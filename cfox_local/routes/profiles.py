"""Profile CRUD routes — unified list for local (Phase 1) + cloud (Phase 3)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from camoufox_profiles.exceptions import ProfileNotFoundError

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
    source: str = "local"


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


def _cloud_profile_to_response(cp: Dict[str, Any]) -> Dict[str, Any]:
    """Convert cloud server profile response to match local ProfileResponse shape."""
    return {
        "id": cp.get("id", ""),
        "name": cp.get("name", ""),
        "source": "cloud",
        "os": cp.get("target_os", "windows"),
        "status": "locked" if cp.get("locked_by") else "idle",
        "tags": cp.get("tags", []),
        "notes": cp.get("notes", ""),
        "sessions": cp.get("total_sessions", 0),
        "created_at": cp.get("created_at", ""),
        "last_used_at": cp.get("last_used_at"),
        "proxy_server": cp.get("proxy_server"),
        "warmup_completed": cp.get("warmup_completed", False),
    }


# ── Dependency injection (set by app.py) ─────────────────────────

_pm = None  # ProfileManager
_bsm = None  # BrowserSessionManager


def init_routes(profile_manager: Any, session_manager: Any) -> None:
    """Inject dependencies."""
    global _pm, _bsm
    _pm = profile_manager
    _bsm = session_manager


def _get_cloud_client(request: Request):
    """Get cloud client from app state, or None if not connected."""
    return getattr(request.app.state, "cloud_client", None)


# ── Endpoints ────────────────────────────────────────────────────


@router.get("")
@router.get("")
async def list_profiles(request: Request) -> Dict[str, Any]:
    """List all profiles (local + cloud if connected).

    When the same profile_id exists in both local SQLite (cloud-shadow) and
    cloud server, the cloud entry wins so the UI shows authoritative cloud
    state (lock owner, version, etc.).
    """
    # Local profiles
    local_profiles = await _pm.store.list()
    local_items = [
        _profile_to_response(p, "local", _bsm.is_running(p.id))
        for p in local_profiles
    ]

    # Cloud profiles (if connected)
    cloud_client = _get_cloud_client(request)
    server_connected = cloud_client is not None and cloud_client.is_connected
    cloud_items: List[Dict[str, Any]] = []
    cloud_ids: set[str] = set()

    if server_connected:
        try:
            cloud_data = await cloud_client.list_profiles()
            for cp in cloud_data.get("profiles", []):
                cid = cp.get("id")
                if cid:
                    cloud_ids.add(cid)
                # Reflect runtime browser status from local BSM (the cloud
                # server only knows lock state, not whether the browser is
                # actually running on this machine).
                resp = _cloud_profile_to_response(cp)
                if cid and _bsm.is_running(cid):
                    resp["status"] = "running"
                cloud_items.append(resp)
        except Exception as e:
            logger.warning("Failed to fetch cloud profiles: %s", e)
            server_connected = False

    # Dedup: drop local-shadow entries whose id matches a cloud profile.
    items = [it for it in local_items if it["id"] not in cloud_ids] + cloud_items

    return {
        "profiles": items,
        "server_connected": server_connected,
    }


@router.post("", status_code=201)
async def create_profile(req: CreateProfileRequest, request: Request) -> Dict[str, Any]:
    """Create a new profile with a unique fingerprint."""

    # ── Cloud profile ──
    if req.source == "cloud":
        cloud_client = _get_cloud_client(request)
        if not cloud_client or not cloud_client.is_connected:
            raise HTTPException(status_code=503, detail="Cloud server not connected")

        # Generate the fingerprint locally — the cloud server doesn't ship the
        # GeoIP DB or BrowserForge wheel and only stores the config, so the
        # client is the right place to capture it. Tag-limit check still applies.
        if req.tags:
            tag_limit = getattr(request.app.state.settings, "max_tags_per_profile", 10)
            if len(req.tags) > tag_limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum {tag_limit} tags per profile allowed",
                )

        from camoufox_profiles.fingerprint import capture_fingerprint
        from camoufox_profiles.models import ProxyConfig

        proxy_dict = None
        if req.proxy_server:
            proxy_dict = ProxyConfig(
                server=req.proxy_server,
                username=req.proxy_username,
                password=req.proxy_password,
            ).to_playwright()

        try:
            fingerprint_config = capture_fingerprint(
                target_os=req.os,
                proxy=proxy_dict,
                geoip=req.geoip or (True if proxy_dict else None),
                block_webrtc=req.block_webrtc,
            )
        except Exception as e:
            logger.error("Fingerprint capture failed: %s", e)
            raise HTTPException(status_code=500, detail=f"Fingerprint capture failed: {e}")

        cloud_data: Dict[str, Any] = {
            "name": req.name,
            "target_os": req.os,
            "tags": req.tags or [],
            "notes": req.notes or "",
            "fingerprint_config": fingerprint_config,
        }
        if req.proxy_server:
            cloud_data["proxy_server"] = req.proxy_server
            cloud_data["proxy_username"] = req.proxy_username
            cloud_data["proxy_password"] = req.proxy_password
        if req.proxy_id:
            cloud_data["proxy_id"] = req.proxy_id

        try:
            result = await cloud_client.create_profile(cloud_data)
        except Exception as e:
            logger.error("Cloud create failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Cloud create failed: {e}")

        # Mirror the cloud profile into the local SQLite as a "cloud-shadow"
        # entry. This lets BrowserSessionManager.launch() / stop() / health
        # treat cloud profiles uniformly. The shadow shares the cloud profile
        # id so heartbeat / unlock match by id.
        try:
            cloud_id = result.get("id")
            cloud_proxy = None
            if result.get("proxy_server"):
                cloud_proxy = ProxyConfig(
                    server=result["proxy_server"],
                    username=result.get("proxy_username"),
                    password=result.get("proxy_password"),
                )
            await _pm.store.create(
                name=result["name"],
                target_os=result.get("target_os", req.os),
                fingerprint_config=fingerprint_config,
                proxy=cloud_proxy,
                tags=result.get("tags", []),
                notes=result.get("notes", ""),
                proxy_id=result.get("proxy_id"),
                profile_id=cloud_id,
            )
        except Exception as e:
            # Mirror failure shouldn't fail the cloud create — just log.
            logger.warning("Could not mirror cloud profile locally: %s", e)

        return _cloud_profile_to_response(result)

    # ── Local profile (existing flow) ──
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
        if req.tags:
            tag_limit = getattr(request.app.state.settings, "max_tags_per_profile", 10)
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
    request: Request,
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Get profile detail."""
    if source == "cloud":
        cloud_client = _get_cloud_client(request)
        if not cloud_client or not cloud_client.is_connected:
            raise HTTPException(status_code=503, detail="Cloud server not connected")
        try:
            result = await cloud_client.get_profile(profile_id)
            return _cloud_profile_to_response(result)
        except Exception as e:
            logger.error("Cloud get failed: %s", e)
            # Surface a 404 if it looks like a missing profile, otherwise 502
            msg = str(e).lower()
            if "404" in msg or "not found" in msg:
                raise HTTPException(status_code=404, detail="Cloud profile not found")
            raise HTTPException(status_code=502, detail=f"Cloud get failed: {e}")

    try:
        profile = await _pm.store.get(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")

    return _profile_to_response(profile, "local", _bsm.is_running(profile_id))


@router.put("/{profile_id}")
async def update_profile(
    profile_id: str,
    req: UpdateProfileRequest,
    request: Request,
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Update profile metadata."""
    if source == "cloud":
        cloud_client = _get_cloud_client(request)
        if not cloud_client or not cloud_client.is_connected:
            raise HTTPException(status_code=503, detail="Cloud server not connected")
        try:
            cloud_payload: Dict[str, Any] = {}
            if req.name is not None:
                cloud_payload["name"] = req.name
            if req.tags is not None:
                cloud_payload["tags"] = req.tags
            if req.notes is not None:
                cloud_payload["notes"] = req.notes
            result = await cloud_client.update_profile(profile_id, cloud_payload)
            return _cloud_profile_to_response(result)
        except Exception as e:
            logger.error("Cloud update failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Cloud update failed: {e}")

    # ── Local update ──
    try:
        await _pm.store.get(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data: Dict[str, Any] = {}
    if req.name is not None:
        update_data["name"] = req.name
    if req.tags is not None:
        # Validate tag limit
        tag_limit = getattr(request.app.state.settings, "max_tags_per_profile", 10)
        if len(req.tags) > tag_limit:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum {tag_limit} tags per profile allowed",
            )
        update_data["tags"] = req.tags
    if req.notes is not None:
        update_data["notes"] = req.notes
    if req.proxy_server is not None:
        update_data["proxy_server"] = req.proxy_server
        update_data["proxy_username"] = req.proxy_username
        update_data["proxy_password"] = req.proxy_password

    if update_data:
        try:
            await _pm.store.update(profile_id, **update_data)
        except ProfileNotFoundError:
            raise HTTPException(status_code=404, detail="Profile not found")

    # proxy_id is a V2 field — handle separately
    if req.proxy_id is not None:
        await _pm.store.update_v2_fields(profile_id, proxy_id=req.proxy_id)

    profile = await _pm.store.get(profile_id)
    return _profile_to_response(profile, "local", _bsm.is_running(profile_id))


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    request: Request,
    source: str = Query(default="local"),
) -> None:
    """Delete a profile and its browser data."""
    if source == "cloud":
        cloud_client = _get_cloud_client(request)
        if not cloud_client or not cloud_client.is_connected:
            raise HTTPException(status_code=503, detail="Cloud server not connected")
        try:
            await cloud_client.delete_profile(profile_id)
        except Exception as e:
            logger.error("Cloud delete failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Cloud delete failed: {e}")

        # Also delete the local cloud-shadow entry if it exists.
        try:
            await _pm.store.delete(profile_id)
        except ProfileNotFoundError:
            pass
        return

    # ── Local delete (existing flow) ──
    if _bsm.is_running(profile_id):
        raise HTTPException(status_code=409, detail="Cannot delete a running profile")

    try:
        profile = await _pm.store.get(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")

    await _pm.store.delete(profile_id)
