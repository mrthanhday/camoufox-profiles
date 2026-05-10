"""
BrowserSessionManager — tracks running Camoufox browser sessions.

Singleton that manages the lifecycle of browser instances:
- Launch/stop with V2 ProfileManager integration
- Crash detection via Playwright disconnect events
- Session persistence to SQLite for crash recovery
- Phase 3: heartbeat, cloud lock, essential data sync
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import psutil

from .routes.ws import Event, EventBus, EventType

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BrowserSession:
    """A running browser session."""

    profile_id: str
    source: str  # "local" or "cloud"
    profile_name: str
    started_at: datetime = field(default_factory=_utcnow)
    browser_pid: Optional[int] = None
    base_version: Optional[int] = None  # Phase 3: downloaded essential_data version
    lock_token: Optional[str] = None  # Phase 3: cloud lock token

    # Internal — not serialized
    _context: Any = field(default=None, repr=False)
    _browser: Any = field(default=None, repr=False)
    _heartbeat_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "source": self.source,
            "profile_name": self.profile_name,
            "started_at": self.started_at.isoformat(),
            "browser_pid": self.browser_pid,
        }


class BrowserSessionManager:
    """
    Singleton managing all running browser sessions.

    Wraps V2 ProfileManager.launch() and adds:
    - Session tracking (in-memory + SQLite persistence)
    - Crash detection and recovery
    - WebSocket event emission
    """

    _instance: Optional[BrowserSessionManager] = None

    def __init__(self, profile_manager: Any, db_path: Path) -> None:
        self._pm = profile_manager
        self._db_path = db_path
        self._sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._bus = EventBus.instance()
        self._watcher_tasks: Dict[str, asyncio.Task] = {}

        # Ensure running_sessions table
        self._init_db()

    @classmethod
    def instance(
        cls,
        profile_manager: Any = None,
        db_path: Path = None,
    ) -> BrowserSessionManager:
        if cls._instance is None:
            if profile_manager is None or db_path is None:
                raise RuntimeError("BSM not initialized — pass profile_manager and db_path")
            cls._instance = cls(profile_manager, db_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    # ── Database persistence ──────────────────────────────────────

    def _init_db(self) -> None:
        """Create running_sessions table for crash recovery."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS running_sessions (
                    profile_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    browser_pid INTEGER,
                    started_at TEXT NOT NULL,
                    base_version INTEGER,
                    lock_token TEXT
                )
            """)
            conn.commit()

    def _persist_session(self, session: BrowserSession) -> None:
        """Save session to SQLite for crash recovery."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO running_sessions
                (profile_id, source, profile_name, browser_pid, started_at, base_version, lock_token)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.profile_id,
                    session.source,
                    session.profile_name,
                    session.browser_pid,
                    session.started_at.isoformat(),
                    session.base_version,
                    session.lock_token,
                ),
            )
            conn.commit()

    def _remove_persisted(self, profile_id: str) -> None:
        """Remove session from SQLite."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("DELETE FROM running_sessions WHERE profile_id = ?", (profile_id,))
            conn.commit()

    def _load_persisted_sessions(self) -> List[Dict[str, Any]]:
        """Load all persisted sessions (for crash recovery)."""
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM running_sessions").fetchall()
            return [dict(row) for row in rows]

    # ── Session lifecycle ─────────────────────────────────────────

    async def launch(
        self,
        profile_id: str,
        source: str = "local",
        headless: bool = False,
        drift: bool = True,
    ) -> BrowserSession:
        """
        Launch a browser for a profile.

        For local profiles (Phase 1): directly uses V2 ProfileManager.
        For cloud profiles (Phase 3): lock → download → restore → launch.
        """
        async with self._lock:
            if profile_id in self._sessions:
                raise RuntimeError(f"Profile '{profile_id}' is already running")

        # Get profile info for display name
        profile = await self._pm.store.get(profile_id)
        if profile is None:
            raise ValueError(f"Profile '{profile_id}' not found")

        self._bus.emit(Event(
            type=EventType.BROWSER_STATUS,
            profile_id=profile_id,
            status="launching",
        ))

        try:
            # Use V2 launcher — get the context manager
            launch_cm = self._pm.launch(
                profile_id=profile_id,
                drift=drift,
                headless=headless,
            )

            # Enter the context manager and keep it open
            context = await launch_cm.__aenter__()

            # Get browser PID
            # For persistent contexts, browser.process is None.
            # PID lives at: context._impl_obj._browser._connection._transport._proc
            browser_pid = None
            try:
                transport = context._impl_obj._browser._connection._transport
                if hasattr(transport, "_proc") and transport._proc:
                    browser_pid = transport._proc.pid
            except Exception:
                pass

            if browser_pid is None:
                # Fallback: try the public API (works for non-persistent contexts)
                try:
                    if hasattr(context, "browser") and context.browser:
                        proc = context.browser.process
                        if proc:
                            browser_pid = proc.pid
                except Exception:
                    pass

            session = BrowserSession(
                profile_id=profile_id,
                source=source,
                profile_name=profile.name,
                browser_pid=browser_pid,
                _context=context,
                _browser=launch_cm,
            )

            # Fast-path: context close event (may not fire on abrupt close)
            context.on("close", lambda: asyncio.ensure_future(
                self._cleanup_session(profile_id, reason="external")
            ))

            async with self._lock:
                self._sessions[profile_id] = session

            self._persist_session(session)

            # Reliable path: background PID monitoring
            if browser_pid:
                watcher = asyncio.create_task(
                    self._watch_browser_pid(profile_id, browser_pid)
                )
                self._watcher_tasks[profile_id] = watcher

            now = datetime.now(timezone.utc).isoformat()
            self._bus.emit(Event(
                type=EventType.BROWSER_STATUS,
                profile_id=profile_id,
                status="running",
                extra={"last_used_at": now},
            ))

            logger.info(
                "Launched browser for '%s' (pid=%s)",
                profile.name,
                browser_pid,
            )
            return session

        except Exception as e:
            self._bus.emit(Event(
                type=EventType.BROWSER_STATUS,
                profile_id=profile_id,
                status="idle",
                error=str(e),
            ))
            raise

    async def launch_cloud(
        self,
        profile_id: str,
        cloud_client,
        machine_id: str,
        headless: bool = False,
        drift: bool = True,
    ) -> BrowserSession:
        """
        Cloud launch flow: lock → download → restore → launch → heartbeat.

        Args:
            profile_id: Cloud profile ID.
            cloud_client: CloudClient instance.
            machine_id: This machine's ID.
            headless: Run headless.
            drift: Enable drift engine.
        """
        from .services.sync_service import restore_essential_data
        import tempfile

        self._bus.emit(Event(
            type=EventType.BROWSER_STATUS,
            profile_id=profile_id,
            status="launching",
            extra={"step": "locking"},
        ))

        # Step 1: Acquire lock
        lock_resp = await cloud_client.lock_profile(
            profile_id, machine_id, ttl_minutes=120,
        )
        lock_token = lock_resp["lock_token"]
        server_version = lock_resp.get("essential_data_version", 0)

        # Step 2: Download essential data if available
        profile = await self._pm.store.get(profile_id)
        user_data_dir = Path(profile.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        if server_version > 0:
            self._bus.emit(Event(
                type=EventType.BROWSER_STATUS,
                profile_id=profile_id,
                status="launching",
                extra={"step": "downloading"},
            ))

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                dl_info = await cloud_client.download_essential_data(
                    profile_id, tmp_path,
                )
                restore_essential_data(
                    tmp_path, user_data_dir,
                    expected_checksum=dl_info.get("checksum"),
                )
            finally:
                tmp_path.unlink(missing_ok=True)

        # Step 3: Launch browser (same as local)
        session = await self.launch(
            profile_id=profile_id,
            source="cloud",
            headless=headless,
            drift=drift,
        )
        session.lock_token = lock_token
        session.base_version = server_version

        # Update persisted session with cloud fields
        self._persist_session(session)

        # Step 4: Register heartbeat
        heartbeat_svc = getattr(self, "_heartbeat_service", None)
        if heartbeat_svc:
            heartbeat_svc.register(profile_id, lock_token, machine_id)

        return session

    async def stop_cloud(
        self,
        profile_id: str,
        cloud_client,
        machine_id: str,
    ) -> None:
        """
        Cloud stop flow: collect → upload → unlock → unregister heartbeat.
        """
        from .services.sync_service import collect_essential_data

        session = self.get_session(profile_id)
        if not session:
            raise ValueError(f"No running session for profile '{profile_id}'")

        # Step 1: Stop browser first
        await self.stop(profile_id)

        # Step 2: Collect and upload essential data
        try:
            profile = await self._pm.store.get(profile_id)
            zip_path, checksum, size = collect_essential_data(profile.user_data_dir)

            self._bus.emit(Event(
                type=EventType.BROWSER_STATUS,
                profile_id=profile_id,
                status="idle",
                extra={"step": "uploading"},
            ))

            await cloud_client.upload_essential_data(profile_id, zip_path)
            zip_path.unlink(missing_ok=True)

        except Exception as e:
            logger.error("Failed to upload essential data for %s: %s", profile_id[:8], e)
            # Upload failed — mark sync incomplete but don't fail the stop

        # Step 3: Unlock
        try:
            if session.lock_token:
                await cloud_client.unlock_profile(
                    profile_id, session.lock_token, machine_id,
                )
        except Exception as e:
            logger.error("Failed to unlock %s: %s", profile_id[:8], e)

        # Step 4: Unregister heartbeat
        heartbeat_svc = getattr(self, "_heartbeat_service", None)
        if heartbeat_svc:
            heartbeat_svc.unregister(profile_id)

    async def on_heartbeat_death(self, profile_id: str) -> None:
        """
        Called by HeartbeatService when lock is lost (300s without heartbeat).

        Force-closes the browser context to prevent split-brain.
        Does NOT attempt upload/unlock (server already expired the lock).
        """
        logger.critical(
            "HEARTBEAT DEATH — force closing browser for profile %s",
            profile_id[:8],
        )

        session = self.get_session(profile_id)
        if not session:
            return

        # Force kill browser process
        if session.browser_pid and psutil.pid_exists(session.browser_pid):
            try:
                psutil.Process(session.browser_pid).kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Cleanup session
        await self._cleanup_session(profile_id, reason="crash")

        self._bus.emit(Event(
            type=EventType.BROWSER_STATUS,
            profile_id=profile_id,
            status="error",
            error="Lock lost — browser force-closed (heartbeat timeout)",
        ))

    async def stop(self, profile_id: str) -> None:
        """Stop a running browser session."""
        async with self._lock:
            if profile_id not in self._sessions:
                raise ValueError(f"No running session for profile '{profile_id}'")

        self._bus.emit(Event(
            type=EventType.BROWSER_STATUS,
            profile_id=profile_id,
            status="stopping",
        ))

        # Delegate all cleanup (cancel watcher, pop session, __aexit__, emit idle)
        await self._cleanup_session(profile_id, reason="stopped")

    async def _on_context_close(self, profile_id: str) -> None:
        """Handle unexpected browser close via Playwright event (fast-path)."""
        await self._cleanup_session(profile_id, reason="external")

    async def _cleanup_session(self, profile_id: str, *, reason: str = "external") -> None:
        """
        Idempotent cleanup when browser dies externally.

        Called from either:
        - context.on("close") fast-path (if Playwright fires it)
        - _watch_browser_pid() reliable path (PID monitoring)
        - Both may fire — idempotent by design.

        Args:
            reason: "external" (user closed) or "crash" (process crashed)
        """
        # Cancel watcher and wait for it to finish to prevent race
        task = self._watcher_tasks.pop(profile_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        async with self._lock:
            session = self._sessions.pop(profile_id, None)

        if session is None:
            return  # Already cleaned up (stop() or duplicate call)

        self._remove_persisted(profile_id)

        # Exit the launcher context manager to cleanup Playwright resources
        if session._browser:
            try:
                await session._browser.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(
                    "Launcher CM exit during cleanup for '%s': %s",
                    session.profile_name, e,
                )

        if reason == "crash":
            status = "error"
            error_msg = "Browser crashed unexpectedly"
        else:
            status = "idle"
            error_msg = None

        logger.info("Browser closed for '%s' (%s)", session.profile_name, reason)

        now = datetime.now(timezone.utc).isoformat()
        self._bus.emit(Event(
            type=EventType.BROWSER_STATUS,
            profile_id=profile_id,
            status=status,
            error=error_msg,
            extra={"last_used_at": now},
        ))

    async def _watch_browser_pid(self, profile_id: str, pid: int) -> None:
        """
        Background task that monitors browser PID and triggers cleanup when it dies.

        Uses psutil.pid_exists() for reliable cross-platform PID checking.
        (os.kill(pid, 0) does NOT raise on Windows when process is dead.)
        """
        poll_interval = 2  # seconds

        try:
            while True:
                await asyncio.sleep(poll_interval)

                # Check if session was already cleaned up (e.g. via stop())
                if profile_id not in self._sessions:
                    return

                # Check if PID is still alive (psutil is cross-platform safe)
                if not psutil.pid_exists(pid):
                    logger.info(
                        "Detected browser process exit (pid=%d) for profile '%s'",
                        pid, profile_id,
                    )
                    await self._cleanup_session(profile_id, reason="external")
                    return
        except asyncio.CancelledError:
            return  # stop() or shutdown() cancelled us

    # ── Queries ───────────────────────────────────────────────────

    def get_sessions(self) -> List[Dict[str, Any]]:
        """Get all running sessions as dicts."""
        return [s.to_dict() for s in self._sessions.values()]

    def is_running(self, profile_id: str) -> bool:
        """Check if a profile has a running browser."""
        return profile_id in self._sessions

    def get_session(self, profile_id: str) -> Optional[BrowserSession]:
        """Get a specific running session."""
        return self._sessions.get(profile_id)

    # ── Crash recovery ────────────────────────────────────────────

    async def recover_on_startup(self) -> None:
        """
        Check for sessions that were running when cfox-local last exited.

        For each persisted session:
        - If process is alive + playwright context responds → skip (shouldn't happen on fresh start)
        - Else → cleanup dead session
        """
        persisted = self._load_persisted_sessions()
        if not persisted:
            return

        logger.info("Recovering %d sessions from previous run", len(persisted))

        for row in persisted:
            pid = row.get("browser_pid")
            profile_id = row["profile_id"]

            is_alive = pid and psutil.pid_exists(pid)

            if is_alive:
                # Process alive but we lost the playwright context — kill it
                logger.warning(
                    "Killing orphan browser process pid=%d for profile '%s'",
                    pid,
                    row["profile_name"],
                )
                try:
                    psutil.Process(pid).terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Cleanup persisted record
            self._remove_persisted(profile_id)
            logger.info("Cleaned up dead session for '%s'", row["profile_name"])

    # ── Shutdown ──────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Stop all running sessions (called on app shutdown)."""
        # Stop heartbeat service
        heartbeat_svc = getattr(self, "_heartbeat_service", None)
        if heartbeat_svc:
            heartbeat_svc.stop()

        # Cancel all PID watchers first
        for task in self._watcher_tasks.values():
            task.cancel()
        self._watcher_tasks.clear()

        profile_ids = list(self._sessions.keys())
        for pid in profile_ids:
            try:
                await self.stop(pid)
            except Exception as e:
                logger.error("Error stopping session %s during shutdown: %s", pid, e)

    def set_heartbeat_service(self, heartbeat_service) -> None:
        """Set the heartbeat service for cloud session management."""
        self._heartbeat_service = heartbeat_service
