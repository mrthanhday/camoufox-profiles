"""Server connection management routes for cfox-local."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..config import Settings
from .ws import Event, EventBus, EventType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/server", tags=["server"])


def _broadcast_connection(status: str) -> None:
    """Broadcast a SERVER_CONNECTION event to all WS clients."""
    EventBus.instance().emit(
        Event(type=EventType.SERVER_CONNECTION, status=status)
    )


@router.get("/status")
async def server_status(request: Request):
    """Get cloud server connection status."""
    cloud_client = getattr(request.app.state, "cloud_client", None)

    if not cloud_client:
        return {
            "cloud_enabled": False,
            "connected": False,
            "server_url": None,
        }

    connected = cloud_client.is_connected
    healthy = False
    if connected:
        try:
            healthy = await cloud_client.health_check()
        except Exception:
            healthy = False

    return {
        "cloud_enabled": True,
        "connected": connected,
        "healthy": healthy,
        "server_url": cloud_client.server_url,
    }


@router.post("/connect")
async def connect_to_server(request: Request):
    """Connect to cfox-server using configured credentials."""
    settings: Settings = request.app.state.settings

    if not settings.server_url or not settings.server_api_key:
        return {"error": "Server URL and API key not configured", "connected": False}

    from ..services.cloud_client import CloudClient
    from ..services.heartbeat_service import HeartbeatService

    client = CloudClient(
        server_url=settings.server_url,
        api_key=settings.server_api_key,
    )

    ok = await client.connect()
    if ok:
        # Tear down old heartbeat if any
        old_hb = getattr(request.app.state, "heartbeat_service", None)
        if old_hb:
            try:
                old_hb.stop()
            except Exception:
                pass
        request.app.state.cloud_client = client
        bsm = request.app.state.session_manager
        heartbeat = HeartbeatService(
            heartbeat_fn=client.heartbeat,
            on_lock_lost=bsm.on_heartbeat_death,
        )
        heartbeat.start()
        bsm.set_heartbeat_service(heartbeat)
        bsm.set_cloud_context(client, settings.machine_id)
        request.app.state.heartbeat_service = heartbeat
        logger.info("Connected to cfox-server: %s", settings.server_url)
        _broadcast_connection("connected")
        return {"connected": True, "server_url": settings.server_url}
    else:
        await client.disconnect()
        return {"connected": False, "error": "Server health check failed"}


@router.post("/disconnect")
async def disconnect_from_server(request: Request):
    """Disconnect from cfox-server."""
    heartbeat = getattr(request.app.state, "heartbeat_service", None)
    if heartbeat:
        try:
            heartbeat.stop()
        except Exception:
            pass
        request.app.state.heartbeat_service = None
    cloud_client = getattr(request.app.state, "cloud_client", None)
    if cloud_client:
        await cloud_client.disconnect()
        request.app.state.cloud_client = None
        logger.info("Disconnected from cfox-server")
    try:
        request.app.state.session_manager.clear_cloud_context()
    except Exception:
        pass

    _broadcast_connection("disconnected")
    return {"connected": False}
