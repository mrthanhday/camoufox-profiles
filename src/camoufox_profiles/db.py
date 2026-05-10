"""
Shared database engine factory for camoufox-profiles.

Supports both SQLite (cfox-local) and PostgreSQL (cfox-server) via
the same SQLAlchemy 2.0 async engine. The connection URL determines
which dialect is used.

Usage:
    # SQLite (cfox-local)
    engine = create_engine("sqlite+aiosqlite:///path/to/profiles.db")

    # PostgreSQL (cfox-server)
    engine = create_engine("postgresql+asyncpg://user:pass@host:5432/cfox")
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models_sa import Base

logger = logging.getLogger(__name__)


def create_engine(url: str, **kwargs) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.

    Args:
        url: Database URL. Supported schemes:
            - sqlite+aiosqlite:///path/to/db.sqlite
            - postgresql+asyncpg://user:pass@host:5432/dbname
        **kwargs: Additional engine options (echo, pool_size, etc.)
    """
    defaults = {"echo": False}

    # SQLite-specific settings
    if url.startswith("sqlite"):
        # aiosqlite doesn't support pool_size
        defaults["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL connection pool
        defaults.setdefault("pool_size", 5)
        defaults.setdefault("max_overflow", 10)

    defaults.update(kwargs)
    return create_async_engine(url, **defaults)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """
    Auto-create all tables on startup.

    Uses metadata.create_all which is idempotent — safe to call repeatedly.
    For SQLite, also enables WAL mode and foreign keys.
    """
    async with engine.begin() as conn:
        # SQLite pragmas
        if "sqlite" in str(engine.url):
            await conn.execute(
                __import__("sqlalchemy").text("PRAGMA journal_mode=WAL")
            )
            await conn.execute(
                __import__("sqlalchemy").text("PRAGMA busy_timeout=5000")
            )
            await conn.execute(
                __import__("sqlalchemy").text("PRAGMA foreign_keys=ON")
            )

        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized: %s", _safe_url(engine.url))


def _safe_url(url) -> str:
    """Mask password in URL for logging."""
    s = str(url)
    if "@" in s:
        # Mask everything between :// and @
        scheme_end = s.index("://") + 3
        at_pos = s.index("@")
        return s[:scheme_end] + "***@" + s[at_pos + 1:]
    return s
