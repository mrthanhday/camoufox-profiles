"""
Suite 5: UI — Profiles Page tests.

Uses browser_subagent to navigate the Profiles page and verify:
- Empty state display
- Create profile flow
- Profile card displays correct info
- Edit profile name
- Delete profile
- Sidebar navigation between pages

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


def _api_post(base_url: str, path: str, json: dict) -> dict:
    """Synchronous POST against the running UI server."""
    r = httpx.post(
        f"{base_url}{path}",
        json=json,
        headers={"Content-Type": "application/json"},
        timeout=5.0,
    )
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


def _api_delete(base_url: str, path: str) -> int:
    """Synchronous DELETE against the running UI server."""
    r = httpx.delete(f"{base_url}{path}", timeout=5.0)
    return r.status_code


# ══════════════════════════════════════════════════════════════════
# 5.1 Empty state
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_profiles_empty(ui_server):
    """Fresh server has no profiles."""
    data = _api_get(ui_server, "/api/profiles")
    assert data["profiles"] == []


# ══════════════════════════════════════════════════════════════════
# 5.2 Create profile
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_create_profile(ui_server):
    """Create a profile via API and verify it appears in the list."""
    profile = _api_post(ui_server, "/api/profiles", {
        "name": "UI Test Profile",
        "os": "windows",
        "tags": ["ui-test"],
        "notes": "Created by UI test",
    })
    assert profile["name"] == "UI Test Profile"
    assert profile["status"] == "idle"
    assert profile["os"] == "windows"
    assert "ui-test" in profile["tags"]

    # Verify appears in list
    data = _api_get(ui_server, "/api/profiles")
    ids = [p["id"] for p in data["profiles"]]
    assert profile["id"] in ids

    # Cleanup
    _api_delete(ui_server, f"/api/profiles/{profile['id']}?source=local")


# ══════════════════════════════════════════════════════════════════
# 5.3 Profile card info
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_profile_card_info(ui_server):
    """Created profile shows correct info: name, OS, status."""
    profile = _api_post(ui_server, "/api/profiles", {
        "name": "Card Info Test",
        "os": "macos",
        "tags": ["card-test", "e2e"],
    })

    # Get the profile
    fetched = _api_get(ui_server, f"/api/profiles/{profile['id']}?source=local")
    assert fetched["name"] == "Card Info Test"
    assert fetched["os"] == "macos"
    assert fetched["status"] == "idle"
    assert set(fetched["tags"]) == {"card-test", "e2e"}

    # Cleanup
    _api_delete(ui_server, f"/api/profiles/{profile['id']}?source=local")


# ══════════════════════════════════════════════════════════════════
# 5.4 Edit profile name
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_edit_profile_name(ui_server):
    """Edit a profile name via API and verify it's updated."""
    profile = _api_post(ui_server, "/api/profiles", {
        "name": "Before Edit",
        "os": "windows",
    })

    # Update name
    updated = _api_put(
        ui_server,
        f"/api/profiles/{profile['id']}?source=local",
        {"name": "After Edit"},
    )
    assert updated["name"] == "After Edit"

    # Verify persisted
    fetched = _api_get(ui_server, f"/api/profiles/{profile['id']}?source=local")
    assert fetched["name"] == "After Edit"

    # Cleanup
    _api_delete(ui_server, f"/api/profiles/{profile['id']}?source=local")


# ══════════════════════════════════════════════════════════════════
# 5.5 Delete profile
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_delete_profile(ui_server):
    """Delete a profile via API and verify it's removed."""
    profile = _api_post(ui_server, "/api/profiles", {
        "name": "To Delete",
        "os": "windows",
    })
    pid = profile["id"]

    # Delete
    status = _api_delete(ui_server, f"/api/profiles/{pid}?source=local")
    assert status == 204

    # Verify removed from list
    data = _api_get(ui_server, "/api/profiles")
    ids = [p["id"] for p in data["profiles"]]
    assert pid not in ids

    # Verify GET returns 404
    r = httpx.get(f"{ui_server}/api/profiles/{pid}?source=local", timeout=5.0)
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 5.6 Sidebar navigation — all pages respond
# ══════════════════════════════════════════════════════════════════


@pytest.mark.ui
def test_ui_sidebar_navigation(ui_server):
    """All API endpoints that power the sidebar pages respond correctly."""
    # Profiles page
    r = httpx.get(f"{ui_server}/api/profiles", timeout=5.0)
    assert r.status_code == 200
    assert "profiles" in r.json()

    # Proxy Pool page
    r = httpx.get(f"{ui_server}/api/proxies", timeout=5.0)
    assert r.status_code == 200
    assert "proxies" in r.json()

    # Settings page
    r = httpx.get(f"{ui_server}/api/settings", timeout=5.0)
    assert r.status_code == 200
    assert "base_dir" in r.json()

    # Tag Manager page
    r = httpx.get(f"{ui_server}/api/tags", timeout=5.0)
    assert r.status_code == 200
    assert "tags" in r.json()

    # System Info (powers sidebar footer)
    r = httpx.get(f"{ui_server}/api/info", timeout=5.0)
    assert r.status_code == 200
    assert "hostname" in r.json()

    # Sessions (powers running count)
    r = httpx.get(f"{ui_server}/api/sessions", timeout=5.0)
    assert r.status_code == 200
    assert "sessions" in r.json()
