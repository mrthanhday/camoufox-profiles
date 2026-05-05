"""
camoufox-profiles: Persistent antidetect browser profile management for Camoufox.

Provides consistent fingerprint persistence, profile storage, and browser
launching with the same identity across sessions.

V2 features:
- Natural drift engine for fingerprint aging
- Centralized proxy pool management
- Null-proxy IP consistency guard
- Health diagnostics
- Batch operations
- Encrypted export/import
- CLI (cfox)
"""

from .exceptions import (
    FingerprintCaptureError,
    ProfileLaunchError,
    ProfileNameExistsError,
    ProfileNotFoundError,
    ProxyNotFoundError,
    TransferError,
    WarmupError,
)
from .manager import ProfileManager, ProfileManagerSync
from .models import (
    DriftEvent,
    DriftSchedule,
    HealthCheck,
    HealthReport,
    Profile,
    ProxyConfig,
    ProxyPoolEntry,
)
from .warmup import DEFAULT_WARMUP_SITES, warmup_profile

__all__ = [
    # High-level API
    "ProfileManager",
    "ProfileManagerSync",
    # Models
    "Profile",
    "ProxyConfig",
    "DriftSchedule",
    "DriftEvent",
    "ProxyPoolEntry",
    "HealthCheck",
    "HealthReport",
    # Warmup
    "warmup_profile",
    "DEFAULT_WARMUP_SITES",
    # Exceptions
    "ProfileNotFoundError",
    "ProfileNameExistsError",
    "ProfileLaunchError",
    "FingerprintCaptureError",
    "ProxyNotFoundError",
    "TransferError",
    "WarmupError",
]

__version__ = "0.2.0"
