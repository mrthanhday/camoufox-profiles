"""
Suite 3: CloudClient integration tests.

Tests the CloudClient class against a real cfox-server (ASGI transport).
Covers connect, CRUD, locking, essential data, caching, retry, and error handling.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from .conftest import ADMIN_KEY, create_server_profile


# ── Fixture: CloudClient connected to test server ────────────────


@pytest_asyncio.fixture
async def cloud_client(server_app):
    """CloudClient connected to the ASGI test server."""
    from cfox_local.services.cloud_client import CloudClient
    import httpx

    transport = ASGITransport(app=server_app)
    client = CloudClient(
        server_url="http://testserver",
        api_key=ADMIN_KEY,
        timeout=10.0,
        max_retries=2,
    )
    # Override internal client with ASGI transport
    client._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": ADMIN_KEY},
        timeout=10.0,
    )
    yield client
    await client.disconnect()


# ══════════════════════════════════════════════════════════════════
# 3.1 Connect & Health Check
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_connect_health(cloud_client):
    """CloudClient health check returns True when server is up."""
    assert cloud_client.is_connected
    result = await cloud_client.health_check()
    assert result is True


# ══════════════════════════════════════════════════════════════════
# 3.2 Connect with Bad URL
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_connect_bad_url():
    """CloudClient with unreachable server returns False."""
    from cfox_local.services.cloud_client import CloudClient

    client = CloudClient(
        server_url="http://localhost:19999",  # Not running
        api_key="fake-key",
        timeout=1.0,
        max_retries=1,
    )
    result = await client.connect()
    assert result is False
    await client.disconnect()


# ══════════════════════════════════════════════════════════════════
# 3.3 Profile CRUD via CloudClient
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_profile_crud(cloud_client):
    """Create → list → get → update → delete via CloudClient."""
    # Create
    profile = await cloud_client.create_profile({
        "name": "CC CRUD Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
        "tags": ["cc-test"],
    })
    pid = profile["id"]
    assert profile["name"] == "CC CRUD Test"

    # List
    result = await cloud_client.list_profiles(use_cache=False)
    assert any(p["id"] == pid for p in result["profiles"])

    # Get
    fetched = await cloud_client.get_profile(pid)
    assert fetched["id"] == pid
    assert fetched["name"] == "CC CRUD Test"

    # Update
    updated = await cloud_client.update_profile(pid, {"notes": "Updated via CC"})
    assert updated["notes"] == "Updated via CC"

    # Delete
    await cloud_client.delete_profile(pid)

    # Verify gone
    from cfox_local.services.cloud_client import CloudAPIError
    with pytest.raises(CloudAPIError) as exc_info:
        await cloud_client.get_profile(pid)
    assert exc_info.value.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 3.4 Lock / Unlock via CloudClient
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_lock_unlock(cloud_client):
    """Lock → heartbeat → unlock via CloudClient."""
    profile = await cloud_client.create_profile({
        "name": "CC Lock Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = profile["id"]

    # Lock
    lock = await cloud_client.lock_profile(pid, "cc-machine", ttl_minutes=5)
    token = lock["lock_token"]
    assert lock["locked_by"] == "cc-machine"

    # Heartbeat
    hb = await cloud_client.heartbeat(pid, token, "cc-machine")
    assert "Heartbeat accepted" in hb["message"]

    # Unlock
    ul = await cloud_client.unlock_profile(pid, token, "cc-machine")
    assert "unlocked" in ul["message"].lower()


# ══════════════════════════════════════════════════════════════════
# 3.5 Essential Data Roundtrip via CloudClient
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_essential_roundtrip(cloud_client, tmp_path):
    """Upload → download → verify via CloudClient."""
    profile = await cloud_client.create_profile({
        "name": "CC Essential Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })
    pid = profile["id"]

    # Lock first
    lock = await cloud_client.lock_profile(pid, "uploader", ttl_minutes=5)

    # Create test ZIP
    test_data = b"essential_data_roundtrip_" + secrets.token_bytes(50)
    expected_checksum = hashlib.sha256(test_data).hexdigest()
    upload_path = tmp_path / "upload.zip"
    upload_path.write_bytes(test_data)

    # Upload
    result = await cloud_client.upload_essential_data(pid, upload_path)
    assert result["version"] == 1
    assert result["checksum"] == expected_checksum

    # Download
    download_path = tmp_path / "download.zip"
    dl_info = await cloud_client.download_essential_data(pid, download_path)
    assert download_path.read_bytes() == test_data
    assert dl_info["checksum"] == expected_checksum
    assert dl_info["version"] == "1"


# ══════════════════════════════════════════════════════════════════
# 3.6 Cache Invalidation
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_cache_invalidation(cloud_client):
    """Profile list cache is invalidated after create/delete."""
    # Warm cache
    result1 = await cloud_client.list_profiles(use_cache=True)
    initial_count = result1["total"]

    # Create → should invalidate cache
    profile = await cloud_client.create_profile({
        "name": "Cache Test",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
    })

    # List again — should see the new profile
    result2 = await cloud_client.list_profiles(use_cache=True)
    assert result2["total"] == initial_count + 1

    # Delete → should invalidate cache
    await cloud_client.delete_profile(profile["id"])
    result3 = await cloud_client.list_profiles(use_cache=True)
    assert result3["total"] == initial_count


# ══════════════════════════════════════════════════════════════════
# 3.7 Retry on Timeout
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_retry_on_timeout(cloud_client):
    """Timeout triggers retry up to max_retries."""
    import httpx

    call_count = 0
    original_request = cloud_client._client.request

    async def flaky_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            raise httpx.ReadTimeout("Simulated timeout")
        return await original_request(*args, **kwargs)

    cloud_client._client.request = flaky_request

    # Should succeed on retry
    result = await cloud_client.health_check()
    assert result is True
    assert call_count == 2  # 1 fail + 1 success

    # Restore
    cloud_client._client.request = original_request


# ══════════════════════════════════════════════════════════════════
# 3.8 API Error — No Retry
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cloud_api_error_no_retry(cloud_client):
    """400/404 errors raise immediately without retrying."""
    from cfox_local.services.cloud_client import CloudAPIError

    with pytest.raises(CloudAPIError) as exc_info:
        await cloud_client.get_profile("nonexistent-id-12345")

    assert exc_info.value.status_code == 404
