"""Server connection management routes for cfox-local."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..config import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/server", tags=["server"])


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

    client = CloudClient(
        server_url=settings.server_url,
        api_key=settings.server_api_key,
    )

    ok = await client.connect()
    if ok:
        request.app.state.cloud_client = client
        logger.info("Connected to cfox-server: %s", settings.server_url)
        return {"connected": True, "server_url": settings.server_url}
    else:
        await client.disconnect()
        return {"connected": False, "error": "Server health check failed"}


@router.post("/disconnect")
async def disconnect_from_server(request: Request):
    """Disconnect from cfox-server."""
    cloud_client = getattr(request.app.state, "cloud_client", None)
    if cloud_client:
        await cloud_client.disconnect()
        request.app.state.cloud_client = None
        logger.info("Disconnected from cfox-server")

    return {"connected": False}
