"""Browser control routes — launch, stop, warmup."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["browser"])


# ── Request models ───────────────────────────────────────────────


class LaunchRequest(BaseModel):
    headless: bool = False
    drift: bool = True
    startup_url: Optional[str] = None


class WarmupRequest(BaseModel):
    max_sites: int = 10


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager
_bsm = None  # BrowserSessionManager


def init_routes(profile_manager: Any, session_manager: Any) -> None:
    global _pm, _bsm
    _pm = profile_manager
    _bsm = session_manager


# ── Endpoints ────────────────────────────────────────────────────


@router.post("/profiles/{profile_id}/launch")
async def launch_profile(
    profile_id: str,
    req: LaunchRequest = LaunchRequest(),
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Launch a browser for a profile."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    if _bsm.is_running(profile_id):
        raise HTTPException(status_code=409, detail="Profile is already running")

    try:
        session = await _bsm.launch(
            profile_id=profile_id,
            source=source,
            headless=req.headless,
            drift=req.drift,
        )
        return session.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to launch profile %s: %s", profile_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiles/{profile_id}/stop")
async def stop_profile(
    profile_id: str,
    source: str = Query(default="local"),
) -> Dict[str, str]:
    """Stop a running browser session."""
    try:
        await _bsm.stop(profile_id)
        return {"status": "stopped"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to stop profile %s: %s", profile_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_sessions() -> Dict[str, Any]:
    """List all running browser sessions."""
    return {"sessions": _bsm.get_sessions()}


@router.post("/profiles/{profile_id}/warmup")
async def warmup_profile(
    profile_id: str,
    req: WarmupRequest = WarmupRequest(),
    background_tasks: BackgroundTasks = None,
    source: str = Query(default="local"),
) -> Dict[str, str]:
    """Run warmup for a profile (launches browser, visits popular sites)."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    if _bsm.is_running(profile_id):
        raise HTTPException(
            status_code=409,
            detail="Profile is already running — stop it first to run warmup",
        )

    profile = await _pm.store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Run warmup in background
    async def _run_warmup() -> None:
        try:
            from camoufox_profiles.warmup import warmup_profile as do_warmup

            report = await do_warmup(
                profile_manager=_pm,
                profile_id=profile_id,
                max_sites=req.max_sites,
            )
            logger.info(
                "Warmup complete for '%s': %d/%d sites",
                profile.name,
                report.successful_visits,
                report.total_visits,
            )
        except Exception as e:
            logger.error("Warmup failed for '%s': %s", profile.name, e)

    background_tasks.add_task(_run_warmup)

    return {"status": "warmup_started", "max_sites": str(req.max_sites)}
