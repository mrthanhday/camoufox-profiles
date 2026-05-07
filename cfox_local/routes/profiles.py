"""Profile CRUD routes — unified list for local (Phase 1) + cloud (Phase 3)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# ── Request/Response models ──────────────────────────────────────


class CreateProfileRequest(BaseModel):
    name: str
    os: str = "windows"
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    proxy_id: Optional[str] = None
    geoip: Optional[str] = None
    block_webrtc: bool = False
    tags: List[str] = Field(default_factory=list)
    notes: str = ""
    source: str = "local"  # Phase 1: always local


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    proxy_id: Optional[str] = None


class ProfileResponse(BaseModel):
    id: str
    name: str
    source: str
    os: str
    status: str
    tags: List[str]
    notes: str
    sessions: int
    created_at: str
    last_used_at: Optional[str]
    proxy_server: Optional[str]
    warmup_completed: bool


# ── Helper ───────────────────────────────────────────────────────


def _profile_to_response(profile: Any, source: str, is_running: bool) -> Dict[str, Any]:
    """Convert V2 Profile model to API response dict."""
    return {
        "id": profile.id,
        "name": profile.name,
        "source": source,
        "os": profile.target_os,
        "status": "running" if is_running else "idle",
        "tags": profile.tags or [],
        "notes": profile.notes or "",
        "sessions": profile.total_sessions,
        "created_at": profile.created_at.isoformat() if profile.created_at else "",
        "last_used_at": profile.last_used_at.isoformat() if profile.last_used_at else None,
        "proxy_server": profile.proxy.server if profile.proxy else None,
        "warmup_completed": profile.warmup_completed,
    }


# ── Dependency injection (set by app.py) ─────────────────────────

_pm = None  # ProfileManager
_bsm = None  # BrowserSessionManager


def init_routes(profile_manager: Any, session_manager: Any) -> None:
    """Inject dependencies."""
    global _pm, _bsm
    _pm = profile_manager
    _bsm = session_manager


# ── Endpoints ────────────────────────────────────────────────────


@router.get("")
async def list_profiles() -> Dict[str, Any]:
    """List all profiles (Phase 1: local only)."""
    profiles = await _pm.store.list()
    items = [
        _profile_to_response(p, "local", _bsm.is_running(p.id))
        for p in profiles
    ]
    return {
        "profiles": items,
        "server_connected": False,  # Phase 3
    }


@router.post("", status_code=201)
async def create_profile(req: CreateProfileRequest) -> Dict[str, Any]:
    """Create a new profile with a unique fingerprint."""
    from camoufox_profiles.models import ProxyConfig

    proxy = None
    if req.proxy_server:
        proxy = ProxyConfig(
            server=req.proxy_server,
            username=req.proxy_username,
            password=req.proxy_password,
        )

    try:
        # Validate tag limit
        max_tags = getattr(_pm, '_settings', None)
        if req.tags:
            from fastapi import Request
            # Get max_tags from app settings
            tag_limit = 10  # default
            try:
                import importlib
                from ..config import Settings
                tag_limit = Settings.load().max_tags_per_profile
            except Exception:
                pass
            if len(req.tags) > tag_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum {tag_limit} tags per profile allowed",
                )

        profile = await _pm.create_profile(
            name=req.name,
            os=req.os,
            proxy=proxy,
            proxy_id=req.proxy_id,
            geoip=req.geoip or (True if proxy or req.proxy_id else None),
            block_webrtc=req.block_webrtc,
            tags=req.tags or None,
            notes=req.notes,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _profile_to_response(profile, "local", False)


@router.get("/{profile_id}")
async def get_profile(
    profile_id: str,
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Get profile detail."""
    # Phase 1: only local
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    profile = await _pm.store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    return _profile_to_response(profile, "local", _bsm.is_running(profile_id))


@router.put("/{profile_id}")
async def update_profile(
    profile_id: str,
    req: UpdateProfileRequest,
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Update profile metadata."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    profile = await _pm.store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data: Dict[str, Any] = {}
    if req.name is not None:
        update_data["name"] = req.name
    if req.tags is not None:
        # Validate tag limit
        tag_limit = 10
        try:
            from .profiles import _get_tag_limit
        except ImportError:
            pass
        try:
            from ..config import Settings
            tag_limit = Settings.load().max_tags_per_profile
        except Exception:
            pass
        if len(req.tags) > tag_limit:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum {tag_limit} tags per profile allowed",
            )
        update_data["tags"] = req.tags
    if req.notes is not None:
        update_data["notes"] = req.notes

    if update_data:
        await _pm.store.update(profile_id, **update_data)

    # Handle proxy update (direct SQL — store.update() doesn't handle proxy fields)
    if req.proxy_server is not None:
        from camoufox_profiles.models import ProxyConfig
        db = _pm.store._ensure_db()
        await db.execute(
            "UPDATE profiles SET proxy_server = ?, proxy_username = ?, proxy_password = ? WHERE id = ?",
            (req.proxy_server, req.proxy_username, req.proxy_password, profile_id),
        )
        await db.commit()
    elif req.proxy_id is not None:
        db = _pm.store._ensure_db()
        await db.execute(
            "UPDATE profiles SET proxy_id = ? WHERE id = ?",
            (req.proxy_id, profile_id),
        )
        await db.commit()

    profile = await _pm.store.get(profile_id)
    return _profile_to_response(profile, "local", _bsm.is_running(profile_id))


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    source: str = Query(default="local"),
) -> None:
    """Delete a profile and its browser data."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    if _bsm.is_running(profile_id):
        raise HTTPException(status_code=409, detail="Cannot delete a running profile")

    profile = await _pm.store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    await _pm.store.delete(profile_id)
