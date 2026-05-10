"""
Phase 3 Smoke Tests — end-to-end validation of the cloud sync system.

Uses SQLite backend (no PostgreSQL needed) to test:
1. Server app factory & routes
2. Auth middleware (API key)
3. Profile CRUD via API
4. Lock protocol (lock → heartbeat → unlock)
5. Essential data upload/download with checksum
6. User management (admin only)
7. Sync service (collect → restore)
8. Storage service (versioning + rotation)
9. Heartbeat service state machine
10. Upload queue dedup
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import tempfile
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Server setup ─────────────────────────────────────────────────

from cfox_server.app import create_app
from cfox_server.config import ServerSettings
from cfox_server.middleware import hash_api_key

ADMIN_KEY = "test-admin-key-smoke"
MEMBER_KEY = ""  # Will be set after user creation


@pytest_asyncio.fixture
async def server_app(tmp_path):
    """Create a cfox-server app with SQLite backend for testing."""
    settings = ServerSettings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "storage",
        admin_api_key=ADMIN_KEY,
        lock_ttl_minutes=5,
        lock_cleanup_interval_seconds=9999,  # Disable auto-cleanup
        max_versions=3,
    )
    app = create_app(settings)

    # Trigger lifespan (init DB, bootstrap admin)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def admin_client(server_app):
    """HTTP client authenticated as admin."""
    transport = ASGITransport(app=server_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": ADMIN_KEY},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def anon_client(server_app):
    """HTTP client with no auth."""
    transport = ASGITransport(app=server_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


# ══════════════════════════════════════════════════════════════════
# 1. Health & Auth
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_health(admin_client: AsyncClient):
    """Health endpoint should return OK."""
    resp = await admin_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "cfox-server"


@pytest.mark.asyncio
async def test_no_auth_rejected(anon_client: AsyncClient):
    """Requests without X-API-Key should be rejected."""
    resp = await anon_client.get("/api/profiles")
    assert resp.status_code == 401
    assert "Missing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_bad_auth_rejected(anon_client: AsyncClient):
    """Requests with invalid API key should be rejected."""
    resp = await anon_client.get(
        "/api/profiles",
        headers={"X-API-Key": "bad-key-12345"},
    )
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


# ══════════════════════════════════════════════════════════════════
# 2. Profile CRUD
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_profile_crud(admin_client: AsyncClient):
    """Full profile lifecycle: create → get → update → list → delete."""
    # CREATE
    resp = await admin_client.post("/api/profiles", json={
        "name": "Smoke Test Profile",
        "target_os": "windows",
        "fingerprint_config": {
            "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0",
            "screen.width": 1920,
        },
        "tags": ["smoke", "test"],
        "notes": "Created by smoke test",
    })
    assert resp.status_code == 201, resp.text
    profile = resp.json()
    pid = profile["id"]
    assert profile["name"] == "Smoke Test Profile"
    assert profile["target_os"] == "windows"
    assert profile["tags"] == ["smoke", "test"]
    assert profile["firefox_base_version"] == 130
    assert profile["essential_data_version"] == 0

    # GET
    resp = await admin_client.get(f"/api/profiles/{pid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid

    # UPDATE
    resp = await admin_client.patch(f"/api/profiles/{pid}", json={
        "name": "Updated Smoke Profile",
        "tags": ["smoke", "updated"],
        "notes": "Updated by smoke test",
    })
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "Updated Smoke Profile"
    assert updated["tags"] == ["smoke", "updated"]

    # LIST
    resp = await admin_client.get("/api/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(p["id"] == pid for p in data["profiles"])

    # LIST with filter
    resp = await admin_client.get("/api/profiles?tag=updated")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # DELETE
    resp = await admin_client.delete(f"/api/profiles/{pid}")
    assert resp.status_code == 200

    # Verify deleted
    resp = await admin_client.get(f"/api/profiles/{pid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_profile_name_uniqueness(admin_client: AsyncClient):
    """Cannot create two profiles with the same name."""
    await admin_client.post("/api/profiles", json={
        "name": "Unique Name",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })

    resp = await admin_client.post("/api/profiles", json={
        "name": "Unique Name",
        "target_os": "macos",
        "fingerprint_config": {"screen.width": 1440},
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_if_match_concurrency(admin_client: AsyncClient):
    """If-Match optimistic concurrency control."""
    resp = await admin_client.post("/api/profiles", json={
        "name": "Concurrency Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    # Update with correct version
    resp = await admin_client.patch(
        f"/api/profiles/{pid}",
        json={"notes": "v1"},
        headers={"If-Match": "0"},
    )
    assert resp.status_code == 200

    # Update with wrong version should fail
    resp = await admin_client.patch(
        f"/api/profiles/{pid}",
        json={"notes": "v2"},
        headers={"If-Match": "999"},
    )
    assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════
# 3. Lock Protocol
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lock_protocol(admin_client: AsyncClient):
    """Lock → Heartbeat → Unlock lifecycle."""
    # Create profile
    resp = await admin_client.post("/api/profiles", json={
        "name": "Lock Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    # LOCK
    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-A",
        "ttl_minutes": 5,
    })
    assert resp.status_code == 200, resp.text
    lock = resp.json()
    token = lock["lock_token"]
    assert lock["locked_by"] == "machine-A"
    assert lock["essential_data_version"] == 0
    assert len(token) > 10

    # HEARTBEAT
    resp = await admin_client.post(f"/api/profiles/{pid}/heartbeat", json={
        "lock_token": token,
        "machine_id": "machine-A",
    })
    assert resp.status_code == 200

    # HEARTBEAT with wrong token
    resp = await admin_client.post(f"/api/profiles/{pid}/heartbeat", json={
        "lock_token": "wrong-token",
        "machine_id": "machine-A",
    })
    assert resp.status_code == 403

    # LOCK by another machine (should fail — already locked)
    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-B",
        "ttl_minutes": 5,
    })
    assert resp.status_code == 409

    # UNLOCK
    resp = await admin_client.post(f"/api/profiles/{pid}/unlock", json={
        "lock_token": token,
        "machine_id": "machine-A",
    })
    assert resp.status_code == 200

    # Verify unlocked
    resp = await admin_client.get(f"/api/profiles/{pid}")
    assert resp.json()["locked_by"] is None


@pytest.mark.asyncio
async def test_force_unlock(admin_client: AsyncClient):
    """Admin can force-unlock any profile."""
    resp = await admin_client.post("/api/profiles", json={
        "name": "Force Unlock Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    # Lock it
    await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-stuck",
        "ttl_minutes": 120,
    })

    # Force unlock
    resp = await admin_client.post(f"/api/profiles/{pid}/force-unlock")
    assert resp.status_code == 200
    assert "machine-stuck" in resp.json()["message"]


# ══════════════════════════════════════════════════════════════════
# 4. Essential Data Upload/Download
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_essential_data_flow(admin_client: AsyncClient):
    """Upload → Download → Verify checksum → Version listing."""
    # Create + lock profile
    resp = await admin_client.post("/api/profiles", json={
        "name": "Essential Data Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "uploader",
        "ttl_minutes": 5,
    })
    token = resp.json()["lock_token"]

    # Upload essential data
    test_data = b"fake essential data for smoke test " + secrets.token_bytes(100)
    expected_checksum = hashlib.sha256(test_data).hexdigest()

    resp = await admin_client.post(
        f"/api/profiles/{pid}/essential-data",
        files={"file": ("essential.zip", test_data, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    assert info["version"] == 1
    assert info["size_bytes"] == len(test_data)
    assert info["checksum"] == expected_checksum

    # Download
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data")
    assert resp.status_code == 200
    assert resp.content == test_data
    assert resp.headers["x-checksum"] == expected_checksum
    assert resp.headers["x-version"] == "1"

    # Version listing
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1

    # Upload v2
    test_data_v2 = b"updated essential data v2 " + secrets.token_bytes(50)
    resp = await admin_client.post(
        f"/api/profiles/{pid}/essential-data",
        files={"file": ("essential.zip", test_data_v2, "application/zip")},
    )
    assert resp.json()["version"] == 2

    # Profile should show updated version
    resp = await admin_client.get(f"/api/profiles/{pid}")
    profile = resp.json()
    assert profile["essential_data_version"] == 2
    assert profile["essential_data_size_bytes"] == len(test_data_v2)

    # Download specific version
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data?version=1")
    assert resp.status_code == 200
    assert resp.content == test_data


@pytest.mark.asyncio
async def test_upload_requires_lock(admin_client: AsyncClient):
    """Cannot upload essential data without locking first."""
    resp = await admin_client.post("/api/profiles", json={
        "name": "No Lock Upload",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    resp = await admin_client.post(
        f"/api/profiles/{pid}/essential-data",
        files={"file": ("essential.zip", b"data", "application/zip")},
    )
    assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════
# 5. User Management
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_user_management(admin_client: AsyncClient, server_app):
    """Create → List → Rotate Key → Auth with new key → Delete."""
    # CREATE
    resp = await admin_client.post("/api/users", json={
        "username": "smoke-member",
        "label": "Smoke test member",
        "role": "member",
    })
    assert resp.status_code == 201, resp.text
    user = resp.json()
    uid = user["id"]
    member_key = user["api_key"]
    assert user["username"] == "smoke-member"
    assert user["role"] == "member"
    assert member_key is not None  # Key shown only on create

    # LIST
    resp = await admin_client.get("/api/users")
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert len(users) >= 2  # admin + member

    # Auth with member key
    transport = ASGITransport(app=server_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": member_key},
    ) as member_client:
        # Member can list profiles
        resp = await member_client.get("/api/profiles")
        assert resp.status_code == 200

        # Member CANNOT manage users
        resp = await member_client.get("/api/users")
        assert resp.status_code == 403

    # ROTATE KEY
    resp = await admin_client.post(f"/api/users/{uid}/rotate-key")
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != member_key

    # Old key should no longer work
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": member_key},
    ) as old_client:
        resp = await old_client.get("/api/profiles")
        assert resp.status_code == 401

    # New key should work
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": new_key},
    ) as new_client:
        resp = await new_client.get("/api/profiles")
        assert resp.status_code == 200

    # DELETE
    resp = await admin_client.delete(f"/api/users/{uid}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cannot_delete_self(admin_client: AsyncClient):
    """Admin cannot delete their own account."""
    # Get admin user ID
    resp = await admin_client.get("/api/users")
    admin_user = next(u for u in resp.json()["users"] if u["role"] == "admin")

    resp = await admin_client.delete(f"/api/users/{admin_user['id']}")
    assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════
# 6. Sync Service (collect + restore)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sync_service_roundtrip(tmp_path):
    """Collect essential data from a fake profile, restore to another dir."""
    from cfox_local.services.sync_service import (
        collect_essential_data,
        restore_essential_data,
        verify_checksum,
    )

    # Create fake profile directory
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "cookies.sqlite").write_bytes(b"cookie_data_123")
    (profile_dir / "places.sqlite").write_bytes(b"places_data_456")
    (profile_dir / "prefs.js").write_bytes(b"user_pref('key', 'value');")
    (profile_dir / "key4.db").write_bytes(b"key4_data")
    (profile_dir / "cache2").mkdir()
    (profile_dir / "cache2" / "big_cache.dat").write_bytes(b"x" * 1000)
    (profile_dir / "random_file.txt").write_bytes(b"should be skipped")

    # Collect
    zip_path, checksum, size = collect_essential_data(profile_dir)
    assert zip_path.exists()
    assert size > 0
    assert len(checksum) == 64
    assert verify_checksum(zip_path, checksum)

    # Restore
    restore_dir = tmp_path / "restored"
    count = restore_essential_data(zip_path, restore_dir, expected_checksum=checksum, clear_cache=True)
    assert count == 4  # cookies, places, prefs, key4
    assert (restore_dir / "cookies.sqlite").read_bytes() == b"cookie_data_123"
    assert (restore_dir / "places.sqlite").read_bytes() == b"places_data_456"
    assert (restore_dir / "prefs.js").read_bytes() == b"user_pref('key', 'value');"
    assert (restore_dir / "key4.db").read_bytes() == b"key4_data"
    assert not (restore_dir / "random_file.txt").exists()

    # Bad checksum should raise
    with pytest.raises(ValueError, match="Checksum mismatch"):
        restore_essential_data(zip_path, restore_dir, expected_checksum="bad" * 16)

    zip_path.unlink()


# ══════════════════════════════════════════════════════════════════
# 7. Storage Service (versioning + rotation)
# ══════════════════════════════════════════════════════════════════


def test_storage_versioning(tmp_path):
    """Test versioned storage with rotation."""
    from cfox_server.services.storage_service import StorageService

    svc = StorageService(tmp_path / "storage", max_versions=2)
    profile_id = "test-profile-id"

    # Save v1
    checksum1, size1 = svc.save(profile_id, b"data_v1", version=1)
    assert size1 == 7
    assert len(checksum1) == 64

    # Save v2
    svc.save(profile_id, b"data_v2_longer", version=2)

    # Save v3 (should rotate v1 out)
    svc.save(profile_id, b"data_v3", version=3)

    # Load
    assert svc.load(profile_id, 3) == b"data_v3"
    assert svc.load(profile_id, 2) == b"data_v2_longer"
    assert svc.load(profile_id, 1) is None  # Rotated out

    # List versions
    versions = svc.list_versions(profile_id)
    assert len(versions) == 2
    assert versions[0].version == 3  # Newest first
    assert versions[1].version == 2

    # Verify
    assert svc.verify(b"data_v3", hashlib.sha256(b"data_v3").hexdigest())
    assert not svc.verify(b"data_v3", "wrong_checksum")

    # Delete all
    svc.delete_profile(profile_id)
    assert svc.load(profile_id, 3) is None


# ══════════════════════════════════════════════════════════════════
# 8. Heartbeat Service State Machine
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_state_machine():
    """Test graduated response logic."""
    from cfox_local.services.heartbeat_service import HeartbeatEntry, HeartbeatService
    import time

    states_log = []

    async def mock_heartbeat(pid, token, mid):
        raise ConnectionError("Server down")

    async def on_lock_lost(pid):
        states_log.append(("lock_lost", pid))

    async def on_state_change(pid, old, new):
        states_log.append(("state", pid, old, new))

    svc = HeartbeatService(
        heartbeat_fn=mock_heartbeat,
        on_lock_lost=on_lock_lost,
        on_state_change=on_state_change,
    )

    svc.register("p1", "token1", "machine1")
    assert svc.active_count == 1

    # Manually set last_success far in the past to simulate failures
    entry = svc._entries["p1"]
    entry.last_success = time.monotonic() - 70  # 70s ago → should be "warn"
    await svc._send_heartbeat(entry)
    assert entry.state == "warn"

    entry.last_success = time.monotonic() - 160  # 160s → "critical"
    await svc._send_heartbeat(entry)
    assert entry.state == "critical"

    entry.last_success = time.monotonic() - 310  # 310s → "dead"
    await svc._send_heartbeat(entry)
    assert ("lock_lost", "p1") in states_log

    svc.unregister("p1")
    assert svc.active_count == 0


# ══════════════════════════════════════════════════════════════════
# 9. Upload Queue Dedup
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_queue_dedup():
    """Upload queue should dedup by profile_id (latest wins)."""
    from cfox_local.services.upload_queue import UploadQueue

    uploaded = []

    async def mock_upload(pid, path):
        await asyncio.sleep(0.05)  # Simulate upload time
        uploaded.append((pid, str(path)))
        return {"version": 1}

    queue = UploadQueue(upload_fn=mock_upload, max_concurrent=1)

    # Enqueue same profile multiple times
    queue.enqueue("p1", Path("/fake/v1.zip"))
    queue.enqueue("p1", Path("/fake/v2.zip"))  # Should replace v1 in pending
    queue.enqueue("p2", Path("/fake/p2.zip"))

    await queue.drain(timeout=5.0)
    await asyncio.sleep(0.5)  # Let tasks complete

    # p1 should have been uploaded (possibly twice due to re-queue)
    p1_uploads = [u for u in uploaded if u[0] == "p1"]
    p2_uploads = [u for u in uploaded if u[0] == "p2"]
    assert len(p1_uploads) >= 1
    assert len(p2_uploads) == 1


# ══════════════════════════════════════════════════════════════════
# 10. Rollback
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rollback(admin_client: AsyncClient):
    """Rollback essential data to a previous version."""
    # Create + lock
    resp = await admin_client.post("/api/profiles", json={
        "name": "Rollback Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]
    await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-A",
        "ttl_minutes": 5,
    })

    # Upload v1 and v2
    data_v1 = b"original data v1"
    data_v2 = b"updated data v2"

    await admin_client.post(
        f"/api/profiles/{pid}/essential-data",
        files={"file": ("e.zip", data_v1, "application/zip")},
    )
    await admin_client.post(
        f"/api/profiles/{pid}/essential-data",
        files={"file": ("e.zip", data_v2, "application/zip")},
    )

    # Current version should be v2
    resp = await admin_client.get(f"/api/profiles/{pid}")
    assert resp.json()["essential_data_version"] == 2

    # Rollback to v1
    resp = await admin_client.post(
        f"/api/profiles/{pid}/essential-data/rollback?version=1"
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 3  # New version created from v1 data

    # Download latest should be v1's data
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data")
    assert resp.content == data_v1
    assert resp.headers["x-version"] == "3"


# ══════════════════════════════════════════════════════════════════
# 11. Auth Middleware — hash_api_key
# ══════════════════════════════════════════════════════════════════


def test_hash_api_key():
    """API key hashing is deterministic SHA-256."""
    key = "my-secret-key"
    h1 = hash_api_key(key)
    h2 = hash_api_key(key)
    assert h1 == h2
    assert h1 == hashlib.sha256(key.encode()).hexdigest()
    assert hash_api_key("different") != h1


# ══════════════════════════════════════════════════════════════════
# 12. Delete locked profile should fail
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_delete_locked_profile(admin_client: AsyncClient):
    """Cannot delete a locked profile."""
    resp = await admin_client.post("/api/profiles", json={
        "name": "Locked Delete Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = resp.json()["id"]

    await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-X",
        "ttl_minutes": 5,
    })

    resp = await admin_client.delete(f"/api/profiles/{pid}")
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"].lower()
