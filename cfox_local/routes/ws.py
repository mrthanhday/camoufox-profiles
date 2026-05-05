"""WebSocket event stream for real-time UI updates."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional, Set

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class EventType(str, Enum):
    BROWSER_STATUS = "browser_status"
    SYNC_STATUS = "sync_status"
    SERVER_CONNECTION = "server_connection"
    HEARTBEAT_WARNING = "heartbeat_warning"


@dataclass
class Event:
    """A real-time event sent to the UI via WebSocket."""

    type: EventType
    profile_id: Optional[str] = None
    status: str = ""
    error: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

    def to_json(self) -> bytes:
        data: Dict[str, Any] = {"type": self.type.value, "status": self.status}
        if self.profile_id:
            data["profile_id"] = self.profile_id
        if self.error:
            data["error"] = self.error
        if self.extra:
            data.update(self.extra)
        return orjson.dumps(data)


class EventBus:
    """
    Singleton event bus for broadcasting events to all connected WebSocket clients.

    Usage:
        bus = EventBus.instance()
        bus.emit(Event(type=EventType.BROWSER_STATUS, profile_id="xyz", status="running"))
    """

    _instance: Optional[EventBus] = None

    def __init__(self) -> None:
        self._subscribers: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @classmethod
    def instance(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    async def subscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.add(ws)
        logger.debug("WS client connected (%d total)", len(self._subscribers))

    async def unsubscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(ws)
        logger.debug("WS client disconnected (%d remaining)", len(self._subscribers))

    def emit(self, event: Event) -> None:
        """
        Fire-and-forget event broadcast.

        Safe to call from sync context — schedules the async broadcast.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._broadcast(event))
        except RuntimeError:
            # No event loop running (e.g. during shutdown)
            pass

    async def _broadcast(self, event: Event) -> None:
        """Send event to all subscribers, removing dead connections."""
        payload = event.to_json()
        dead: list[WebSocket] = []

        async with self._lock:
            subscribers = list(self._subscribers)

        for ws in subscribers:
            try:
                await ws.send_bytes(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers.discard(ws)


# ── WebSocket endpoint ──────────────────────────────────────────────


@router.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time event streaming."""
    await websocket.accept()
    bus = EventBus.instance()
    await bus.subscribe(websocket)

    try:
        # Keep connection alive — client sends pings, we just listen
        while True:
            # Wait for any message (ping/pong or close)
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(websocket)
