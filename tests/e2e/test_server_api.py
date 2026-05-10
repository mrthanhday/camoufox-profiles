"""
Suite 1: Server API — additional edge-case tests.

Existing smoke tests (19) cover CRUD, auth, locks, data, users.
These tests add: search/filter, pagination, expired lock re-lock, version rotation.
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient

from .conftest import create_server_profile


# ══════════════════════════════════════════════════════════════════
# 1.5 Profile Search & Filter
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_profile_search_filter(admin_client: AsyncClient):
    """Search by name, filter by tag and target_os."""
    # Create diverse profiles
    await admin_client.post("/api/profiles", json={
        "name": "SearchMe Alpha",
        "target_os": "windows",
        "fingerprint_config": {"screen.width": 1920},
        "tags": ["search-test", "alpha"],
    })
    await admin_client.post("/api/profiles", json={
        "name": "SearchMe Beta",
        "target_os": "macos",
        "fingerprint_config": {"screen.width": 1440},
        "tags": ["search-test", "beta"],
    })

    # Search by name substring
    resp = await admin_client.get("/api/profiles?search=Alpha")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all("Alpha" in p["name"] for p in data["profiles"])

    # Filter by tag
    resp = await admin_client.get("/api/profiles?tag=beta")
    assert resp.status_code == 200
    assert all("beta" in p["tags"] for p in resp.json()["profiles"])

    # Filter by target_os
    resp = await admin_client.get("/api/profiles?target_os=macos")
    assert resp.status_code == 200
    assert all(p["target_os"] == "macos" for p in resp.json()["profiles"])


# ══════════════════════════════════════════════════════════════════
# 1.6 Profile Pagination
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_profile_pagination(admin_client: AsyncClient):
    """Create 5 profiles, paginate with limit=2 offset=2."""
    for i in range(5):
        await admin_client.post("/api/profiles", json={
            "name": f"Paginate Profile {i}",
            "target_os": "windows",
            "fingerprint_config": {"screen.width": 1920},
            "tags": ["pagination-test"],
        })

    # Page 1: limit=2, offset=0
    resp = await admin_client.get("/api/profiles?tag=pagination-test&limit=2&offset=0")
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1["profiles"]) == 2
    assert page1["total"] >= 5

    # Page 2: limit=2, offset=2
    resp = await admin_client.get("/api/profiles?tag=pagination-test&limit=2&offset=2")
    assert resp.status_code == 200
    page2 = resp.json()
    assert len(page2["profiles"]) == 2

    # Pages should be different
    p1_ids = {p["id"] for p in page1["profiles"]}
    p2_ids = {p["id"] for p in page2["profiles"]}
    assert p1_ids.isdisjoint(p2_ids)


# ══════════════════════════════════════════════════════════════════
# 1.9 Lock Expired Re-lock
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lock_expired_relock(admin_client: AsyncClient):
    """When lock expires, another machine can re-lock."""
    profile = await create_server_profile(admin_client, "Expired Lock Test")
    pid = profile["id"]

    # Lock by machine A with very short TTL
    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-A",
        "ttl_minutes": 5,
    })
    assert resp.status_code == 200

    # Manually expire the lock by setting lock_expires_at to past
    from camoufox_profiles.models_sa import ProfileModel
    from sqlalchemy import update
    from camoufox_profiles.models import _utcnow
    from datetime import timedelta

    async with admin_client._transport.app.state.session_factory() as session:
        past = (_utcnow() - timedelta(hours=1)).isoformat()
        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == pid)
            .values(lock_expires_at=past)
        )
        await session.commit()

    # Machine B should be able to lock now (expired lock)
    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "machine-B",
        "ttl_minutes": 5,
    })
    assert resp.status_code == 200
    lock = resp.json()
    assert lock["locked_by"] == "machine-B"
    # Should report previous lock info
    assert lock["previous_lock"] is not None
    assert lock["previous_lock"]["locked_by"] == "machine-A"


# ══════════════════════════════════════════════════════════════════
# 1.12 Version Rotation
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_version_rotation(admin_client: AsyncClient):
    """Upload 4 versions with max_versions=3; version 1 should be rotated out."""
    profile = await create_server_profile(admin_client, "Rotation Test")
    pid = profile["id"]

    # Lock for upload
    resp = await admin_client.post(f"/api/profiles/{pid}/lock", json={
        "machine_id": "uploader",
        "ttl_minutes": 5,
    })
    assert resp.status_code == 200

    # Upload 4 versions
    for i in range(1, 5):
        data = f"version_{i}_data".encode() + secrets.token_bytes(20)
        resp = await admin_client.post(
            f"/api/profiles/{pid}/essential-data",
            files={"file": ("essential.zip", data, "application/zip")},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == i

    # List versions — should only have 3 (max_versions=3)
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 3
    version_nums = [v["version"] for v in versions]
    assert 1 not in version_nums  # Rotated out
    assert 4 in version_nums
    assert 3 in version_nums
    assert 2 in version_nums

    # Trying to download v1 should fail
    resp = await admin_client.get(f"/api/profiles/{pid}/essential-data?version=1")
    assert resp.status_code == 404
