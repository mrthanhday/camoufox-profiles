"""Health and drift history routes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from camoufox_profiles.exceptions import ProfileNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profiles", tags=["health"])


# ── Dependency injection ─────────────────────────────────────────

_pm = None  # ProfileManager


def init_routes(profile_manager: Any, **_: Any) -> None:
    global _pm
    _pm = profile_manager


def _compute_score(checks: List[Any]) -> int:
    """Compute a 0-100 health score from check results.

    Scoring: each non-passing check deducts points by severity.
    """
    if not checks:
        return 100

    deductions = {"info": 5, "warning": 15, "critical": 40}
    score = 100
    for c in checks:
        if not c.passed:
            score -= deductions.get(c.severity, 5)
    return max(0, score)


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
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")
    except Exception as e:
        logger.error("Health check failed for %s: %s", profile_id, e)
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "profile_id": profile_id,
        "profile_name": report.profile_name,
        "status": report.status,
        "score": _compute_score(report.checks),
        "checks": [
            {
                "name": c.check_name,
                "passed": c.passed,
                "severity": c.severity,
                "message": c.message,
                "recommendation": c.recommendation,
            }
            for c in report.checks
        ],
        "recommendations": report.recommendations,
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

    try:
        await _pm.store.get(profile_id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profile not found")

    events = await _pm.store.get_drift_history(profile_id, limit=limit)
    return {
        "profile_id": profile_id,
        "events": [
            {
                "id": e.id,
                "drift_type": e.drift_type,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "timestamp": e.timestamp,
            }
            for e in events
        ],
    }
