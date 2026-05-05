"""
High-level ProfileManager API combining store, fingerprint, and launcher.

V2 enhancements:
- Drift engine integration for fingerprint aging
- Proxy pool management (add, list, health-check)
- Profile health diagnostics
- Batch operations (parallel warmup, batch health check)
- Encrypted export/import
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

from .exceptions import ProfileLaunchError
from .fingerprint import capture_fingerprint
from .launcher import launch_profile, launch_profile_sync
from .models import (
    DriftEvent,
    DriftSchedule,
    HealthReport,
    Profile,
    ProxyConfig,
    ProxyPoolEntry,
)
from .store import ProfileStore, ProfileStoreSync
from .warmup import WarmupReport, warmup_profile

logger = logging.getLogger(__name__)


class ProfileManager:
    """
    High-level async API for managing antidetect browser profiles.

    Combines profile storage, fingerprint persistence, drift engine,
    proxy pool, health checks, and browser launching.

    Usage:
        pm = ProfileManager("./profiles")
        await pm.initialize()

        # Create a profile
        profile = await pm.create_profile(
            name="shop-account-1",
            os="windows",
            proxy=ProxyConfig(server="http://proxy:8080"),
        )

        # Launch with consistent fingerprint + drift
        async with pm.launch(profile.id) as context:
            page = await context.new_page()
            await page.goto("https://example.com")

        # Check health
        report = await pm.health_check(profile.id)
        print(report.status)
    """

    def __init__(self, base_dir: Union[str, Path]):
        """
        Initialize the profile manager.

        Args:
            base_dir: Base directory for storing profiles database and browser data.
        """
        self.base_dir = Path(base_dir)
        self.store = ProfileStore(self.base_dir)

    async def initialize(self) -> None:
        """Create database and directories. Must be called before other methods."""
        await self.store.initialize()
        logger.info("ProfileManager initialized at %s", self.base_dir)

    async def close(self) -> None:
        """Close the database connection."""
        await self.store.close()

    # ── Profile lifecycle ──────────────────────────────────────────

    async def create_profile(
        self,
        name: str,
        os: str = "windows",
        proxy: Optional[Union[ProxyConfig, Dict[str, str]]] = None,
        proxy_id: Optional[str] = None,
        geoip: Optional[Union[str, bool]] = None,
        window: Optional[Tuple[int, int]] = None,
        block_webrtc: bool = False,
        fonts: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        notes: str = "",
    ) -> Profile:
        """
        Create a new profile with a unique, persistent fingerprint.

        The fingerprint is generated once and saved. All subsequent launches
        of this profile will use the same fingerprint.

        Args:
            name: Human-readable profile name (must be unique).
            os: Target OS for fingerprint ('windows', 'macos', 'linux').
            proxy: Fixed inline proxy for this profile.
            proxy_id: Proxy pool entry ID to bind (overrides inline proxy).
            geoip: IP for geo lookup (True=auto, str=specific IP, None=skip).
            window: Fixed window size (width, height).
            block_webrtc: Block WebRTC entirely.
            fonts: Additional fonts to include.
            tags: User-defined tags for organization.
            notes: Optional notes about this profile.

        Returns:
            Created Profile object.
        """
        # Resolve proxy from pool if proxy_id is provided
        proxy_config = None
        proxy_dict = None

        if proxy_id:
            from .proxy import ProxyStore
            ps = ProxyStore(self.store._ensure_db())
            entry = await ps.get(proxy_id)
            if entry:
                proxy_dict = entry.to_playwright()
        elif proxy:
            if isinstance(proxy, dict):
                proxy_config = ProxyConfig.from_dict(proxy)
            else:
                proxy_config = proxy
            proxy_dict = proxy_config.to_playwright()

        # Auto-enable geoip when proxy is set
        if proxy_dict and geoip is None:
            geoip = True

        # Generate fingerprint ONCE
        fingerprint_config = capture_fingerprint(
            target_os=os,
            proxy=proxy_dict,
            geoip=geoip,
            window=window,
            block_webrtc=block_webrtc,
            fonts=fonts,
            headless=True,
        )

        # Resolve creation IP/region
        creation_ip = None
        creation_region = None
        try:
            from camoufox.ip import public_ip
            from camoufox.locale import get_geolocation

            if proxy_dict:
                from camoufox.ip import Proxy
                creation_ip = public_ip(Proxy(**proxy_dict).as_string())
            else:
                creation_ip = public_ip()
            geo = get_geolocation(creation_ip)
            creation_region = geo.locale.region
        except Exception as e:
            logger.debug("Could not resolve creation IP/region: %s", e)

        # Store profile with fingerprint
        profile = await self.store.create(
            name=name,
            target_os=os,
            fingerprint_config=fingerprint_config,
            proxy=proxy_config,
            tags=tags,
            notes=notes,
            proxy_id=proxy_id,
            creation_ip=creation_ip,
            creation_region=creation_region,
        )

        logger.info(
            "Created profile '%s' (id=%s, os=%s, proxy=%s, region=%s)",
            name,
            profile.id,
            os,
            proxy_config.server if proxy_config else proxy_id or "none",
            creation_region or "unknown",
        )

        return profile

    @asynccontextmanager
    async def launch(
        self,
        profile_id: str,
        drift: bool = True,
        headless: bool = False,
        humanize: Optional[Union[bool, float]] = None,
        addons: Optional[List[str]] = None,
        enable_cache: bool = True,
        firefox_user_prefs: Optional[Dict[str, Any]] = None,
        extra_args: Optional[List[str]] = None,
        **extra_launch_options: Any,
    ) -> AsyncIterator[Any]:
        """
        Launch a browser with a saved profile's fingerprint.

        V2 enhancements:
        - IP consistency guard runs automatically for null-proxy profiles
        - Drift engine applies UA version bumps, viewport jitter per schedule

        Args:
            profile_id: ID of the profile to launch.
            drift: Enable drift engine (default True). Note: IP consistency
                guard ALWAYS runs regardless of this setting.
            headless: Run in headless mode.
            humanize: Enable human-like cursor (True or max duration).
            addons: Firefox addon paths.
            enable_cache: Enable browser cache.
            firefox_user_prefs: Firefox preferences.
            extra_args: Extra browser launch arguments.

        Yields:
            Playwright BrowserContext with persistent storage.
        """
        profile = await self.store.get(profile_id)

        async with launch_profile(
            profile=profile,
            store=self.store,
            drift=drift,
            headless=headless,
            humanize=humanize,
            addons=addons,
            enable_cache=enable_cache,
            firefox_user_prefs=firefox_user_prefs,
            extra_args=extra_args,
            **extra_launch_options,
        ) as context:
            yield context

    async def warmup(
        self,
        profile_id: str,
        extra_urls: Optional[List[str]] = None,
        max_sites: int = 10,
        headless: bool = True,
        **launch_kwargs: Any,
    ) -> WarmupReport:
        """
        Run warmup on a profile to build natural browsing history.

        After warmup, the profile is marked as warmup_completed=True.

        Args:
            profile_id: Profile to warm up.
            extra_urls: Additional URLs to visit.
            max_sites: Max number of sites to visit.
            headless: Run in headless mode (recommended).

        Returns:
            WarmupReport with visit details.
        """
        async with self.launch(
            profile_id,
            headless=headless,
            enable_cache=True,
            **launch_kwargs,
        ) as context:
            report = await warmup_profile(
                context=context,
                profile_id=profile_id,
                extra_urls=extra_urls,
                max_sites=max_sites,
            )

        # Mark warmup completed
        await self.store.update_v2_fields(profile_id, warmup_completed=True)

        return report

    # ── Health checks ──────────────────────────────────────────────

    async def health_check(self, profile_id: str) -> HealthReport:
        """
        Run comprehensive health checks on a profile.

        Checks include: UA staleness, IP region consistency, proxy health,
        browser data integrity, and drift schedule status.

        Returns:
            HealthReport with all check results and recommendations.
        """
        from .health import check_profile_health

        profile = await self.store.get(profile_id)

        # Get installed Firefox version
        installed_ff = None
        try:
            from .drift import _get_installed_firefox_version
            installed_ff = _get_installed_firefox_version()
        except Exception:
            pass

        # Get current IP for null-proxy profiles
        current_ip = None
        current_region = None
        if not profile.proxy_id and not profile.proxy:
            try:
                from camoufox.ip import public_ip
                from camoufox.locale import get_geolocation
                current_ip = public_ip()
                geo = get_geolocation(current_ip)
                current_region = geo.locale.region
            except Exception:
                pass

        return await check_profile_health(
            profile,
            installed_ff_version=installed_ff,
            current_public_ip=current_ip,
            current_region=current_region,
        )

    async def batch_health_check(
        self,
        profile_ids: Optional[List[str]] = None,
        concurrency: int = 5,
    ) -> Dict[str, HealthReport]:
        """
        Run health checks on multiple profiles in parallel.

        Args:
            profile_ids: List of profile IDs. If None, checks all profiles.
            concurrency: Max parallel checks.

        Returns:
            Dict mapping profile_id → HealthReport.
        """
        from .batch import batch_health_check

        if profile_ids is None:
            profiles = await self.store.list(limit=10000)
            profile_ids = [p.id for p in profiles]

        return await batch_health_check(self.store, profile_ids, concurrency)

    # ── Drift management ───────────────────────────────────────────

    async def get_drift_history(self, profile_id: str, limit: int = 50) -> List[DriftEvent]:
        """Get drift event history for a profile."""
        return await self.store.get_drift_history(profile_id, limit)

    async def update_drift_schedule(
        self,
        profile_id: str,
        drift_ua_version: Optional[bool] = None,
        drift_viewport: Optional[bool] = None,
        drift_history_length: Optional[bool] = None,
        ua_drift_interval_days: Optional[int] = None,
        viewport_jitter_range: Optional[int] = None,
    ) -> DriftSchedule:
        """
        Update drift schedule settings for a profile.

        Args:
            profile_id: Profile to update.
            drift_ua_version: Enable/disable UA version drift.
            drift_viewport: Enable/disable viewport jitter.
            drift_history_length: Enable/disable history length randomization.
            ua_drift_interval_days: Days between UA version bumps.
            viewport_jitter_range: Max pixels to jitter viewport.

        Returns:
            Updated DriftSchedule.
        """
        profile = await self.store.get(profile_id)
        schedule = profile.drift_schedule

        if drift_ua_version is not None:
            schedule.drift_ua_version = drift_ua_version
        if drift_viewport is not None:
            schedule.drift_viewport = drift_viewport
        if drift_history_length is not None:
            schedule.drift_history_length = drift_history_length
        if ua_drift_interval_days is not None:
            schedule.ua_drift_interval_days = ua_drift_interval_days
        if viewport_jitter_range is not None:
            schedule.viewport_jitter_range = viewport_jitter_range

        await self.store.update_v2_fields(profile_id, drift_schedule=schedule)
        return schedule

    # ── Proxy pool ─────────────────────────────────────────────────

    async def add_proxy(
        self,
        server: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> ProxyPoolEntry:
        """Add a proxy to the centralized pool."""
        from .proxy import ProxyStore
        ps = ProxyStore(self.store._ensure_db())
        return await ps.add(server, username, password, tags or [])

    async def list_proxies(
        self,
        tag: Optional[str] = None,
        alive_only: bool = False,
    ) -> List[ProxyPoolEntry]:
        """List proxies in the pool."""
        from .proxy import ProxyStore
        ps = ProxyStore(self.store._ensure_db())
        return await ps.list(tag=tag, alive_only=alive_only)

    async def check_proxies(self, concurrency: int = 5) -> List[Tuple[str, bool, Optional[str], Optional[int]]]:
        """Health-check all proxies in the pool."""
        from .proxy import ProxyStore
        ps = ProxyStore(self.store._ensure_db())
        return await ps.check_all(concurrency=concurrency)

    async def bind_proxy(self, profile_id: str, proxy_id: str) -> None:
        """Bind a proxy pool entry to a profile."""
        await self.store.update_v2_fields(profile_id, proxy_id=proxy_id)
        logger.info("Bound proxy %s to profile %s", proxy_id[:8], profile_id[:8])

    # ── Export / Import ────────────────────────────────────────────

    async def export_profile(
        self,
        profile_id: str,
        output_path: str,
        password: Optional[str] = None,
    ) -> str:
        """
        Export a profile to a ZIP archive.

        Args:
            profile_id: Profile to export.
            output_path: Destination path for the ZIP file.
            password: Optional AES-256 encryption password.

        Returns:
            Absolute path to the created ZIP file.
        """
        from .transfer import export_profile
        profile = await self.store.get(profile_id)
        return await export_profile(profile, output_path, password)

    async def import_profile(
        self,
        zip_path: str,
        new_name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> Profile:
        """
        Import a profile from a ZIP archive.

        Args:
            zip_path: Path to the ZIP file.
            new_name: Optional name override.
            password: Decryption password for encrypted archives.

        Returns:
            The imported Profile object.
        """
        from .transfer import import_profile
        return await import_profile(self.store, zip_path, new_name, password)

    # ── Convenience methods delegated to store ─────────────────────

    async def get_profile(self, profile_id: str) -> Profile:
        """Get a profile by ID."""
        return await self.store.get(profile_id)

    async def get_profile_by_name(self, name: str) -> Profile:
        """Get a profile by name."""
        return await self.store.get_by_name(name)

    async def list_profiles(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Profile]:
        """List profiles with optional filters."""
        return await self.store.list(
            tag=tag, target_os=target_os, search=search, limit=limit, offset=offset
        )

    async def update_profile(self, profile_id: str, **kwargs: Any) -> Profile:
        """Update mutable profile fields (name, tags, notes)."""
        return await self.store.update(profile_id, **kwargs)

    async def delete_profile(self, profile_id: str) -> None:
        """Delete a profile and its browser data."""
        await self.store.delete(profile_id)

    async def count_profiles(self, **kwargs: Any) -> int:
        """Count profiles with optional filters."""
        return await self.store.count(**kwargs)


class ProfileManagerSync:
    """
    Synchronous version of ProfileManager.

    Note: V2 features (drift, IP guard, proxy pool, health checks) are
    best used through the async ProfileManager. The sync version provides
    basic profile creation, launching, and storage operations.

    Usage:
        pm = ProfileManagerSync("./profiles")
        pm.initialize()

        profile = pm.create_profile(name="test", os="windows")

        with pm.launch(profile.id) as context:
            page = context.new_page()
            page.goto("https://example.com")
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)
        self.store = ProfileStoreSync(self.base_dir)

    def initialize(self) -> None:
        """Create database and directories."""
        self.store.initialize()
        logger.info("ProfileManagerSync initialized at %s", self.base_dir)

    def close(self) -> None:
        """Close the database connection."""
        self.store.close()

    def create_profile(
        self,
        name: str,
        os: str = "windows",
        proxy: Optional[Union[ProxyConfig, Dict[str, str]]] = None,
        geoip: Optional[Union[str, bool]] = None,
        window: Optional[Tuple[int, int]] = None,
        block_webrtc: bool = False,
        fonts: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        notes: str = "",
    ) -> Profile:
        """Create a new profile with a persistent fingerprint."""
        proxy_config = None
        proxy_dict = None
        if proxy:
            if isinstance(proxy, dict):
                proxy_config = ProxyConfig.from_dict(proxy)
            else:
                proxy_config = proxy
            proxy_dict = proxy_config.to_playwright()

        if proxy_dict and geoip is None:
            geoip = True

        fingerprint_config = capture_fingerprint(
            target_os=os,
            proxy=proxy_dict,
            geoip=geoip,
            window=window,
            block_webrtc=block_webrtc,
            fonts=fonts,
            headless=True,
        )

        profile = self.store.create(
            name=name,
            target_os=os,
            fingerprint_config=fingerprint_config,
            proxy=proxy_config,
            tags=tags,
            notes=notes,
        )

        logger.info("Created profile '%s' (id=%s)", name, profile.id)
        return profile

    @contextmanager
    def launch(
        self,
        profile_id: str,
        drift: bool = True,
        headless: bool = False,
        humanize: Optional[Union[bool, float]] = None,
        addons: Optional[List[str]] = None,
        enable_cache: bool = True,
        firefox_user_prefs: Optional[Dict[str, Any]] = None,
        extra_args: Optional[List[str]] = None,
        **extra_launch_options: Any,
    ) -> Iterator[Any]:
        """Launch a browser with a saved profile's fingerprint."""
        profile = self.store.get(profile_id)

        with launch_profile_sync(
            profile=profile,
            store=self.store,
            drift=drift,
            headless=headless,
            humanize=humanize,
            addons=addons,
            enable_cache=enable_cache,
            firefox_user_prefs=firefox_user_prefs,
            extra_args=extra_args,
            **extra_launch_options,
        ) as context:
            yield context

    # --- Convenience methods ---

    def get_profile(self, profile_id: str) -> Profile:
        return self.store.get(profile_id)

    def get_profile_by_name(self, name: str) -> Profile:
        return self.store.get_by_name(name)

    def list_profiles(self, **kwargs: Any) -> List[Profile]:
        return self.store.list(**kwargs)

    def update_profile(self, profile_id: str, **kwargs: Any) -> Profile:
        return self.store.update(profile_id, **kwargs)

    def delete_profile(self, profile_id: str) -> None:
        self.store.delete(profile_id)

    def count_profiles(self, **kwargs: Any) -> int:
        return self.store.count(**kwargs)
