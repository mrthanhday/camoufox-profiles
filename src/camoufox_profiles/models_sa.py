"""
SQLAlchemy 2.0 declarative models for camoufox-profiles.

Shared between cfox-local (SQLite) and cfox-server (PostgreSQL).
These models define the database schema; business-layer DTOs remain
in models.py (dataclasses) for backward compatibility.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class ProfileModel(Base):
    """Persistent antidetect browser profile."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text)
    target_os: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint_config: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    proxy_server: Mapped[str | None] = mapped_column(Text)
    proxy_username: Mapped[str | None] = mapped_column(Text)
    proxy_password: Mapped[str | None] = mapped_column(Text)
    user_data_dir: Mapped[str] = mapped_column(Text, nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    notes: Mapped[str] = mapped_column(Text, default="")
    drift_schedule: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    firefox_base_version: Mapped[int | None] = mapped_column(Integer)
    proxy_id: Mapped[str | None] = mapped_column(String(36))
    warmup_completed: Mapped[int] = mapped_column(Integer, default=0)
    creation_ip: Mapped[str | None] = mapped_column(Text)
    creation_region: Mapped[str | None] = mapped_column(Text)
    last_known_ip: Mapped[str | None] = mapped_column(Text)
    last_known_region: Mapped[str | None] = mapped_column(Text)

    # Phase 3: Cloud sync fields (nullable — unused until cloud enabled)
    locked_by: Mapped[str | None] = mapped_column(String(36))
    lock_token: Mapped[str | None] = mapped_column(String(36))
    locked_at: Mapped[str | None] = mapped_column(Text)
    lock_expires_at: Mapped[str | None] = mapped_column(Text)
    essential_data_version: Mapped[int] = mapped_column(Integer, default=0)
    essential_data_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    essential_data_checksum: Mapped[str | None] = mapped_column(String(64))
    sync_incomplete: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[str | None] = mapped_column(Text)
    last_sync_machine: Mapped[str | None] = mapped_column(String(36))
    last_heartbeat_at: Mapped[str | None] = mapped_column(Text)

    # Relationships
    drift_events: Mapped[list[DriftEventModel]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_profiles_name", "name"),
        Index("idx_profiles_created", "created_at"),
        Index("idx_profiles_target_os", "target_os"),
    )


class DriftEventModel(Base):
    """Record of a single drift application."""

    __tablename__ = "drift_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    drift_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="")
    new_value: Mapped[str] = mapped_column(Text, default="")

    profile: Mapped[ProfileModel] = relationship(back_populates="drift_events")

    __table_args__ = (
        Index("idx_drift_profile", "profile_id"),
        Index("idx_drift_timestamp", "timestamp"),
    )


class ProxyPoolModel(Base):
    """Centralized proxy pool entry."""

    __tablename__ = "proxy_pool"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    server: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    is_alive: Mapped[int] = mapped_column(Integer, default=1)
    last_checked_at: Mapped[str | None] = mapped_column(Text)
    last_ip: Mapped[str | None] = mapped_column(Text)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    auto_rotate_enabled: Mapped[int] = mapped_column(Integer, default=0)
    rotate_pool_tag: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_proxy_alive", "is_alive"),
    )


class TagMetaModel(Base):
    """Tag metadata for colors and organization."""

    __tablename__ = "tags_meta"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    color: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class SchemaVersion(Base):
    """Schema migration tracking."""

    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[str] = mapped_column(Text, nullable=False)


class UserModel(Base):
    """
    User for cfox-server multi-user auth.

    Only used on the server side (PostgreSQL). On local (SQLite),
    this table exists but remains empty.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")  # "admin", "member"
    label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(Text)
