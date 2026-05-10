"""
Suite 2: cfox-local API tests.

Tests all local launcher endpoints: info, settings, browse, drives,
profile CRUD, sessions, and server status.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from httpx import AsyncClient

from .conftest import create_local_profile


# ══════════════════════════════════════════════════════════════════
# 2.1 System Info
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_info(local_client: AsyncClient):
    """GET /api/info returns machine_id, hostname, version."""
    resp = await local_client.get("/api/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["machine_id"] == "e2e-machine-001"
    assert "hostname" in data
    assert "version" in data
    assert data["platform"] in ("windows", "linux", "darwin")


# ══════════════════════════════════════════════════════════════════
# 2.2 Settings — GET
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_settings_get(local_client: AsyncClient):
    """GET /api/settings returns all config fields."""
    resp = await local_client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "base_dir" in data
    assert data["port"] == 9600
    assert data["host"] == "127.0.0.1"
    assert "max_tags_per_profile" in data
    assert "profile_count" in data
    assert "storage_size_bytes" in data
    # No cloud configured in this fixture
    assert data.get("server_url") is None
    assert data["cloud_enabled"] is False


# ══════════════════════════════════════════════════════════════════
# 2.3 Settings — Update max_tags
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_settings_update_max_tags(local_client: AsyncClient):
    """PUT /api/settings with max_tags → no restart required."""
    resp = await local_client.put("/api/settings", json={
        "max_tags_per_profile": 15,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_tags_per_profile"] == 15
    assert data["restart_required"] is False
    assert "max_tags_per_profile" in data["changed_fields"]


# ══════════════════════════════════════════════════════════════════
# 2.4 Settings — Update base_dir (restart required)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_settings_base_dir(local_client: AsyncClient, tmp_path):
    """PUT /api/settings with base_dir → restart_required=true."""
    new_dir = tmp_path / "new_profiles"
    new_dir.mkdir()

    resp = await local_client.put("/api/settings", json={
        "base_dir": str(new_dir),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["restart_required"] is True
    assert data["base_dir"] == str(new_dir)


# ══════════════════════════════════════════════════════════════════
# 2.5 Settings — Invalid max_tags
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_settings_invalid(local_client: AsyncClient):
    """PUT /api/settings with max_tags > 100 → 400."""
    resp = await local_client.put("/api/settings", json={
        "max_tags_per_profile": 999,
    })
    # max_tags_per_profile must be between 1 and 100
    assert resp.status_code == 400
    detail = resp.json()["detail"].lower()
    assert "must be between" in detail or "between" in detail


# ══════════════════════════════════════════════════════════════════
# 2.6 Browse Directories
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_browse_dirs(local_client: AsyncClient, tmp_path):
    """GET /api/settings/browse returns directory listing."""
    # Create some subdirectories
    (tmp_path / "subdir_a").mkdir()
    (tmp_path / "subdir_b").mkdir()
    (tmp_path / ".hidden").mkdir()  # Should be excluded

    resp = await local_client.get(f"/api/settings/browse?path={tmp_path}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] == str(tmp_path)
    names = [d["name"] for d in data["directories"]]
    assert "subdir_a" in names
    assert "subdir_b" in names
    assert ".hidden" not in names  # Hidden dirs excluded


# ══════════════════════════════════════════════════════════════════
# 2.7 List Drives
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_drives(local_client: AsyncClient):
    """GET /api/settings/drives returns at least one drive."""
    resp = await local_client.get("/api/settings/drives")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["drives"]) >= 1
    assert "name" in data["drives"][0]
    assert "path" in data["drives"][0]


# ══════════════════════════════════════════════════════════════════
# 2.8 Local Profile CRUD
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_profile_crud(local_client: AsyncClient):
    """Create → List → Get → Update → Delete local profile."""
    # CREATE
    resp = await local_client.post("/api/profiles", json={
        "name": "E2E CRUD Profile",
        "os": "windows",
        "notes": "Created by e2e test",
    })
    assert resp.status_code == 201
    profile = resp.json()
    pid = profile["id"]
    assert profile["name"] == "E2E CRUD Profile"
    assert profile["status"] == "idle"

    # LIST
    resp = await local_client.get("/api/profiles")
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert any(p["id"] == pid for p in profiles)

    # GET
    resp = await local_client.get(f"/api/profiles/{pid}?source=local")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid

    # UPDATE
    resp = await local_client.put(f"/api/profiles/{pid}?source=local", json={
        "name": "Updated E2E Profile",
        "notes": "Updated by e2e test",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated E2E Profile"

    # DELETE
    resp = await local_client.delete(f"/api/profiles/{pid}?source=local")
    assert resp.status_code == 204

    # Verify deleted
    resp = await local_client.get(f"/api/profiles/{pid}?source=local")
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 2.9 Profile with Tags
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_profile_with_tags(local_client: AsyncClient):
    """Create profile with tags, verify tags persist."""
    resp = await local_client.post("/api/profiles", json={
        "name": "Tagged Profile",
        "os": "windows",
        "tags": ["alpha", "beta", "gamma"],
    })
    assert resp.status_code == 201
    profile = resp.json()
    assert set(profile["tags"]) == {"alpha", "beta", "gamma"}

    # Update tags
    resp = await local_client.put(f"/api/profiles/{profile['id']}?source=local", json={
        "tags": ["alpha", "delta"],
    })
    assert resp.status_code == 200
    assert set(resp.json()["tags"]) == {"alpha", "delta"}


# ══════════════════════════════════════════════════════════════════
# 2.10 Server Status (no cloud)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_server_status(local_client: AsyncClient):
    """GET /api/server/status when cloud not configured."""
    resp = await local_client.get("/api/server/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cloud_enabled"] is False
    assert data["connected"] is False
    assert data["server_url"] is None


# ══════════════════════════════════════════════════════════════════
# 2.11 Sessions — Empty
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_local_sessions_empty(local_client: AsyncClient):
    """GET /api/sessions when no browser running."""
    resp = await local_client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sessions"] == []


# ══════════════════════════════════════════════════════════════════
# 2.12 Delete Running Profile → 409
# ══════════════════════════════════════════════════════════════════


@pytest.mark.real_browser
@pytest.mark.asyncio
async def test_local_delete_running_profile(local_client: AsyncClient):
    """Cannot delete a profile that has an active browser session.

    This test creates a profile and simulates a running session by
    directly manipulating the session manager state.
    """
    # Create profile
    resp = await local_client.post("/api/profiles", json={
        "name": "Running Delete Test",
        "os": "windows",
    })
    assert resp.status_code == 201
    pid = resp.json()["id"]

    # Simulate running session by injecting into BSM's session dict
    app = local_client._transport._app
    bsm = app.state.session_manager
    bsm._sessions[pid] = type("FakeSession", (), {
        "profile_id": pid,
        "browser_pid": None,
        "to_dict": lambda self: {"profile_id": pid},
    })()

    try:
        # Attempt delete → should be 409
        resp = await local_client.delete(f"/api/profiles/{pid}?source=local")
        assert resp.status_code == 409
        assert "running" in resp.json()["detail"].lower()
    finally:
        # Cleanup fake session
        bsm._sessions.pop(pid, None)
