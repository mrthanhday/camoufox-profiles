"""
Profile-aware browser launcher for Camoufox.

Launches browsers with saved fingerprint configs and persistent contexts,
ensuring the same identity across sessions. V2 adds:
- IP consistency guard for null-proxy profiles
- Drift engine integration
- Proxy pool resolution
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

from .exceptions import ProfileLaunchError
from .fingerprint import build_launch_options
from .models import DriftEvent, Profile
from .store import ProfileStore, ProfileStoreSync

logger = logging.getLogger(__name__)


async def _check_ip_consistency(
    profile: Profile,
    config: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[DriftEvent], Optional[str], Optional[str]]:
    """
    Pre-launch IP region check for null-proxy profiles.

    If the current public IP's region differs from the region stored at
    creation, recalculates all geo properties (timezone, locale, geolocation,
    webrtc IP) to prevent anti-bot detection.

    This runs even when drift=False — it's a safety guard, not cosmetic.

    Returns:
        Tuple of (updated_config, drift_events, current_ip, current_region).
    """
    from .models import DriftEvent, _new_id, _utcnow

    # Skip for proxied profiles
    if profile.proxy_id or profile.proxy:
        return config, [], None, None

    try:
        from camoufox.ip import public_ip
        from camoufox.locale import get_geolocation
    except ImportError:
        logger.debug("camoufox geoip not available, skipping IP consistency check")
        return config, [], None, None

    try:
        current_ip = public_ip()
    except Exception as e:
        logger.warning("Could not resolve public IP for consistency check: %s", e)
        return config, [], None, None

    try:
        current_geo = get_geolocation(current_ip)
        current_region = current_geo.locale.region
    except Exception as e:
        logger.warning("Could not geolocate IP %s: %s", current_ip, e)
        return config, [], current_ip, None

    stored_region = config.get("locale:region") or profile.creation_region
    stored_timezone = config.get("timezone", "")

    if not stored_region:
        # No region info stored — first time or V1 profile, skip
        return config, [], current_ip, current_region

    # Same region → safe, just update webrtc IP silently
    if current_region == stored_region:
        if config.get("webrtc:ipv4"):
            config["webrtc:ipv4"] = current_ip
        return config, [], current_ip, current_region

    # Region changed → recalculate all geo properties
    logger.warning(
        "IP region changed: %s → %s (profile '%s'). "
        "Recalculating geo properties to avoid detection.",
        stored_region, current_region, profile.name,
    )

    geo_config = current_geo.as_config()
    config.update(geo_config)  # Overwrite timezone, locale, geolocation
    if config.get("webrtc:ipv4"):
        config["webrtc:ipv4"] = current_ip

    events = [DriftEvent(
        id=_new_id(),
        profile_id=profile.id,
        timestamp=_utcnow().isoformat(),
        drift_type="geo_ip_change",
        old_value=f"{stored_region}/{stored_timezone}",
        new_value=f"{current_region}/{current_geo.timezone}",
    )]

    return config, events, current_ip, current_region


def _apply_drift(profile: Profile, config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[DriftEvent], Any]:
    """Apply drift engine to a config. Returns updated config, events, and new schedule."""
    from .drift import DriftEngine
    engine = DriftEngine()
    return engine.apply_drift(profile)


@asynccontextmanager
async def launch_profile(
    profile: Profile,
    store: ProfileStore,
    drift: bool = True,
    headless: bool = False,
    humanize: Optional[Union[bool, float]] = None,
    addons: Optional[list[str]] = None,
    enable_cache: bool = True,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    extra_args: Optional[list[str]] = None,
    **extra_launch_options: Any,
) -> AsyncIterator[Any]:
    """
    Launch a Camoufox browser with a saved profile's fingerprint.

    V2 enhancements:
    - IP consistency guard (always runs for null-proxy profiles)
    - Drift engine (controllable via drift=True/False)
    - Proxy pool resolution

    Args:
        profile: Profile object to launch.
        store: ProfileStore instance for recording sessions.
        drift: Enable drift engine (UA version, viewport jitter). Default True.
        headless: Run browser in headless mode.
        humanize: Enable human-like cursor movement.
        addons: Additional Firefox addons.
        enable_cache: Cache pages and requests.
        firefox_user_prefs: Firefox user preferences.
        extra_args: Extra browser launch args.
        **extra_launch_options: Passed through to Playwright.

    Yields:
        Playwright BrowserContext (persistent).

    Raises:
        ProfileLaunchError: If browser fails to launch.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise ProfileLaunchError(
            profile.id, "playwright package is required"
        ) from e

    # Work on a copy of the fingerprint config
    config = dict(profile.fingerprint_config)

    # --- ALWAYS: IP consistency guard for null-proxy profiles ---
    ip_events: List[DriftEvent] = []
    try:
        config, ip_events, current_ip, current_region = await _check_ip_consistency(
            profile, config
        )
        if ip_events:
            await store.record_drift_events(profile.id, ip_events)
        # Update last known IP in store
        if current_ip:
            await store.update_v2_fields(
                profile.id,
                last_known_ip=current_ip,
                last_known_region=current_region,
            )
    except Exception as e:
        logger.warning("IP consistency check failed (non-fatal): %s", e)

    # --- OPTIONAL: Apply drift engine ---
    if drift and profile.drift_schedule:
        try:
            config, drift_events, updated_schedule = _apply_drift(profile, config)
            if drift_events:
                await store.record_drift_events(profile.id, drift_events)
                await store.update_v2_fields(
                    profile.id,
                    drift_schedule=updated_schedule,
                    fingerprint_config=config,
                )
        except Exception as e:
            logger.warning("Drift engine failed (non-fatal): %s", e)

    # Resolve proxy
    proxy = None
    if profile.proxy:
        proxy = profile.proxy.to_playwright()
    elif profile.proxy_id:
        try:
            from .proxy import ProxyStore
            proxy_store = ProxyStore(store._ensure_db())
            entry = await proxy_store.get(profile.proxy_id)
            if entry:
                proxy = entry.to_playwright()
        except Exception as e:
            logger.warning("Could not resolve proxy_id %s: %s", profile.proxy_id, e)

    # Build launch options from (potentially modified) config
    opts = build_launch_options(
        fingerprint_config=config,
        proxy=proxy,
        user_data_dir=profile.user_data_dir,
        headless=headless,
        humanize=humanize,
        addons=addons,
        enable_cache=enable_cache,
        firefox_user_prefs=firefox_user_prefs,
        extra_args=extra_args,
    )

    # Extract persistent context specific options
    user_data_dir = opts.pop("user_data_dir", profile.user_data_dir)
    opts.update(extra_launch_options)

    logger.info(
        "Launching profile '%s' (id=%s, os=%s, sessions=%d, drift=%s)",
        profile.name,
        profile.id,
        profile.target_os,
        profile.total_sessions,
        drift,
    )

    playwright = None
    context = None
    try:
        playwright = await async_playwright().start()

        context = await playwright.firefox.launch_persistent_context(
            user_data_dir=user_data_dir,
            **opts,
        )

        logger.info("Browser launched successfully for profile '%s'", profile.name)
        yield context

    except Exception as e:
        if not isinstance(e, (GeneratorExit, ProfileLaunchError)):
            raise ProfileLaunchError(profile.id, str(e)) from e
        raise
    finally:
        # Record session
        try:
            await store.record_session(profile.id)
        except Exception:
            logger.warning("Failed to record session for profile '%s'", profile.name)

        if context:
            try:
                await context.close()
            except Exception:
                logger.warning("Failed to close browser context")

        if playwright:
            try:
                await playwright.stop()
            except Exception:
                logger.warning("Failed to stop playwright")


