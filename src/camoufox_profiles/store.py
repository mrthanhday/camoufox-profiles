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
from .models import Profile, ProxyConfig, _new_id, _utcnow

# SQL schema
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
    notes TEXT DEFAULT ''
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name);
CREATE INDEX IF NOT EXISTS idx_profiles_created ON profiles(created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_target_os ON profiles(target_os);
"""

_INSERT_PROFILE = """
INSERT INTO profiles (
    id, name, created_at, last_used_at, target_os,
    fingerprint_config, proxy_server, proxy_username, proxy_password,
    user_data_dir, total_sessions, tags, notes
) VALUES (
    :id, :name, :created_at, :last_used_at, :target_os,
    :fingerprint_config, :proxy_server, :proxy_username, :proxy_password,
    :user_data_dir, :total_sessions, :tags, :notes
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
        # SQLite JSON: check if tag exists in the JSON array
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
        """Create database, tables, and directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.browser_data_dir.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row  # type: ignore[assignment]

        # Enable WAL mode for concurrent reads
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA busy_timeout=5000;")

        await self._db.executescript(_CREATE_TABLE + _CREATE_INDEXES)
        await self._db.commit()

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
    ) -> Profile:
        """
        Create a new profile with the given fingerprint config.

        Args:
            name: Human-readable profile name (must be unique).
            target_os: Target OS ('windows', 'macos', 'linux').
            fingerprint_config: Complete Camoufox config dict.
            proxy: Optional fixed proxy binding.
            tags: Optional list of tags.
            notes: Optional notes.

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

        profile_id = _new_id()
        user_data_dir = self._profile_data_dir(profile_id)

        # Create browser data directory
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
    ) -> Profile:
        """
        Update mutable fields of a profile.

        Note: fingerprint_config, target_os, and proxy are immutable
        after creation to preserve identity consistency.

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
            # Check name uniqueness
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

        if updates:
            query = f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?"
            params.append(profile_id)
            await db.execute(query, params)
            await db.commit()

        return await self.get(profile_id)

    async def record_session(self, profile_id: str) -> None:
        """Increment session counter and update last_used_at timestamp."""
        db = self._ensure_db()
        now = _utcnow().isoformat()
        await db.execute(
            "UPDATE profiles SET total_sessions = total_sessions + 1, last_used_at = ? WHERE id = ?",
            (now, profile_id),
        )
        await db.commit()

    async def delete(self, profile_id: str) -> None:
        """
        Delete a profile and its associated browser data.

        Raises:
            ProfileNotFoundError: If profile doesn't exist.
        """
        db = self._ensure_db()

        # Get profile to find its data dir
        profile = await self.get(profile_id)

        # Delete from database
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
        self._db.executescript(_CREATE_TABLE + _CREATE_INDEXES)
        self._db.commit()

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
        self.get(profile_id)  # Verify exists

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
        # _row_factory returns dict, so we need to handle both formats
        if isinstance(row, dict):
            return list(row.values())[0]
        return row[0] if row else 0
