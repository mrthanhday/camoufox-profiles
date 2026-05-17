"""SQLite-backed profile storage with WAL mode for concurrent reads."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite
import orjson

from .exceptions import ProfileNameExistsError, ProfileNotFoundError
from .models import (
    DriftEvent,
    DriftSchedule,
    Profile,
    ProxyConfig,
    _new_id,
    _utcnow,
)

# SQL schema (V2)
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    target_os TEXT NOT NULL,
    fingerprint_config TEXT NOT NULL,
    proxy_server TEXT,
    proxy_username TEXT,
    proxy_password TEXT,
    user_data_dir TEXT NOT NULL,
    total_sessions INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    drift_schedule TEXT DEFAULT '{}',
    firefox_base_version INTEGER,
    proxy_id TEXT,
    warmup_completed INTEGER DEFAULT 0,
    creation_ip TEXT,
    creation_region TEXT,
    last_known_ip TEXT,
    last_known_region TEXT
);

CREATE TABLE IF NOT EXISTS drift_events (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    drift_type TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proxy_pool (
    id TEXT PRIMARY KEY,
    server TEXT NOT NULL,
    username TEXT,
    password TEXT,
    tags TEXT DEFAULT '[]',
    is_alive INTEGER DEFAULT 1,
    last_checked_at TEXT,
    last_ip TEXT,
    last_latency_ms INTEGER,
    consecutive_failures INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    notes TEXT DEFAULT '',
    auto_rotate_enabled INTEGER DEFAULT 0,
    rotate_pool_tag TEXT
);

CREATE TABLE IF NOT EXISTS tags_meta (
    name TEXT PRIMARY KEY,
    color TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name);
CREATE INDEX IF NOT EXISTS idx_profiles_created ON profiles(created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_target_os ON profiles(target_os);
CREATE INDEX IF NOT EXISTS idx_drift_profile ON drift_events(profile_id);
CREATE INDEX IF NOT EXISTS idx_drift_timestamp ON drift_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_proxy_alive ON proxy_pool(is_alive);
"""

_INSERT_PROFILE = """
INSERT INTO profiles (
    id, name, created_at, last_used_at, target_os,
    fingerprint_config, proxy_server, proxy_username, proxy_password,
    user_data_dir, total_sessions, tags, notes,
    drift_schedule, firefox_base_version, proxy_id, warmup_completed,
    creation_ip, creation_region, last_known_ip, last_known_region
) VALUES (
    :id, :name, :created_at, :last_used_at, :target_os,
    :fingerprint_config, :proxy_server, :proxy_username, :proxy_password,
    :user_data_dir, :total_sessions, :tags, :notes,
    :drift_schedule, :firefox_base_version, :proxy_id, :warmup_completed,
    :creation_ip, :creation_region, :last_known_ip, :last_known_region
);
"""

