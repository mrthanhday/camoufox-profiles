"""Database schema migrations for camoufox-profiles."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Union

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """A single schema migration."""

    version: int
    description: str
    up_sql: str


# All migrations in order
MIGRATIONS: List[Migration] = [
    Migration(
        version=2,
        description="Add drift, proxy pool, IP tracking, health",
        up_sql="""
            -- Schema version tracking (must come first)
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );

            -- Drift schedule per profile
            ALTER TABLE profiles ADD COLUMN drift_schedule TEXT DEFAULT '{}';
            ALTER TABLE profiles ADD COLUMN firefox_base_version INTEGER;

            -- Proxy pool reference
            ALTER TABLE profiles ADD COLUMN proxy_id TEXT;

            -- Warmup tracking
            ALTER TABLE profiles ADD COLUMN warmup_completed INTEGER DEFAULT 0;

            -- IP tracking for null-proxy consistency guard
            ALTER TABLE profiles ADD COLUMN creation_ip TEXT;
            ALTER TABLE profiles ADD COLUMN creation_region TEXT;
            ALTER TABLE profiles ADD COLUMN last_known_ip TEXT;
            ALTER TABLE profiles ADD COLUMN last_known_region TEXT;
        """,
    ),
]

# Table creation SQL that must be run via executescript (handles complex statements)
_V2_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS drift_events (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    drift_type TEXT NOT NULL,
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_drift_profile ON drift_events(profile_id);
CREATE INDEX IF NOT EXISTS idx_drift_timestamp ON drift_events(timestamp);

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
CREATE INDEX IF NOT EXISTS idx_proxy_alive ON proxy_pool(is_alive);
"""


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    """Check if a table exists in the database."""
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ) as cursor:
        return await cursor.fetchone() is not None


async def _column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        rows = await cursor.fetchall()
        columns = [row[1] for row in rows]
        return column in columns


async def get_current_version(db: aiosqlite.Connection) -> int:
    """Get the current schema version from the database."""
    if not await _table_exists(db, "schema_migrations"):
        # Check if this is a V1 database (has profiles table but no migrations)
        if await _table_exists(db, "profiles"):
            return 1  # V1 schema
        return 0  # Fresh database

    async with db.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ) as cursor:
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 1


async def run_migrations(db: aiosqlite.Connection) -> List[int]:
    """
    Apply pending migrations.

    Returns list of migration versions that were applied.
    """
    current = await get_current_version(db)
    applied: List[int] = []

    # Ensure schema_migrations table exists (needed to record migrations)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    await db.commit()

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue

        logger.info(
            "Applying migration v%d: %s", migration.version, migration.description
        )

        # Strip SQL comments before splitting by semicolons
        # This prevents comments between multi-line statements from corrupting the split
        sql_lines = []
        for line in migration.up_sql.splitlines():
            stripped = line.strip()
            if stripped.startswith("--"):
                continue
            sql_lines.append(line)
        clean_sql = "\n".join(sql_lines)

        # Execute each statement individually to handle ALTER TABLE gracefully
        for statement in clean_sql.split(";"):
            statement = statement.strip()
            if not statement:
                continue

            # Skip ALTER TABLE if column already exists
            if "ALTER TABLE" in statement and "ADD COLUMN" in statement:
                # Extract table and column name
                parts = statement.split("ADD COLUMN")
                table_part = parts[0].split("ALTER TABLE")[1].strip()
                col_name = parts[1].strip().split()[0]
                if await _column_exists(db, table_part, col_name):
                    logger.debug("Column %s.%s already exists, skipping", table_part, col_name)
                    continue

            try:
                await db.execute(statement)
            except Exception as e:
                logger.warning("Migration statement failed (may be idempotent): %s — %s", statement[:80], e)

        # Create tables via executescript (handles complex CREATE TABLE with commas)
        if migration.version == 2:
            await db.executescript(_V2_TABLES_SQL)

        # Record migration
        from .models import _utcnow
        await db.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.description, _utcnow().isoformat()),
        )
        await db.commit()
        applied.append(migration.version)
        logger.info("Migration v%d applied successfully", migration.version)

    return applied


# Sync version for ProfileStoreSync
def run_migrations_sync(db: "sqlite3.Connection") -> List[int]:
    """Apply pending migrations synchronously."""
    import sqlite3

    def table_exists(table: str) -> bool:
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        return cursor.fetchone() is not None

    def column_exists(table: str, column: str) -> bool:
        cursor = db.execute(f"PRAGMA table_info({table})")
        columns = [row[1] if isinstance(row, tuple) else row.get("name", row[1]) for row in cursor.fetchall()]
        return column in columns

    # Get current version
    if not table_exists("schema_migrations"):
        current = 1 if table_exists("profiles") else 0
    else:
        cursor = db.execute("SELECT MAX(version) FROM schema_migrations")
        row = cursor.fetchone()
        if isinstance(row, dict):
            current = list(row.values())[0] or 1
        else:
            current = row[0] if row and row[0] else 1

    applied: List[int] = []

    # Ensure schema_migrations table exists
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    db.commit()

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue

        logger.info("Applying migration v%d: %s", migration.version, migration.description)

        # Strip SQL comments before splitting
        sql_lines = []
        for line in migration.up_sql.splitlines():
            stripped = line.strip()
            if stripped.startswith("--"):
                continue
            sql_lines.append(line)
        clean_sql = "\n".join(sql_lines)

        for statement in clean_sql.split(";"):
            statement = statement.strip()
            if not statement:
                continue

            if "ALTER TABLE" in statement and "ADD COLUMN" in statement:
                parts = statement.split("ADD COLUMN")
                table_part = parts[0].split("ALTER TABLE")[1].strip()
                col_name = parts[1].strip().split()[0]
                if column_exists(table_part, col_name):
                    continue

            try:
                db.execute(statement)
            except Exception as e:
                logger.warning("Migration statement failed: %s — %s", statement[:80], e)

        # Create tables via executescript
        if migration.version == 2:
            db.executescript(_V2_TABLES_SQL)

        from .models import _utcnow
        db.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.description, _utcnow().isoformat()),
        )
        db.commit()
        applied.append(migration.version)

    return applied
