"""
High-level ProfileManager API combining store, fingerprint, and launcher.

Provides a single entry point for creating, launching, and managing
antidetect browser profiles with consistent fingerprints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

from .exceptions import ProfileLaunchError
from .fingerprint import capture_fingerprint
from .launcher import launch_profile, launch_profile_sync
from .models import Profile, ProxyConfig
from .store import ProfileStore, ProfileStoreSync
from .warmup import WarmupReport, warmup_profile

logger = logging.getLogger(__name__)


class ProfileManager:
    """
    High-level async API for managing antidetect browser profiles.

    Combines profile storage, fingerprint persistence, and browser launching
    into a single convenient interface.

    Usage:
        pm = ProfileManager("./profiles")
        await pm.initialize()

        # Create a profile
        profile = await pm.create_profile(
            name="shop-account-1",
            os="windows",
            proxy=ProxyConfig(server="http://proxy:8080"),
        )

        # Launch with consistent fingerprint
        async with pm.launch(profile.id) as context:
            page = await context.new_page()
            await page.goto("https://example.com")
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

    async def create_profile(
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
        """
        Create a new profile with a unique, persistent fingerprint.

        The fingerprint is generated once and saved. All subsequent launches
        of this profile will use the same fingerprint.

        Args:
            name: Human-readable profile name (must be unique).
            os: Target OS for fingerprint ('windows', 'macos', 'linux').
            proxy: Fixed proxy for this profile.
            geoip: IP for geo lookup (True=auto from proxy, str=specific IP, None=skip).
            window: Fixed window size (width, height).
            block_webrtc: Block WebRTC entirely.
            fonts: Additional fonts to include.
            tags: User-defined tags for organization.
            notes: Optional notes about this profile.

        Returns:
            Created Profile object.
        """
        # Normalize proxy
        proxy_config = None
        proxy_dict = None
        if proxy:
            if isinstance(proxy, dict):
                proxy_config = ProxyConfig.from_dict(proxy)
            else:
                proxy_config = proxy
            proxy_dict = proxy_config.to_playwright()

        # Auto-enable geoip when proxy is set and geoip is not explicitly disabled
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
            headless=True,  # Don't need screen constraints for fingerprint gen
        )

        # Store profile with fingerprint
        profile = await self.store.create(
            name=name,
            target_os=os,
            fingerprint_config=fingerprint_config,
            proxy=proxy_config,
            tags=tags,
            notes=notes,
        )

        logger.info(
            "Created profile '%s' (id=%s, os=%s, proxy=%s)",
            name,
            profile.id,
            os,
            proxy_config.server if proxy_config else "none",
        )

        return profile

    @asynccontextmanager
    async def launch(
        self,
        profile_id: str,
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

        This is a context manager that handles browser lifecycle automatically.
        On exit, the session is recorded and the browser is closed.

        Args:
            profile_id: ID of the profile to launch.
            headless: Run in headless mode.
            humanize: Enable human-like cursor (True or max duration in seconds).
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

        Creates a browser session and visits popular websites to establish
        cookies, localStorage, and browsing history before real usage.

        Args:
            profile_id: Profile to warm up.
            extra_urls: Additional URLs to visit.
            max_sites: Max number of sites to visit.
            headless: Run warmup in headless mode (recommended).
            **launch_kwargs: Extra args passed to launch().

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

        return report

    # --- Convenience methods delegated to store ---

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
