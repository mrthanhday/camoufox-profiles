"""Data models for camoufox-profiles V2."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import orjson


def _utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def _new_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


@dataclass
class ProxyConfig:
    """
    Fixed proxy binding for a profile.

    Each profile is permanently associated with one proxy to ensure
    geo-consistency between IP, timezone, locale, and fingerprint.
    """

    server: str
    username: Optional[str] = None
    password: Optional[str] = None

    def to_playwright(self) -> Dict[str, str]:
        """Convert to Playwright proxy format."""
        result: Dict[str, str] = {"server": self.server}
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        return result

    def to_dict(self) -> Dict[str, Optional[str]]:
        """Serialize to dict for storage."""
        return {
            "server": self.server,
            "username": self.username,
            "password": self.password,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Optional[str]]) -> ProxyConfig:
        """Deserialize from dict."""
        return cls(
            server=data["server"],  # type: ignore[arg-type]
            username=data.get("username"),
            password=data.get("password"),
        )


@dataclass
class DriftSchedule:
    """Per-profile drift configuration and state."""

    # --- Feature toggles ---
    drift_ua_version: bool = True
    drift_viewport: bool = True
    drift_history_length: bool = True

    # --- Timing ---
    ua_drift_interval_days: int = 28
    viewport_jitter_range: int = 3

    # --- State ---
    last_ua_drift_at: Optional[str] = None
    last_ua_version: Optional[int] = None
    next_ua_drift_at: Optional[str] = None
    total_drifts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON storage."""
        return {
            "drift_ua_version": self.drift_ua_version,
            "drift_viewport": self.drift_viewport,
            "drift_history_length": self.drift_history_length,
            "ua_drift_interval_days": self.ua_drift_interval_days,
            "viewport_jitter_range": self.viewport_jitter_range,
            "last_ua_drift_at": self.last_ua_drift_at,
            "last_ua_version": self.last_ua_version,
            "next_ua_drift_at": self.next_ua_drift_at,
            "total_drifts": self.total_drifts,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DriftSchedule:
        """Deserialize from dict."""
        if not data:
            return cls()
        return cls(
            drift_ua_version=data.get("drift_ua_version", True),
            drift_viewport=data.get("drift_viewport", True),
            drift_history_length=data.get("drift_history_length", True),
            ua_drift_interval_days=data.get("ua_drift_interval_days", 28),
            viewport_jitter_range=data.get("viewport_jitter_range", 3),
            last_ua_drift_at=data.get("last_ua_drift_at"),
            last_ua_version=data.get("last_ua_version"),
            next_ua_drift_at=data.get("next_ua_drift_at"),
            total_drifts=data.get("total_drifts", 0),
        )


@dataclass
class DriftEvent:
    """Record of a single drift application."""

    id: str = field(default_factory=_new_id)
    profile_id: str = ""
    timestamp: str = field(default_factory=lambda: _utcnow().isoformat())
    drift_type: str = ""  # "ua_version", "viewport", "history_length", "geo_ip_change"
    old_value: str = ""
    new_value: str = ""


@dataclass
class ProxyPoolEntry:
    """Centralized proxy pool entry."""

    id: str = field(default_factory=_new_id)
    server: str = ""
    username: Optional[str] = None
    password: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    # Health tracking
    is_alive: bool = True
    last_checked_at: Optional[str] = None
    last_ip: Optional[str] = None
    last_latency_ms: Optional[int] = None
    consecutive_failures: int = 0

    # Metadata
    created_at: str = field(default_factory=lambda: _utcnow().isoformat())
    notes: str = ""

    # Auto-rotation (off by default)
    auto_rotate_enabled: bool = False
    rotate_pool_tag: Optional[str] = None

    def to_playwright(self) -> Dict[str, str]:
        """Convert to Playwright proxy format."""
        result: Dict[str, str] = {"server": self.server}
        if self.username:
            result["username"] = self.username
        if self.password:
            result["password"] = self.password
        return result


@dataclass
class HealthCheck:
    """Result of a single health check."""

    check_name: str
    passed: bool
    severity: str = "info"  # "info", "warning", "critical"
    message: str = ""
    recommendation: str = ""


@dataclass
class HealthReport:
    """Aggregated health report for a profile."""

    profile_id: str
    profile_name: str
    status: str = "healthy"  # "healthy", "warning", "critical"
    checks: List[HealthCheck] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class Profile:
    """
    Represents a persistent antidetect browser profile.

    The fingerprint_config dict contains all Camoufox fingerprint properties
    (navigator.*, screen.*, webGl:*, AudioContext:*, canvas:*, fonts, etc.)
    and is frozen at profile creation time. Drift engine may modify safe
    properties (UA version, viewport) per schedule.
    """

    id: str = field(default_factory=_new_id)
    name: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    last_used_at: Optional[datetime] = None
    target_os: str = "windows"
    fingerprint_config: Dict[str, Any] = field(default_factory=dict)
    proxy: Optional[ProxyConfig] = None
    user_data_dir: str = ""
    total_sessions: int = 0
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    # V2 fields
    drift_schedule: DriftSchedule = field(default_factory=DriftSchedule)
    firefox_base_version: Optional[int] = None
    proxy_id: Optional[str] = None
    warmup_completed: bool = False
    creation_ip: Optional[str] = None
    creation_region: Optional[str] = None
    last_known_ip: Optional[str] = None
    last_known_region: Optional[str] = None

    def to_row(self) -> Dict[str, Any]:
        """Serialize to a flat dict for SQLite storage."""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "target_os": self.target_os,
            "fingerprint_config": orjson.dumps(self.fingerprint_config).decode("utf-8"),
            "proxy_server": self.proxy.server if self.proxy else None,
            "proxy_username": self.proxy.username if self.proxy else None,
            "proxy_password": self.proxy.password if self.proxy else None,
            "user_data_dir": self.user_data_dir,
            "total_sessions": self.total_sessions,
            "tags": orjson.dumps(self.tags).decode("utf-8"),
            "notes": self.notes,
            # V2 fields
            "drift_schedule": orjson.dumps(self.drift_schedule.to_dict()).decode("utf-8"),
            "firefox_base_version": self.firefox_base_version,
            "proxy_id": self.proxy_id,
            "warmup_completed": 1 if self.warmup_completed else 0,
            "creation_ip": self.creation_ip,
            "creation_region": self.creation_region,
            "last_known_ip": self.last_known_ip,
            "last_known_region": self.last_known_region,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> Profile:
        """Deserialize from a SQLite row dict."""
        proxy = None
        if row.get("proxy_server"):
            proxy = ProxyConfig(
                server=row["proxy_server"],
                username=row.get("proxy_username"),
                password=row.get("proxy_password"),
            )

        # Parse drift_schedule (V2, may not exist in V1 rows)
        drift_raw = row.get("drift_schedule", "{}")
        if drift_raw and isinstance(drift_raw, str):
            drift_schedule = DriftSchedule.from_dict(orjson.loads(drift_raw))
        else:
            drift_schedule = DriftSchedule()

        return cls(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used_at=(
                datetime.fromisoformat(row["last_used_at"])
                if row.get("last_used_at")
                else None
            ),
            target_os=row["target_os"],
            fingerprint_config=orjson.loads(row["fingerprint_config"]),
            proxy=proxy,
            user_data_dir=row["user_data_dir"],
            total_sessions=row.get("total_sessions", 0),
            tags=orjson.loads(row.get("tags", "[]")),
            notes=row.get("notes", ""),
            # V2 fields
            drift_schedule=drift_schedule,
            firefox_base_version=row.get("firefox_base_version"),
            proxy_id=row.get("proxy_id"),
            warmup_completed=bool(row.get("warmup_completed", 0)),
            creation_ip=row.get("creation_ip"),
            creation_region=row.get("creation_region"),
            last_known_ip=row.get("last_known_ip"),
            last_known_region=row.get("last_known_region"),
        )
