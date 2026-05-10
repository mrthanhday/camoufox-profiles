"""
Heartbeat service for cloud lock renewal.

Sends periodic heartbeats to cfox-server to keep profile locks alive.
If heartbeats fail, implements graduated response:
  - 60s: Warning log
  - 150s: Critical log + notify UI
  - 300s: Force-close browser context (split-brain protection)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Graduated response thresholds (seconds since last successful heartbeat)
WARN_THRESHOLD = 60
CRITICAL_THRESHOLD = 150
FORCE_CLOSE_THRESHOLD = 300

HEARTBEAT_INTERVAL = 30  # seconds


class HeartbeatEntry:
    """Tracks heartbeat state for a single profile."""

    def __init__(
        self,
        profile_id: str,
        lock_token: str,
        machine_id: str,
    ):
        self.profile_id = profile_id
        self.lock_token = lock_token
        self.machine_id = machine_id
        self.last_success: float = time.monotonic()
        self.consecutive_failures: int = 0
        self.state: str = "healthy"  # healthy, warn, critical, dead


class HeartbeatService:
    """
    Background service that sends heartbeats for all active cloud sessions.

    Register a profile when launching, unregister when stopping.
    """

    def __init__(
        self,
        heartbeat_fn: Callable,
        on_lock_lost: Optional[Callable] = None,
        on_state_change: Optional[Callable] = None,
    ):
        """
        Args:
            heartbeat_fn: async fn(profile_id, lock_token, machine_id) -> dict
            on_lock_lost: async fn(profile_id) — called when force-close threshold hit
            on_state_change: async fn(profile_id, old_state, new_state) — state transitions
        """
        self._heartbeat_fn = heartbeat_fn
        self._on_lock_lost = on_lock_lost
        self._on_state_change = on_state_change
        self._entries: Dict[str, HeartbeatEntry] = {}
        self._task: Optional[asyncio.Task] = None

    def register(self, profile_id: str, lock_token: str, machine_id: str) -> None:
        """Start heartbeating for a profile."""
        self._entries[profile_id] = HeartbeatEntry(
            profile_id=profile_id,
            lock_token=lock_token,
            machine_id=machine_id,
        )
        logger.info("Heartbeat registered: %s", profile_id[:8])

    def unregister(self, profile_id: str) -> None:
        """Stop heartbeating for a profile."""
        self._entries.pop(profile_id, None)
        logger.info("Heartbeat unregistered: %s", profile_id[:8])

    def start(self) -> None:
        """Start the background heartbeat loop."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            logger.info("Heartbeat service started")

    def stop(self) -> None:
        """Stop the background heartbeat loop."""
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        """Periodic heartbeat loop."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat loop error: %s", e)

    async def _tick(self) -> None:
        """Send heartbeats for all registered profiles."""
        tasks = []
        for entry in list(self._entries.values()):
            tasks.append(self._send_heartbeat(entry))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_heartbeat(self, entry: HeartbeatEntry) -> None:
        """Send a single heartbeat and handle graduated response."""
        try:
            await self._heartbeat_fn(
                entry.profile_id, entry.lock_token, entry.machine_id,
            )
            entry.last_success = time.monotonic()
            entry.consecutive_failures = 0

            if entry.state != "healthy":
                old = entry.state
                entry.state = "healthy"
                logger.info("Heartbeat recovered: %s", entry.profile_id[:8])
                if self._on_state_change:
                    await self._on_state_change(entry.profile_id, old, "healthy")

        except Exception as e:
            entry.consecutive_failures += 1
            elapsed = time.monotonic() - entry.last_success
            old_state = entry.state

            if elapsed >= FORCE_CLOSE_THRESHOLD:
                entry.state = "dead"
                if old_state != "dead":
                    logger.critical(
                        "LOCK LOST — force closing browser: profile=%s elapsed=%.0fs",
                        entry.profile_id[:8], elapsed,
                    )
                    if self._on_state_change:
                        await self._on_state_change(entry.profile_id, old_state, "dead")
                    if self._on_lock_lost:
                        await self._on_lock_lost(entry.profile_id)
                    self.unregister(entry.profile_id)

            elif elapsed >= CRITICAL_THRESHOLD:
                entry.state = "critical"
                if old_state != "critical":
                    logger.error(
                        "Heartbeat CRITICAL: profile=%s elapsed=%.0fs failures=%d error=%s",
                        entry.profile_id[:8], elapsed, entry.consecutive_failures, e,
                    )
                    if self._on_state_change:
                        await self._on_state_change(entry.profile_id, old_state, "critical")

            elif elapsed >= WARN_THRESHOLD:
                entry.state = "warn"
                if old_state != "warn":
                    logger.warning(
                        "Heartbeat warning: profile=%s elapsed=%.0fs failures=%d",
                        entry.profile_id[:8], elapsed, entry.consecutive_failures,
                    )
                    if self._on_state_change:
                        await self._on_state_change(entry.profile_id, old_state, "warn")

    @property
    def active_count(self) -> int:
        return len(self._entries)

    def get_status(self) -> Dict[str, str]:
        """Get heartbeat state for all registered profiles."""
        return {pid: e.state for pid, e in self._entries.items()}
