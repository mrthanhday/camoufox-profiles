"""Local proxy pool routes."""

from __future__ import annotations

import logging
import re
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


class BulkAddProxyRequest(BaseModel):
    proxies: List[Dict[str, Optional[str]]]
    tags: List[str] = Field(default_factory=list)
    skip_duplicates: bool = True


class UpdateProxyRequest(BaseModel):
    tags: Optional[List[str]] = None


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager


def init_routes(profile_manager: Any, **_: Any) -> None:
    global _pm
    _pm = profile_manager


def _get_proxy_store() -> Any:
    """Lazily get the proxy store from ProfileManager's db."""
    from camoufox_profiles.proxy import ProxyStore
    return ProxyStore(_pm.store._ensure_db())


def _normalize_server(server: str) -> str:
    """Normalize server string for dedup comparison: strip protocol, lowercase."""
    s = re.sub(r'^https?://', '', server, flags=re.IGNORECASE)
    s = re.sub(r'^socks[45]?://', '', s, flags=re.IGNORECASE)
    return s.lower().rstrip('/')


def _proxy_to_dict(e: Any) -> Dict[str, Any]:
    """Convert ProxyPoolEntry to API response dict."""
    return {
        "id": e.id,
        "server": e.server,
        "username": e.username,
        "tags": e.tags or [],
        "is_alive": e.is_alive,
        "last_checked_at": e.last_checked_at,
        "last_latency_ms": e.last_latency_ms,
        "last_ip": e.last_ip,
    }


# ── Endpoints ────────────────────────────────────────────────────


@router.get("")
async def list_proxies() -> Dict[str, Any]:
    """List all proxies in the local pool."""
    ps = _get_proxy_store()
    entries = await ps.list()
    return {
        "proxies": [_proxy_to_dict(e) for e in entries],
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
    return _proxy_to_dict(entry)


@router.delete("/{proxy_id}", status_code=204)
async def remove_proxy(proxy_id: str) -> None:
    """Remove a proxy from the local pool."""
    ps = _get_proxy_store()
    entry = await ps.get(proxy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    await ps.delete(proxy_id)


@router.put("/{proxy_id}")
async def update_proxy(proxy_id: str, req: UpdateProxyRequest) -> Dict[str, Any]:
    """Update proxy metadata (tags)."""
    ps = _get_proxy_store()
    entry = await ps.get(proxy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Proxy not found")

    if req.tags is not None:
        db = _pm.store._ensure_db()
        import orjson
        await db.execute(
            "UPDATE proxy_pool SET tags = ? WHERE id = ?",
            (orjson.dumps(req.tags).decode("utf-8"), proxy_id),
        )
        await db.commit()

    updated = await ps.get(proxy_id)
    return _proxy_to_dict(updated)


@router.post("/check")
async def check_proxies() -> Dict[str, Any]:
    """Health check all proxies in the local pool."""
    ps = _get_proxy_store()
    results = await ps.check_all()
    return {
        "checked": len(results),
        "results": [_proxy_to_dict(r) for r in results],
    }


@router.post("/{proxy_id}/check")
async def check_single_proxy(proxy_id: str) -> Dict[str, Any]:
    """Health check a single proxy."""
    ps = _get_proxy_store()
    entry = await ps.get(proxy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Proxy not found")

    from camoufox_profiles.proxy import check_proxy_health
    alive, ip, latency = await check_proxy_health(
        entry.server, entry.username, entry.password
    )
    await ps.update_health(entry.id, alive, ip, latency)
    updated = await ps.get(proxy_id)
    return _proxy_to_dict(updated)


@router.post("/bulk", status_code=201)
async def bulk_add_proxies(req: BulkAddProxyRequest) -> Dict[str, Any]:
    """Bulk add proxies with dedup support."""
    ps = _get_proxy_store()

    # Get existing servers for dedup
    existing = await ps.list()
    existing_normalized = {_normalize_server(e.server) for e in existing}

    added = 0
    skipped = 0
    new_entries = []

    for p in req.proxies:
        server = p.get("server", "")
        if not server:
            skipped += 1
            continue

        if req.skip_duplicates and _normalize_server(server) in existing_normalized:
            skipped += 1
            continue

        try:
            entry = await ps.add(
                server=server,
                username=p.get("username"),
                password=p.get("password"),
                tags=req.tags or None,
            )
            new_entries.append(entry)
            existing_normalized.add(_normalize_server(server))
            added += 1
        except Exception:
            skipped += 1

    return {
        "added": added,
        "skipped": skipped,
        "proxies": [_proxy_to_dict(e) for e in new_entries],
    }
