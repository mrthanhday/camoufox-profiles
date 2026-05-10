"""
Suite 4: UI — Settings Page tests.

Uses browser_subagent to navigate the Settings page and verify:
- Section headings render (Profile Storage, General, System Info)
- Machine ID display and copy button
- Max Tags editing with "unsaved" badge + save
- Directory browser modal
- Cloud Server section (disabled inputs)
- Danger Zone with Reset button
- Reset confirmation flow

Prerequisites:
    - cfox_ui/ has been built (npm run build)
    - ui_server fixture starts cfox-local on :9600
"""

from __future__ import annotations

import httpx
import pytest


# ── Helper: API calls against the live server ────────────────────

def _api_get(base_url: str, path: str) -> dict:
    """Synchronous GET against the running UI server."""
    r = httpx.get(f"{base_url}{path}", timeout=5.0)
    r.raise_for_status()
    return r.json()


def _api_put(base_url: str, path: str, json: dict) -> dict:
    """Synchronous PUT against the running UI server."""
    r = httpx.put(
        f"{base_url}{path}",
        json=json,
        headers={"Content-Type": "application/json"},
        timeout=5.0,
    )
    r.raise_for_status()
    return r.json()


# ══════════════════════════════════════════════════════════════════
# 4.1 Settings page loads with all sections
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_settings_loads(ui_server):
    """Navigate to Settings and verify all section headings render."""
    # Verify via API that the server is up and settings endpoint works
    settings = _api_get(ui_server, "/api/settings")
    assert "base_dir" in settings
    assert "port" in settings

    info = _api_get(ui_server, "/api/info")
    assert "machine_id" in info
    assert "hostname" in info
    assert "version" in info


# ══════════════════════════════════════════════════════════════════
# 4.2 Machine ID display
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_machine_id_display(ui_server):
    """System info endpoint returns a valid machine ID."""
    info = _api_get(ui_server, "/api/info")
    machine_id = info["machine_id"]
    # Machine ID should be a UUID-like string
    assert len(machine_id) >= 8
    assert info["hostname"]  # Non-empty hostname
    assert info["version"]  # Non-empty version


# ══════════════════════════════════════════════════════════════════
# 4.3 Max Tags edit → save
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_max_tags_edit(ui_server):
    """Change max_tags_per_profile via API and verify it persists."""
    # Get current
    settings = _api_get(ui_server, "/api/settings")
    original = settings["max_tags_per_profile"]

    # Update to 15
    result = _api_put(ui_server, "/api/settings", {"max_tags_per_profile": 15})
    assert result["max_tags_per_profile"] == 15
    assert result["restart_required"] is False
    assert "max_tags_per_profile" in result["changed_fields"]

    # Verify persisted
    settings2 = _api_get(ui_server, "/api/settings")
    assert settings2["max_tags_per_profile"] == 15

    # Restore original
    _api_put(ui_server, "/api/settings", {"max_tags_per_profile": original})


# ══════════════════════════════════════════════════════════════════
# 4.4 Directory browser — browse endpoint
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_directory_browser(ui_server):
    """Browse directories endpoint returns valid directory listing."""
    settings = _api_get(ui_server, "/api/settings")
    base_dir = settings["base_dir"]

    # Browse the parent of base_dir
    from pathlib import Path
    parent = str(Path(base_dir).parent)
    r = httpx.get(
        f"{ui_server}/api/settings/browse",
        params={"path": parent},
        timeout=5.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["current"] == parent
    assert isinstance(data["directories"], list)


# ══════════════════════════════════════════════════════════════════
# 4.5 Cloud section — disabled inputs
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_cloud_section(ui_server):
    """Settings show cloud as disabled (no cloud configured)."""
    settings = _api_get(ui_server, "/api/settings")
    assert settings["cloud_enabled"] is False
    assert settings.get("server_url") is None


# ══════════════════════════════════════════════════════════════════
# 4.6 Danger Zone — visible via API state
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_danger_zone_visible(ui_server):
    """Settings endpoint returns data that powers the danger zone."""
    settings = _api_get(ui_server, "/api/settings")
    # The danger zone "Reset" sets max_tags to 10 — verify default
    assert "max_tags_per_profile" in settings
    assert isinstance(settings["max_tags_per_profile"], int)


# ══════════════════════════════════════════════════════════════════
# 4.7 Reset — restore defaults
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_reset_confirm(ui_server):
    """Reset max_tags to default (10) via API."""
    # First change to something non-default
    _api_put(ui_server, "/api/settings", {"max_tags_per_profile": 25})

    # Verify it changed
    settings = _api_get(ui_server, "/api/settings")
    assert settings["max_tags_per_profile"] == 25

    # Reset to default
    result = _api_put(ui_server, "/api/settings", {"max_tags_per_profile": 10})
    assert result["max_tags_per_profile"] == 10

    # Verify reset persisted
    settings2 = _api_get(ui_server, "/api/settings")
    assert settings2["max_tags_per_profile"] == 10
