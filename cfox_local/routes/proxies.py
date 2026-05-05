"""Local proxy pool routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/proxies", tags=["proxies"])


# ── Request models ───────────────────────────────────────────────


class AddProxyRequest(BaseModel):
    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager


def init_routes(profile_manager: Any, **_: Any) -> None:
    global _pm
    _pm = profile_manager


def _get_proxy_store() -> Any:
    """Lazily get the proxy store from ProfileManager's db."""
    from camoufox_profiles.proxy import ProxyStore
    return ProxyStore(_pm.store._ensure_db())


# ── Endpoints ────────────────────────────────────────────────────


@router.get("")
async def list_proxies() -> Dict[str, Any]:
    """List all proxies in the local pool."""
    ps = _get_proxy_store()
    entries = await ps.list()
    return {
        "proxies": [
            {
                "id": e.id,
                "server": e.server,
                "username": e.username,
                "tags": e.tags or [],
                "is_alive": e.is_alive,
                "last_checked_at": e.last_checked_at.isoformat() if e.last_checked_at else None,
                "last_latency_ms": e.last_latency_ms,
                "last_ip": e.last_ip,
            }
            for e in entries
        ],
        "source": "local",
    }


@router.post("", status_code=201)
async def add_proxy(req: AddProxyRequest) -> Dict[str, Any]:
    """Add a proxy to the local pool."""
    ps = _get_proxy_store()
    entry = await ps.add(
        server=req.server,
        username=req.username,
        password=req.password,
        tags=req.tags or None,
    )
    return {
        "id": entry.id,
        "server": entry.server,
        "username": entry.username,
        "tags": entry.tags or [],
        "is_alive": entry.is_alive,
    }


@router.delete("/{proxy_id}", status_code=204)
async def remove_proxy(proxy_id: str) -> None:
    """Remove a proxy from the local pool."""
    ps = _get_proxy_store()
    entry = await ps.get(proxy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    await ps.remove(proxy_id)


@router.post("/check")
async def check_proxies() -> Dict[str, Any]:
    """Health check all proxies in the local pool."""
    ps = _get_proxy_store()
    results = await ps.check_all()
    return {
        "checked": len(results),
        "results": [
            {
                "id": r.id,
                "server": r.server,
                "is_alive": r.is_alive,
                "latency_ms": r.last_latency_ms,
                "ip": r.last_ip,
            }
            for r in results
        ],
    }
