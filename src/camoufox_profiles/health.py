"""
Profile health diagnostics.

Checks proxy connectivity, UA staleness, data directory integrity,
null-proxy IP consistency, and drift schedule compliance.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import HealthCheck, HealthReport, Profile, _utcnow

logger = logging.getLogger(__name__)


def _get_dir_size_mb(path: str) -> float:
    """Calculate directory size in MB."""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
    except OSError:
        pass
    return total / (1024 * 1024)


async def check_profile_health(
    profile: Profile,
    proxy_alive: Optional[bool] = None,
    proxy_ip: Optional[str] = None,
    current_public_ip: Optional[str] = None,
    current_region: Optional[str] = None,
    installed_ff_version: Optional[int] = None,
) -> HealthReport:
    """
    Run all health checks on a profile.

    Args:
        profile: The profile to check.
        proxy_alive: Pre-checked proxy status (None = skip check).
        proxy_ip: Current resolved proxy IP.
        current_public_ip: Current public IP (for null-proxy profiles).
        current_region: Current IP's region code.
        installed_ff_version: Installed Firefox major version.

    Returns:
        HealthReport with all check results.
    """
    checks: List[HealthCheck] = []
    recommendations: List[str] = []

    # --- Stale UA check ---
    if installed_ff_version:
        ua = profile.fingerprint_config.get("navigator.userAgent", "")
        import re
        match = re.search(r"Firefox/(\d+)\.0", ua)
        if match:
            profile_ff = int(match.group(1))
            if installed_ff_version - profile_ff > 2:
                checks.append(HealthCheck(
                    check_name="stale_ua",
                    passed=False,
                    severity="warning",
                    message=f"UA has Firefox/{profile_ff}.0 but installed binary is {installed_ff_version}",
                    recommendation="Launch with drift=True to auto-update UA version",
                ))
                recommendations.append(f"cfox launch {profile.name} (drift will auto-update UA)")
            else:
                checks.append(HealthCheck(check_name="stale_ua", passed=True))

    # --- Proxy health ---
    if profile.proxy_id and proxy_alive is not None:
        if not proxy_alive:
            checks.append(HealthCheck(
                check_name="dead_proxy",
                passed=False,
                severity="critical",
                message="Proxy is unreachable",
                recommendation=f"cfox proxy rotate {profile.name}",
            ))
            recommendations.append(f"cfox proxy rotate {profile.name}")
        else:
            checks.append(HealthCheck(check_name="proxy_alive", passed=True))

    # --- Proxy IP mismatch ---
    if proxy_ip and profile.last_known_ip and proxy_ip != profile.last_known_ip:
        checks.append(HealthCheck(
            check_name="proxy_ip_mismatch",
            passed=False,
            severity="warning",
            message=f"Proxy IP changed: {profile.last_known_ip} → {proxy_ip}",
        ))

    # --- Null-proxy geo drift (CRITICAL) ---
    if not profile.proxy_id and current_region and profile.creation_region:
        if current_region != profile.creation_region:
            checks.append(HealthCheck(
                check_name="null_proxy_geo_drift",
                passed=False,
                severity="critical",
                message=(
                    f"Local IP region changed: {profile.creation_region} → {current_region}. "
                    f"Timezone/locale in fingerprint will be auto-corrected on next launch."
                ),
                recommendation="Geo properties will auto-recalculate. Consider using a fixed proxy.",
            ))
            recommendations.append("Consider assigning a fixed proxy to avoid IP-based geo drift")
        else:
            checks.append(HealthCheck(check_name="null_proxy_geo_consistent", passed=True))

    # --- Data directory checks ---
    data_dir = Path(profile.user_data_dir)
    if not data_dir.exists():
        checks.append(HealthCheck(
            check_name="data_dir_missing",
            passed=False,
            severity="critical",
            message=f"Browser data directory missing: {profile.user_data_dir}",
            recommendation="Profile storage was deleted. Warmup again to rebuild.",
        ))
        recommendations.append(f"cfox warmup {profile.name}")
    else:
        size_mb = _get_dir_size_mb(profile.user_data_dir)
        if size_mb > 500:
            checks.append(HealthCheck(
                check_name="data_dir_bloat",
                passed=False,
                severity="warning",
                message=f"Browser data is {size_mb:.0f}MB (>500MB threshold)",
                recommendation="Large cache may slow launch. Consider clearing cache.",
            ))
        else:
            checks.append(HealthCheck(check_name="data_dir_size", passed=True))

    # --- Idle check ---
    if profile.last_used_at:
        from datetime import datetime, timezone
        now = _utcnow()
        days_idle = (now - profile.last_used_at).days
        if days_idle > 30:
            checks.append(HealthCheck(
                check_name="long_idle",
                passed=False,
                severity="info",
                message=f"Profile unused for {days_idle} days",
                recommendation="Re-warmup to refresh cookies and browsing history",
            ))
            recommendations.append(f"cfox warmup {profile.name}")
        else:
            checks.append(HealthCheck(check_name="idle_check", passed=True))

    # --- No warmup check ---
    if profile.total_sessions == 0:
        checks.append(HealthCheck(
            check_name="no_warmup",
            passed=False,
            severity="warning",
            message="Profile was never used (no sessions recorded)",
            recommendation="Run warmup before using in production",
        ))
        recommendations.append(f"cfox warmup {profile.name}")

    # --- Drift overdue ---
    if profile.drift_schedule.drift_ua_version and profile.drift_schedule.next_ua_drift_at:
        try:
            from datetime import datetime
            next_drift = datetime.fromisoformat(profile.drift_schedule.next_ua_drift_at)
            if next_drift.tzinfo is None:
                next_drift = next_drift.replace(tzinfo=timezone.utc)
            if _utcnow() > next_drift:
                checks.append(HealthCheck(
                    check_name="drift_overdue",
                    passed=False,
                    severity="warning",
                    message=f"UA drift overdue since {next_drift.isoformat()[:10]}",
                    recommendation="Launch the profile to trigger auto-drift",
                ))
        except (ValueError, TypeError):
            pass

    # --- Determine overall status ---
    status = "healthy"
    for check in checks:
        if not check.passed:
            if check.severity == "critical":
                status = "critical"
                break
            elif check.severity == "warning" and status != "critical":
                status = "warning"

    return HealthReport(
        profile_id=profile.id,
        profile_name=profile.name,
        status=status,
        checks=checks,
        recommendations=list(dict.fromkeys(recommendations)),  # Deduplicate
    )
