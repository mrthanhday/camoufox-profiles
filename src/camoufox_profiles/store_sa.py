"""
SQLAlchemy-backed profile storage.

Drop-in replacement for store.py using SQLAlchemy async sessions instead
of raw aiosqlite. Same public API — ProfileManager doesn't need changes
beyond swapping the import.

Works with both SQLite (aiosqlite) and PostgreSQL (asyncpg).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import orjson
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .exceptions import ProfileNameExistsError, ProfileNotFoundError
from .models import (
    DriftEvent,
    DriftSchedule,
    Profile,
    ProxyConfig,
    ProxyPoolEntry,
    _new_id,
    _utcnow,
)
from .models_sa import (
    DriftEventModel,
    ProfileModel,
    ProxyPoolModel,
    TagMetaModel,
)


def _profile_to_model(profile: Profile) -> ProfileModel:
    """Convert a Profile dataclass to a SQLAlchemy model instance."""
    return ProfileModel(
        id=profile.id,
        name=profile.name,
        created_at=profile.created_at.isoformat(),
        last_used_at=profile.last_used_at.isoformat() if profile.last_used_at else None,
        target_os=profile.target_os,
        fingerprint_config=orjson.dumps(profile.fingerprint_config).decode("utf-8"),
        proxy_server=profile.proxy.server if profile.proxy else None,
        proxy_username=profile.proxy.username if profile.proxy else None,
        proxy_password=profile.proxy.password if profile.proxy else None,
        user_data_dir=profile.user_data_dir,
        total_sessions=profile.total_sessions,
        tags=orjson.dumps(profile.tags).decode("utf-8"),
        notes=profile.notes,
        drift_schedule=orjson.dumps(profile.drift_schedule.to_dict()).decode("utf-8"),
        firefox_base_version=profile.firefox_base_version,
        proxy_id=profile.proxy_id,
        warmup_completed=1 if profile.warmup_completed else 0,
        creation_ip=profile.creation_ip,
        creation_region=profile.creation_region,
        last_known_ip=profile.last_known_ip,
        last_known_region=profile.last_known_region,
    )


def _model_to_profile(m: ProfileModel) -> Profile:
    """Convert a SQLAlchemy model instance to a Profile dataclass."""
    from datetime import datetime

    proxy = None
    if m.proxy_server:
        proxy = ProxyConfig(
            server=m.proxy_server,
            username=m.proxy_username,
            password=m.proxy_password,
        )

    drift_raw = m.drift_schedule or "{}"
    drift_schedule = DriftSchedule.from_dict(orjson.loads(drift_raw))

    return Profile(
        id=m.id,
        name=m.name,
        created_at=datetime.fromisoformat(m.created_at),
        last_used_at=datetime.fromisoformat(m.last_used_at) if m.last_used_at else None,
        target_os=m.target_os,
        fingerprint_config=orjson.loads(m.fingerprint_config),
        proxy=proxy,
        user_data_dir=m.user_data_dir,
        total_sessions=m.total_sessions or 0,
        tags=orjson.loads(m.tags or "[]"),
        notes=m.notes or "",
        drift_schedule=drift_schedule,
        firefox_base_version=m.firefox_base_version,
        proxy_id=m.proxy_id,
        warmup_completed=bool(m.warmup_completed),
        creation_ip=m.creation_ip,
        creation_region=m.creation_region,
        last_known_ip=m.last_known_ip,
        last_known_region=m.last_known_region,
    )


class ProfileStoreSA:
    """
    Async SQLAlchemy-backed profile storage.

    Same public API as ProfileStore (store.py) — drop-in replacement.
    Uses SQLAlchemy sessions instead of raw aiosqlite for cross-dialect support.
    """

    def __init__(
        self,
        base_dir: Union[str, Path],
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.base_dir = Path(base_dir)
        self.browser_data_dir = self.base_dir / "browser_data"
        self._session_factory = session_factory

    async def initialize(self) -> None:
        """Create directories. Database init is handled externally via init_db()."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """No-op. Engine lifecycle is managed externally."""
        pass

    def _profile_data_dir(self, profile_id: str) -> str:
        """Get the browser data directory path for a profile."""
        return str(self.browser_data_dir / profile_id)

    # ── CRUD ───────────────────────────────────────────────────────

    async def create(
        self,
        name: str,
        target_os: str,
        fingerprint_config: Dict[str, Any],
        proxy: Optional[ProxyConfig] = None,
        tags: Optional[List[str]] = None,
        notes: str = "",
        proxy_id: Optional[str] = None,
        creation_ip: Optional[str] = None,
        creation_region: Optional[str] = None,
    ) -> Profile:
        """
        Create a new profile with the given fingerprint config.

        Raises:
            ProfileNameExistsError: If a profile with this name already exists.
        """
        async with self._session_factory() as session:
            # Check name uniqueness
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.name == name)
            )
            if result.scalar_one_or_none():
                raise ProfileNameExistsError(name)

            profile_id = _new_id()
            user_data_dir = self._profile_data_dir(profile_id)
            os.makedirs(user_data_dir, exist_ok=True)

            # Determine Firefox version from config
            import re
            ua = fingerprint_config.get("navigator.userAgent", "")
            ff_version = None
            match = re.search(r"Firefox/(\d+)\.0", ua)
            if match:
                ff_version = int(match.group(1))

            profile = Profile(
                id=profile_id,
                name=name,
                created_at=_utcnow(),
                target_os=target_os,
                fingerprint_config=fingerprint_config,
                proxy=proxy,
                user_data_dir=user_data_dir,
                tags=tags or [],
                notes=notes,
                firefox_base_version=ff_version,
                proxy_id=proxy_id,
                creation_ip=creation_ip,
                creation_region=creation_region,
                last_known_ip=creation_ip,
                last_known_region=creation_region,
            )

            model = _profile_to_model(profile)
            session.add(model)
            await session.commit()

        return profile

    async def get(self, profile_id: str) -> Profile:
        """
        Load a profile by ID.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.id == profile_id)
            )
            model = result.scalar_one_or_none()

        if not model:
            raise ProfileNotFoundError(profile_id)

        return _model_to_profile(model)

    async def get_by_name(self, name: str) -> Profile:
        """
        Load a profile by name.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProfileModel).where(ProfileModel.name == name)
            )
            model = result.scalar_one_or_none()

        if not model:
            raise ProfileNotFoundError(name)

        return _model_to_profile(model)

    async def list(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Profile]:
        """List profiles with optional filters and pagination."""
        stmt = select(ProfileModel)

        if tag:
            stmt = stmt.where(ProfileModel.tags.contains(f'"{tag}"'))

        if target_os:
            stmt = stmt.where(ProfileModel.target_os == target_os)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                ProfileModel.name.ilike(pattern) | ProfileModel.notes.ilike(pattern)
            )

        stmt = stmt.order_by(ProfileModel.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            models = result.scalars().all()

        return [_model_to_profile(m) for m in models]

    async def update(
        self,
        profile_id: str,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        last_used_at: Optional[str] = None,
        total_sessions: Optional[int] = None,
    ) -> Profile:
        """
        Update mutable fields of a profile.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
            ProfileNameExistsError: If new name conflicts.
        """
        # Verify profile exists
        await self.get(profile_id)

        async with self._session_factory() as session:
            if name is not None:
                # Check name uniqueness
                result = await session.execute(
                    select(ProfileModel).where(
                        ProfileModel.name == name,
                        ProfileModel.id != profile_id,
                    )
                )
                if result.scalar_one_or_none():
                    raise ProfileNameExistsError(name)

            values: Dict[str, Any] = {}
            if name is not None:
                values["name"] = name
            if tags is not None:
                values["tags"] = orjson.dumps(tags).decode("utf-8")
            if notes is not None:
                values["notes"] = notes
            if last_used_at is not None:
                values["last_used_at"] = last_used_at
            if total_sessions is not None:
                values["total_sessions"] = total_sessions

            if values:
                await session.execute(
                    update(ProfileModel)
                    .where(ProfileModel.id == profile_id)
                    .values(**values)
                )
                await session.commit()

        return await self.get(profile_id)

    async def update_v2_fields(
        self,
        profile_id: str,
        drift_schedule: Optional[DriftSchedule] = None,
        fingerprint_config: Optional[Dict[str, Any]] = None,
        proxy_id: Optional[str] = None,
        warmup_completed: Optional[bool] = None,
        creation_ip: Optional[str] = None,
        creation_region: Optional[str] = None,
        last_known_ip: Optional[str] = None,
        last_known_region: Optional[str] = None,
    ) -> None:
        """Update V2-specific fields."""
        values: Dict[str, Any] = {}

        if drift_schedule is not None:
            values["drift_schedule"] = orjson.dumps(drift_schedule.to_dict()).decode("utf-8")
        if fingerprint_config is not None:
            values["fingerprint_config"] = orjson.dumps(fingerprint_config).decode("utf-8")
        if proxy_id is not None:
            values["proxy_id"] = proxy_id
        if warmup_completed is not None:
            values["warmup_completed"] = 1 if warmup_completed else 0
        if creation_ip is not None:
            values["creation_ip"] = creation_ip
        if creation_region is not None:
            values["creation_region"] = creation_region
        if last_known_ip is not None:
            values["last_known_ip"] = last_known_ip
        if last_known_region is not None:
            values["last_known_region"] = last_known_region

        if values:
            async with self._session_factory() as session:
                await session.execute(
                    update(ProfileModel)
                    .where(ProfileModel.id == profile_id)
                    .values(**values)
                )
                await session.commit()

    async def record_session(self, profile_id: str) -> None:
        """Increment session counter and update last_used_at timestamp."""
        now = _utcnow().isoformat()
        async with self._session_factory() as session:
            await session.execute(
                update(ProfileModel)
                .where(ProfileModel.id == profile_id)
                .values(
                    total_sessions=ProfileModel.total_sessions + 1,
                    last_used_at=now,
                )
            )
            await session.commit()

    async def record_drift_events(self, profile_id: str, events: List[DriftEvent]) -> None:
        """Insert drift events into the audit log."""
        async with self._session_factory() as session:
            for event in events:
                model = DriftEventModel(
                    id=event.id,
                    profile_id=profile_id,
                    timestamp=event.timestamp,
                    drift_type=event.drift_type,
                    old_value=event.old_value,
                    new_value=event.new_value,
                )
                session.add(model)
            await session.commit()

    async def get_drift_history(self, profile_id: str, limit: int = 50) -> List[DriftEvent]:
        """Get drift event history for a profile."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(DriftEventModel)
                .where(DriftEventModel.profile_id == profile_id)
                .order_by(DriftEventModel.timestamp.desc())
                .limit(limit)
            )
            models = result.scalars().all()

        return [
            DriftEvent(
                id=m.id,
                profile_id=m.profile_id,
                timestamp=m.timestamp,
                drift_type=m.drift_type,
                old_value=m.old_value or "",
                new_value=m.new_value or "",
            )
            for m in models
        ]

    async def delete(self, profile_id: str) -> None:
        """
        Delete a profile and its associated browser data.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        profile = await self.get(profile_id)

        async with self._session_factory() as session:
            await session.execute(
                delete(ProfileModel).where(ProfileModel.id == profile_id)
            )
            await session.commit()

        # Delete browser data directory
        data_dir = Path(profile.user_data_dir)
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)

    async def count(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
    ) -> int:
        """Get the total number of profiles, optionally filtered."""
        stmt = select(func.count()).select_from(ProfileModel)

        if tag:
            stmt = stmt.where(ProfileModel.tags.contains(f'"{tag}"'))
        if target_os:
            stmt = stmt.where(ProfileModel.target_os == target_os)

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return result.scalar() or 0

    # ── Internal helpers for other modules ──────────────────────────

    def _ensure_db(self):
        """
        Backward compatibility shim.

        Returns the session factory so ProxyStore and other modules
        that need raw DB access can use it. This is a transitional
        API — will be replaced when ProxyStore migrates to SQLAlchemy.
        """
        return self._session_factory
