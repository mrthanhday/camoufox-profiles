"""
Natural drift engine for fingerprint aging.

Applies scheduled, per-profile changes to safe fingerprint properties
(UA version, viewport jitter, history.length) to prevent stale-profile
detection. Identity anchors (OS, GPU, canvas, audio, screen, fonts)
are never modified.
"""

from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import DriftEvent, DriftSchedule, Profile, _new_id, _utcnow

logger = logging.getLogger(__name__)


def _get_installed_firefox_version() -> int:
    """Get Firefox major version from installed Camoufox binary."""
    try:
        from camoufox.pkgman import installed_verstr
        verstr = installed_verstr()
        return int(verstr.split(".")[0])
    except Exception:
        logger.warning("Could not determine installed Firefox version, defaulting to 142")
        return 142


def _bump_ua_version(ua: str, new_version: int) -> str:
    """
    Replace the Firefox version in a User-Agent string.

    Example:
        'Mozilla/5.0 ... Firefox/135.0' -> 'Mozilla/5.0 ... Firefox/142.0'
    """
    # Replace Firefox/NNN.0 pattern
    updated = re.sub(r"Firefox/\d+\.0", f"Firefox/{new_version}.0", ua)
    # Also update rv:NNN.0 in the UA string
    updated = re.sub(r"rv:\d+\.0", f"rv:{new_version}.0", updated)
    return updated


class DriftEngine:
    """
    Applies scheduled drift to fingerprint configs.

    Each profile has a DriftSchedule that controls which properties
    drift and at what intervals. The engine checks schedules and
    applies modifications, recording each drift as a DriftEvent.
    """

    def __init__(self):
        self._current_ff_version: Optional[int] = None

    @property
    def current_firefox_version(self) -> int:
        """Cached Firefox version from installed binary."""
        if self._current_ff_version is None:
            self._current_ff_version = _get_installed_firefox_version()
        return self._current_ff_version

    def should_drift_ua(self, schedule: DriftSchedule) -> bool:
        """Check if UA version drift is due based on schedule."""
        if not schedule.drift_ua_version:
            return False
        if schedule.next_ua_drift_at is None:
            return True  # Never drifted, always apply first time

        try:
            next_drift = datetime.fromisoformat(schedule.next_ua_drift_at)
            # Ensure timezone-aware comparison
            now = _utcnow()
            if next_drift.tzinfo is None:
                next_drift = next_drift.replace(tzinfo=timezone.utc)
            return now >= next_drift
        except (ValueError, TypeError):
            return True

    def apply_drift(
        self, profile: Profile
    ) -> Tuple[Dict[str, Any], List[DriftEvent], DriftSchedule]:
        """
        Apply scheduled drift to a profile's fingerprint config.

        Args:
            profile: Profile to apply drift to.

        Returns:
            Tuple of (modified_config, list_of_events, updated_schedule).
        """
        config = dict(profile.fingerprint_config)
        schedule = DriftSchedule.from_dict(profile.drift_schedule.to_dict())  # Copy
        events: List[DriftEvent] = []
        now = _utcnow()

        # --- UA version drift ---
        if self.should_drift_ua(schedule):
            current_version = self.current_firefox_version
            stored_version = schedule.last_ua_version

            # Only drift if binary version is actually newer
            if stored_version is None or current_version > stored_version:
                old_ua = config.get("navigator.userAgent", "")
                new_ua = _bump_ua_version(old_ua, current_version)

                if old_ua != new_ua:
                    config["navigator.userAgent"] = new_ua

                    # Also update appVersion if present
                    old_app = config.get("navigator.appVersion", "")
                    if old_app:
                        config["navigator.appVersion"] = _bump_ua_version(
                            old_app, current_version
                        )

                    events.append(DriftEvent(
                        id=_new_id(),
                        profile_id=profile.id,
                        timestamp=now.isoformat(),
                        drift_type="ua_version",
                        old_value=f"Firefox/{stored_version or '?'}.0",
                        new_value=f"Firefox/{current_version}.0",
                    ))

                    schedule.last_ua_version = current_version
                    schedule.last_ua_drift_at = now.isoformat()

            # Schedule next drift regardless
            next_drift = now + timedelta(days=schedule.ua_drift_interval_days)
            schedule.next_ua_drift_at = next_drift.isoformat()

        # --- Viewport jitter ---
        if schedule.drift_viewport:
            jitter = schedule.viewport_jitter_range
            old_w = config.get("window.innerWidth")
            old_h = config.get("window.innerHeight")

            if old_w is not None:
                delta_w = random.randint(-jitter, jitter)
                config["window.innerWidth"] = old_w + delta_w

            if old_h is not None:
                delta_h = random.randint(-jitter, jitter)
                config["window.innerHeight"] = old_h + delta_h

            if old_w is not None or old_h is not None:
                events.append(DriftEvent(
                    id=_new_id(),
                    profile_id=profile.id,
                    timestamp=now.isoformat(),
                    drift_type="viewport_jitter",
                    old_value=f"{old_w}x{old_h}",
                    new_value=f"{config.get('window.innerWidth')}x{config.get('window.innerHeight')}",
                ))

        # --- History length ---
        if schedule.drift_history_length:
            old_hist = config.get("window.history.length", 1)
            new_hist = random.randint(1, 5)
            config["window.history.length"] = new_hist

            if old_hist != new_hist:
                events.append(DriftEvent(
                    id=_new_id(),
                    profile_id=profile.id,
                    timestamp=now.isoformat(),
                    drift_type="history_length",
                    old_value=str(old_hist),
                    new_value=str(new_hist),
                ))

        # Update schedule counters
        if events:
            schedule.total_drifts += len(events)

        return config, events, schedule
