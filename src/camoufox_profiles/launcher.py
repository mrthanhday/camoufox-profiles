"""
Profile-aware browser launcher for Camoufox.

Launches browsers with saved fingerprint configs and persistent contexts,
ensuring the same identity across sessions.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Dict, Iterator, Optional, Union

from .exceptions import ProfileLaunchError
from .fingerprint import build_launch_options
from .models import Profile
from .store import ProfileStore, ProfileStoreSync

logger = logging.getLogger(__name__)


@asynccontextmanager
async def launch_profile(
    profile: Profile,
    store: ProfileStore,
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

    This is an async context manager that:
    1. Loads the fingerprint config from the profile
    2. Builds launch options with persistent context
    3. Launches the browser via Playwright
    4. Records the session on exit

    Args:
        profile: Profile object to launch.
        store: ProfileStore instance for recording sessions.
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

    # Build launch options from saved fingerprint
    proxy = profile.proxy.to_playwright() if profile.proxy else None

    opts = build_launch_options(
        fingerprint_config=profile.fingerprint_config,
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

    # Merge any extra launch options
    opts.update(extra_launch_options)

    logger.info(
        "Launching profile '%s' (id=%s, os=%s, sessions=%d)",
        profile.name,
        profile.id,
        profile.target_os,
        profile.total_sessions,
    )

    playwright = None
    context = None
    try:
        playwright = await async_playwright().start()

        # Launch as persistent context to preserve storage state
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

        # Cleanup
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

    Yields:
        Playwright BrowserContext (persistent).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ProfileLaunchError(
            profile.id, "playwright package is required"
        ) from e

    proxy = profile.proxy.to_playwright() if profile.proxy else None

    opts = build_launch_options(
        fingerprint_config=profile.fingerprint_config,
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
        "Launching profile '%s' (id=%s, os=%s, sessions=%d)",
        profile.name,
        profile.id,
        profile.target_os,
        profile.total_sessions,
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