_SELECT_BY_ID = "SELECT * FROM profiles WHERE id = ?;"
_SELECT_BY_NAME = "SELECT * FROM profiles WHERE name = ?;"
_DELETE_BY_ID = "DELETE FROM profiles WHERE id = ?;"
_COUNT = "SELECT COUNT(*) FROM profiles;"


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> Dict[str, Any]:
    """Convert a row tuple to a dict using column names."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _build_list_query(
    tag: Optional[str] = None,
    target_os: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[str, list]:
    """Build a dynamic SELECT query with optional filters."""
    conditions = []
    params: list = []

    if tag:
        conditions.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    if target_os:
        conditions.append("target_os = ?")
        params.append(target_os)

    if search:
        conditions.append("(name LIKE ? OR notes LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    return where, params


class ProfileStore:
    """
    Async SQLite-backed profile storage.

    Uses WAL mode for concurrent read access during multi-profile launches.
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)
        self.db_path = self.base_dir / "profiles.db"
        self.browser_data_dir = self.base_dir / "browser_data"
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Create database, tables, and directories. Run migrations on existing DB."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row  # type: ignore[assignment]

        # Enable WAL mode for concurrent reads
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA busy_timeout=5000;")
        await self._db.execute("PRAGMA foreign_keys=ON;")

        # Run migrations for existing databases
        from .migrations import run_migrations, get_current_version
        current_version = await get_current_version(self._db)

        if current_version == 0:
            # Fresh database — create all tables
            await self._db.executescript(_CREATE_TABLE + _CREATE_INDEXES)
            # Record as v2 schema
            await self._db.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (2, "Initial V2 schema", _utcnow().isoformat()),
            )
            await self._db.commit()
        else:
            # Existing database — run pending migrations
            applied = await run_migrations(self._db)
            if applied:
                import logging
                logging.getLogger(__name__).info("Applied migrations: %s", applied)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    def _ensure_db(self) -> aiosqlite.Connection:
        """Ensure database connection is open."""
        if self._db is None:
            raise RuntimeError("ProfileStore not initialized. Call initialize() first.")
        return self._db

    def _profile_data_dir(self, profile_id: str) -> str:
        """Get the browser data directory path for a profile."""
        return str(self.browser_data_dir / profile_id)

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
        profile_id: Optional[str] = None,
    ) -> Profile:
        """
        Create a new profile with the given fingerprint config.

        Args:
            name: Human-readable profile name (must be unique).
            target_os: Target OS ('windows', 'macos', 'linux').
            fingerprint_config: Complete Camoufox config dict.
            proxy: Optional inline proxy config (V1 compat).
            tags: Optional list of tags.
            notes: Optional notes.
            proxy_id: Optional reference to a proxy pool entry.
            creation_ip: IP address at creation time.
            creation_region: Region code at creation time.
            profile_id: Optional explicit UUID (used when mirroring a cloud
                profile so local + cloud share the same id). Defaults to a
                freshly generated UUID4.

        Returns:
            The created Profile object.

        Raises:
            ProfileNameExistsError: If a profile with this name already exists.
        """
        db = self._ensure_db()

        # Check for name uniqueness
        async with db.execute(_SELECT_BY_NAME, (name,)) as cursor:
            if await cursor.fetchone():
                raise ProfileNameExistsError(name)

        profile_id = profile_id or _new_id()
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

        await db.execute(_INSERT_PROFILE, profile.to_row())
        await db.commit()

        return profile

    async def get(self, profile_id: str) -> Profile:
        """
        Load a profile by ID.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        db = self._ensure_db()
        async with db.execute(_SELECT_BY_ID, (profile_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            raise ProfileNotFoundError(profile_id)

        return Profile.from_row(dict(row))

    async def get_by_name(self, name: str) -> Profile:
        """
        Load a profile by name.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        db = self._ensure_db()
        async with db.execute(_SELECT_BY_NAME, (name,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            raise ProfileNotFoundError(name)

        return Profile.from_row(dict(row))

    async def list(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Profile]:
        """
        List profiles with optional filters and pagination.

        Args:
            tag: Filter by tag.
            target_os: Filter by target OS.
            search: Search in name and notes.
            limit: Max results per page.
            offset: Pagination offset.
        """
        db = self._ensure_db()
        where, params = _build_list_query(tag=tag, target_os=target_os, search=search)

        query = f"SELECT * FROM profiles{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        return [Profile.from_row(dict(row)) for row in rows]

    async def update(
        self,
        profile_id: str,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        last_used_at: Optional[str] = None,
        total_sessions: Optional[int] = None,
        proxy_server: Optional[str] = None,
        proxy_username: Optional[str] = None,
        proxy_password: Optional[str] = None,
    ) -> Profile:
        """
        Update mutable fields of a profile.

        Note: fingerprint_config and target_os are immutable after creation
        to preserve identity consistency. Proxy can be re-bound.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
            ProfileNameExistsError: If new name conflicts with existing profile.
        """
        db = self._ensure_db()

        # Verify profile exists
        await self.get(profile_id)

        updates = []
        params: list = []

        if name is not None:
            async with db.execute(
                "SELECT id FROM profiles WHERE name = ? AND id != ?",
                (name, profile_id),
            ) as cursor:
                if await cursor.fetchone():
                    raise ProfileNameExistsError(name)
            updates.append("name = ?")
            params.append(name)

        if tags is not None:
            updates.append("tags = ?")
            params.append(orjson.dumps(tags).decode("utf-8"))

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if last_used_at is not None:
            updates.append("last_used_at = ?")
            params.append(last_used_at)

        if total_sessions is not None:
            updates.append("total_sessions = ?")
            params.append(total_sessions)

        if proxy_server is not None:
            # Empty string clears the proxy
            updates.append("proxy_server = ?")
            params.append(proxy_server or None)
            updates.append("proxy_username = ?")
            params.append(proxy_username or None)
            updates.append("proxy_password = ?")
            params.append(proxy_password or None)

        if updates:
            query = f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?"
            params.append(profile_id)
            await db.execute(query, params)
            await db.commit()

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
        db = self._ensure_db()
        updates = []
        params: list = []

        if drift_schedule is not None:
            updates.append("drift_schedule = ?")
            params.append(orjson.dumps(drift_schedule.to_dict()).decode("utf-8"))

        if fingerprint_config is not None:
            updates.append("fingerprint_config = ?")
            params.append(orjson.dumps(fingerprint_config).decode("utf-8"))

        if proxy_id is not None:
            updates.append("proxy_id = ?")
            params.append(proxy_id)

        if warmup_completed is not None:
            updates.append("warmup_completed = ?")
            params.append(1 if warmup_completed else 0)

        if creation_ip is not None:
            updates.append("creation_ip = ?")
            params.append(creation_ip)

        if creation_region is not None:
            updates.append("creation_region = ?")
            params.append(creation_region)

        if last_known_ip is not None:
            updates.append("last_known_ip = ?")
            params.append(last_known_ip)

        if last_known_region is not None:
            updates.append("last_known_region = ?")
            params.append(last_known_region)

        if updates:
            query = f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?"
            params.append(profile_id)
            await db.execute(query, params)
            await db.commit()

    async def record_session(self, profile_id: str) -> None:
        """Increment session counter and update last_used_at timestamp."""
        db = self._ensure_db()
        now = _utcnow().isoformat()
        await db.execute(
            "UPDATE profiles SET total_sessions = total_sessions + 1, last_used_at = ? WHERE id = ?",
            (now, profile_id),
        )
        await db.commit()

    async def record_drift_events(self, profile_id: str, events: List[DriftEvent]) -> None:
        """Insert drift events into the audit log."""
        db = self._ensure_db()
        for event in events:
            await db.execute(
                "INSERT INTO drift_events (id, profile_id, timestamp, drift_type, old_value, new_value) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.id, profile_id, event.timestamp, event.drift_type, event.old_value, event.new_value),
            )
        await db.commit()

    async def get_drift_history(self, profile_id: str, limit: int = 50) -> List[DriftEvent]:
        """Get drift event history for a profile."""
        db = self._ensure_db()
        async with db.execute(
            "SELECT * FROM drift_events WHERE profile_id = ? ORDER BY timestamp DESC LIMIT ?",
            (profile_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            DriftEvent(
                id=dict(r)["id"],
                profile_id=dict(r)["profile_id"],
                timestamp=dict(r)["timestamp"],
                drift_type=dict(r)["drift_type"],
                old_value=dict(r).get("old_value", ""),
                new_value=dict(r).get("new_value", ""),
            )
            for r in rows
        ]

    async def delete(self, profile_id: str) -> None:
        """
        Delete a profile and its associated browser data.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        db = self._ensure_db()

        # Get profile to find its data dir
        profile = await self.get(profile_id)

        # Delete from database (CASCADE deletes drift_events)
        await db.execute(_DELETE_BY_ID, (profile_id,))
        await db.commit()

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
        db = self._ensure_db()

        if tag or target_os:
            where, params = _build_list_query(tag=tag, target_os=target_os)
            query = f"SELECT COUNT(*) FROM profiles{where}"
        else:
            query = _COUNT
            params = []

        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()

        return row[0] if row else 0


class ProfileStoreSync:
    """
    Synchronous SQLite-backed profile storage.

    For use in sync contexts where async is not needed.
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)
        self.db_path = self.base_dir / "profiles.db"
        self.browser_data_dir = self.base_dir / "browser_data"
        self._db: Optional[sqlite3.Connection] = None

    def initialize(self) -> None:
        """Create database, tables, and directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)

        self._db = sqlite3.connect(str(self.db_path))
        self._db.row_factory = _row_factory  # type: ignore[assignment]

        self._db.execute("PRAGMA journal_mode=WAL;")
        self._db.execute("PRAGMA busy_timeout=5000;")
        self._db.execute("PRAGMA foreign_keys=ON;")

        # Run migrations for existing databases
        from .migrations import run_migrations_sync
        # Check if fresh or existing
        cursor = self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='profiles'"
        )
        is_existing = cursor.fetchone() is not None

        if not is_existing:
            self._db.executescript(_CREATE_TABLE + _CREATE_INDEXES)
            self._db.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                (2, "Initial V2 schema", _utcnow().isoformat()),
            )
            self._db.commit()
        else:
            run_migrations_sync(self._db)

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    def _ensure_db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("ProfileStoreSync not initialized. Call initialize() first.")
        return self._db

    def _profile_data_dir(self, profile_id: str) -> str:
        return str(self.browser_data_dir / profile_id)

    def create(
        self,
        name: str,
        target_os: str,
        fingerprint_config: Dict[str, Any],
        proxy: Optional[ProxyConfig] = None,
        tags: Optional[List[str]] = None,
        notes: str = "",
    ) -> Profile:
        """Create a new profile. See ProfileStore.create for details."""
        db = self._ensure_db()

        cursor = db.execute(_SELECT_BY_NAME, (name,))
        if cursor.fetchone():
            raise ProfileNameExistsError(name)

        profile_id = _new_id()
        user_data_dir = self._profile_data_dir(profile_id)
        os.makedirs(user_data_dir, exist_ok=True)

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
        )

        db.execute(_INSERT_PROFILE, profile.to_row())
        db.commit()
        return profile

    def get(self, profile_id: str) -> Profile:
        """Load a profile by ID."""
        db = self._ensure_db()
        cursor = db.execute(_SELECT_BY_ID, (profile_id,))
        row = cursor.fetchone()
        if not row:
            raise ProfileNotFoundError(profile_id)
        return Profile.from_row(row)

    def get_by_name(self, name: str) -> Profile:
        """Load a profile by name."""
        db = self._ensure_db()
        cursor = db.execute(_SELECT_BY_NAME, (name,))
        row = cursor.fetchone()
        if not row:
            raise ProfileNotFoundError(name)
        return Profile.from_row(row)

    def list(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Profile]:
        """List profiles with optional filters."""
        db = self._ensure_db()
        where, params = _build_list_query(tag=tag, target_os=target_os, search=search)
        query = f"SELECT * FROM profiles{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = db.execute(query, params)
        return [Profile.from_row(row) for row in cursor.fetchall()]

    def update(
        self,
        profile_id: str,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
        last_used_at: Optional[str] = None,
        total_sessions: Optional[int] = None,
    ) -> Profile:
        """Update mutable fields of a profile."""
        db = self._ensure_db()
        self.get(profile_id)

        updates = []
        params: list = []

        if name is not None:
            cursor = db.execute(
                "SELECT id FROM profiles WHERE name = ? AND id != ?",
                (name, profile_id),
            )
            if cursor.fetchone():
                raise ProfileNameExistsError(name)
            updates.append("name = ?")
            params.append(name)

        if tags is not None:
            updates.append("tags = ?")
            params.append(orjson.dumps(tags).decode("utf-8"))

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if last_used_at is not None:
            updates.append("last_used_at = ?")
            params.append(last_used_at)

        if total_sessions is not None:
            updates.append("total_sessions = ?")
            params.append(total_sessions)

        if updates:
            query = f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?"
            params.append(profile_id)
            db.execute(query, params)
            db.commit()

        return self.get(profile_id)

    def record_session(self, profile_id: str) -> None:
        """Increment session counter and update last_used_at."""
        db = self._ensure_db()
        now = _utcnow().isoformat()
        db.execute(
            "UPDATE profiles SET total_sessions = total_sessions + 1, last_used_at = ? WHERE id = ?",
            (now, profile_id),
        )
        db.commit()

    def delete(self, profile_id: str) -> None:
        """Delete a profile and its browser data."""
        db = self._ensure_db()
        profile = self.get(profile_id)
        db.execute(_DELETE_BY_ID, (profile_id,))
        db.commit()

        data_dir = Path(profile.user_data_dir)
        if data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)

    def count(
        self,
        tag: Optional[str] = None,
        target_os: Optional[str] = None,
    ) -> int:
        """Get total number of profiles."""
        db = self._ensure_db()
        if tag or target_os:
            where, params = _build_list_query(tag=tag, target_os=target_os)
            query = f"SELECT COUNT(*) FROM profiles{where}"
        else:
            query = _COUNT
            params = []
        cursor = db.execute(query, params)
        row = cursor.fetchone()
        if isinstance(row, dict):
            return list(row.values())[0]
        return row[0] if row else 0
