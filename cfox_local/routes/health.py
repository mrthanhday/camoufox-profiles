"""Health and drift history routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profiles", tags=["health"])


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager


def init_routes(profile_manager: Any, **_: Any) -> None:
    global _pm
    _pm = profile_manager


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/{profile_id}/health")
async def health_check(
    profile_id: str,
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Run health diagnostics on a profile."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    try:
        report = await _pm.health_check(profile_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "profile_id": profile_id,
        "status": report.status,
        "score": report.score,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "severity": c.severity,
                "message": c.message,
            }
            for c in report.checks
        ],
    }


@router.get("/{profile_id}/drift")
async def drift_history(
    profile_id: str,
    limit: int = Query(default=50, le=200),
    source: str = Query(default="local"),
) -> Dict[str, Any]:
    """Get drift event history for a profile."""
    if source != "local":
        raise HTTPException(status_code=501, detail="Cloud profiles not yet supported")

    profile = await _pm.store.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    events = await _pm.store.get_drift_events(profile_id, limit=limit)
    return {
        "profile_id": profile_id,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
