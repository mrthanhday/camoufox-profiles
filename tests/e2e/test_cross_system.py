"""
Suite 6: Cross-system integration tests.

Tests that combine cfox-local and cfox-server working together:
server status, connect/disconnect, cloud launch flow, heartbeat,
and upload queue integration.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from .conftest import ADMIN_KEY, create_server_profile


# ══════════════════════════════════════════════════════════════════
# 6.1 Server Status — Connected
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_server_status_connected(server_app, tmp_path):
    """cfox-local with cloud config reports connected status."""
    from cfox_local.app import create_app
    from cfox_local.config import Settings
    from cfox_local.services.cloud_client import CloudClient
    import httpx

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    settings = Settings(
        host="127.0.0.1",
        port=9600,
        base_dir=profiles_dir,
        machine_id="status-test-machine",
        server_url="http://testserver",
        server_api_key=ADMIN_KEY,
    )
    app = create_app(settings)

    # Manually inject a connected cloud client
    transport = ASGITransport(app=server_app)
    cloud_client = CloudClient(
        server_url="http://testserver",
        api_key=ADMIN_KEY,
    )
    cloud_client._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": ADMIN_KEY},
        timeout=10.0,
    )

    async with app.router.lifespan_context(app):
        app.state.cloud_client = cloud_client

        local_transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=local_transport,
            base_url="http://testlocal",
        ) as client:
            resp = await client.get("/api/server/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["cloud_enabled"] is True
            assert data["connected"] is True

        await cloud_client.disconnect()


# ══════════════════════════════════════════════════════════════════
# 6.2 Server Connect / Disconnect
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_server_connect_disconnect(local_client: AsyncClient):
    """POST /api/server/connect without config → error."""
    # Since local fixture has no cloud config, connect should fail
    resp = await local_client.post("/api/server/connect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    assert "not configured" in data.get("error", "").lower()

    # Disconnect (no-op when not connected)
    resp = await local_client.post("/api/server/disconnect")
    assert resp.status_code == 200
    assert resp.json()["connected"] is False


# ══════════════════════════════════════════════════════════════════
# 6.3 Cloud Launch Flow (simulated)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_launch_flow(server_app, tmp_path):
    """Simulate cloud launch: lock → download → (no browser) → upload → unlock."""
    from cfox_local.services.cloud_client import CloudClient
    from cfox_local.services.sync_service import collect_essential_data, restore_essential_data
    import httpx

    transport = ASGITransport(app=server_app)
    client = CloudClient(
        server_url="http://testserver",
        api_key=ADMIN_KEY,
    )
    client._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": ADMIN_KEY},
        timeout=10.0,
    )

    try:
        # Create profile on server
        profile = await client.create_profile({
            "name": "Launch Flow Test",
            "target_os": "windows",
            "fingerprint_config": {"screen.width": 1920},
        })
        pid = profile["id"]

        # Step 1: Lock
        lock = await client.lock_profile(pid, "launch-machine", ttl_minutes=5)
        token = lock["lock_token"]
        assert lock["locked_by"] == "launch-machine"

        # Step 2: Upload initial essential data
        fake_profile_dir = tmp_path / "fake_profile"
        fake_profile_dir.mkdir()
        (fake_profile_dir / "cookies.sqlite").write_bytes(b"cookie_v1")
        (fake_profile_dir / "places.sqlite").write_bytes(b"places_v1")

        zip_path, checksum, size = collect_essential_data(fake_profile_dir)
        upload_result = await client.upload_essential_data(pid, zip_path)
        assert upload_result["version"] == 1
        zip_path.unlink()

        # Step 3: Download and restore
        download_path = tmp_path / "downloaded.zip"
        dl_info = await client.download_essential_data(pid, download_path)
        assert dl_info["checksum"] == checksum

        restore_dir = tmp_path / "restored"
        count = restore_essential_data(download_path, restore_dir, expected_checksum=checksum)
        assert count >= 2
        assert (restore_dir / "cookies.sqlite").read_bytes() == b"cookie_v1"

        # Step 4: Simulate session end — upload updated data
        (fake_profile_dir / "cookies.sqlite").write_bytes(b"cookie_v2_updated")
        zip_v2, checksum_v2, _ = collect_essential_data(fake_profile_dir)
        upload_v2 = await client.upload_essential_data(pid, zip_v2)
        assert upload_v2["version"] == 2
        zip_v2.unlink()

        # Step 5: Unlock
        unlock = await client.unlock_profile(pid, token, "launch-machine")
        assert "unlocked" in unlock["message"].lower()

        # Verify profile is unlocked and has v2
        fetched = await client.get_profile(pid)
        assert fetched["locked_by"] is None
        assert fetched["essential_data_version"] == 2

    finally:
        await client.disconnect()


# ══════════════════════════════════════════════════════════════════
# 6.4 Heartbeat Integration
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_integration():
    """HeartbeatService registers, tracks state, and unregisters."""
    from cfox_local.services.heartbeat_service import HeartbeatService

    events = []

    async def mock_hb(pid, token, mid):
        # Succeed
        return {"message": "ok"}

    async def on_lost(pid):
        events.append(("lost", pid))

    async def on_change(pid, old, new):
        events.append(("change", pid, old, new))

    svc = HeartbeatService(
        heartbeat_fn=mock_hb,
        on_lock_lost=on_lost,
        on_state_change=on_change,
    )

    # Register
    svc.register("p1", "token1", "machine1")
    svc.register("p2", "token2", "machine2")
    assert svc.active_count == 2

    # Send successful heartbeat
    entry = svc._entries["p1"]
    await svc._send_heartbeat(entry)
    assert entry.state == "healthy"
    assert entry.consecutive_failures == 0

    # Unregister
    svc.unregister("p1")
    assert svc.active_count == 1
    svc.unregister("p2")
    assert svc.active_count == 0


# ══════════════════════════════════════════════════════════════════
# 6.5 Upload Queue Integration
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_upload_queue_integration(tmp_path):
    """Upload queue delivers all files to server."""
    from cfox_local.services.upload_queue import UploadQueue

    delivered = []

    async def mock_upload(pid, path):
        await asyncio.sleep(0.01)
        delivered.append({"pid": pid, "data": Path(path).read_bytes()})
        return {"version": len(delivered)}

    queue = UploadQueue(upload_fn=mock_upload, max_concurrent=2)

    # Create test files
    for i in range(3):
        p = tmp_path / f"profile_{i}.zip"
        p.write_bytes(f"data_{i}".encode())
        queue.enqueue(f"profile_{i}", p)

    await queue.drain(timeout=10.0)
    await asyncio.sleep(1.0)

    assert len(delivered) == 3
    pids = {d["pid"] for d in delivered}
    assert pids == {"profile_0", "profile_1", "profile_2"}
