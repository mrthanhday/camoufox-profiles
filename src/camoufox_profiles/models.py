"""Data models for camoufox-profiles."""

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
class Profile:
    """
    Represents a persistent antidetect browser profile.

    The fingerprint_config dict contains all Camoufox fingerprint properties
    (navigator.*, screen.*, webGl:*, AudioContext:*, canvas:*, fonts, etc.)
    and is frozen at profile creation time.
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
        )
