"""Lock TTL expiry background service for cfox-server."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from camoufox_profiles.models import _utcnow
from camoufox_profiles.models_sa import ProfileModel

logger = logging.getLogger(__name__)


class LockCleanupService:
    """
    Background task that expires stale locks.

    Runs periodically and clears locks where lock_expires_at < now.
    """

    def __init__(self, session_factory: async_sessionmaker, settings):
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background cleanup loop."""
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Lock cleanup service started (interval=%ds)",
            self._settings.lock_cleanup_interval_seconds,
        )

    def stop(self) -> None:
        """Stop the background cleanup loop."""
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        """Periodic cleanup loop."""
        while True:
            try:
                await asyncio.sleep(self._settings.lock_cleanup_interval_seconds)
                expired = await self._cleanup_expired()
                if expired:
                    logger.info("Cleaned up %d expired lock(s)", expired)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Lock cleanup error: %s", e)

    async def _cleanup_expired(self) -> int:
        """Find and clear expired locks. Returns count of locks cleared."""
        now = _utcnow().isoformat()

        async with self._session_factory() as session:
            # Find profiles with expired locks
            result = await session.execute(
                select(ProfileModel).where(
                    ProfileModel.locked_by.is_not(None),
                    ProfileModel.lock_expires_at < now,
                )
            )
            expired_profiles = result.scalars().all()

            if not expired_profiles:
                return 0

            for profile in expired_profiles:
                logger.warning(
                    "Lock expired: profile=%s, locked_by=%s, expired_at=%s",
                    profile.id[:8], profile.locked_by, profile.lock_expires_at,
                )

            # Clear all expired locks
            expired_ids = [p.id for p in expired_profiles]
            await session.execute(
                update(ProfileModel)
                .where(ProfileModel.id.in_(expired_ids))
                .values(
                    locked_by=None,
                    lock_token=None,
                    locked_at=None,
                    lock_expires_at=None,
                    last_heartbeat_at=None,
                )
            )
            await session.commit()

        return len(expired_profiles)
