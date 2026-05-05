"""
camoufox-profiles: Persistent antidetect browser profile management for Camoufox.

Provides consistent fingerprint persistence, profile storage, and browser
launching with the same identity across sessions.
"""

from .exceptions import (
    FingerprintCaptureError,
    ProfileLaunchError,
    ProfileNameExistsError,
    ProfileNotFoundError,
    WarmupError,
)
from .manager import ProfileManager, ProfileManagerSync
from .models import Profile, ProxyConfig
from .warmup import DEFAULT_WARMUP_SITES, warmup_profile

__all__ = [
    # High-level API
    "ProfileManager",
    "ProfileManagerSync",
    # Models
    "Profile",
    "ProxyConfig",
    # Warmup
    "warmup_profile",
    "DEFAULT_WARMUP_SITES",
    # Exceptions
    "ProfileNotFoundError",
    "ProfileNameExistsError",
    "ProfileLaunchError",
    "FingerprintCaptureError",
    "WarmupError",
]

__version__ = "0.1.0"