@contextmanager
def launch_profile_sync(
    profile: Profile,
    store: ProfileStoreSync,
    drift: bool = True,
    headless: bool = False,
    humanize: Optional[Union[bool, float]] = None,
    addons: Optional[list[str]] = None,
    enable_cache: bool = True,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    extra_args: Optional[list[str]] = None,
    **extra_launch_options: Any,
) -> Iterator[Any]:
    """
    Synchronous version of launch_profile.

    Note: IP consistency guard and drift are async-only operations.
    The sync launcher applies drift synchronously if possible.

    Yields:
        Playwright BrowserContext (persistent).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ProfileLaunchError(
            profile.id, "playwright package is required"
        ) from e

    config = dict(profile.fingerprint_config)

    # Apply drift synchronously (simplified — no IP consistency guard in sync mode)
    if drift and profile.drift_schedule:
        try:
            config, drift_events, updated_schedule = _apply_drift(profile, config)
            # Note: drift events and schedule updates are not persisted in sync mode
            # Use async API for full drift support
            if drift_events:
                logger.info(
                    "Drift applied in sync mode (%d events). Use async API for full persistence.",
                    len(drift_events),
                )
        except Exception as e:
            logger.warning("Drift engine failed (non-fatal): %s", e)

    proxy = profile.proxy.to_playwright() if profile.proxy else None

    opts = build_launch_options(
        fingerprint_config=config,
        proxy=proxy,
        user_data_dir=profile.user_data_dir,
        headless=headless,
        humanize=humanize,
        addons=addons,
        enable_cache=enable_cache,
        firefox_user_prefs=firefox_user_prefs,
        extra_args=extra_args,
    )

    user_data_dir = opts.pop("user_data_dir", profile.user_data_dir)
    opts.update(extra_launch_options)

    logger.info(
        "Launching profile '%s' (id=%s, os=%s, sessions=%d, drift=%s)",
        profile.name,
        profile.id,
        profile.target_os,
        profile.total_sessions,
        drift,
    )

    playwright = None
    context = None
    try:
        playwright = sync_playwright().start()
        context = playwright.firefox.launch_persistent_context(
            user_data_dir=user_data_dir,
            **opts,
        )

        logger.info("Browser launched successfully for profile '%s'", profile.name)
        yield context

    except Exception as e:
        if not isinstance(e, (GeneratorExit, ProfileLaunchError)):
            raise ProfileLaunchError(profile.id, str(e)) from e
        raise
    finally:
        try:
            store.record_session(profile.id)
        except Exception:
            logger.warning("Failed to record session for profile '%s'", profile.name)

        if context:
            try:
                context.close()
            except Exception:
                logger.warning("Failed to close browser context")

        if playwright:
            try:
                playwright.stop()
            except Exception:
                logger.warning("Failed to stop playwright")
