"""
Shared fixtures for E2E tests.

Provides both cfox-server and cfox-local apps running in-process via ASGI
transport. No real ports are opened for API tests.

UI tests (Suites 4-5) start cfox-local as a real subprocess on port 9600
and use browser_subagent to interact with the served Web UI.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ── Pytest custom markers ────────────────────────────────────────

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "real_browser: requires real Camoufox binary to be available"
    )
    config.addinivalue_line(
        "markers", "ui: requires built UI and real subprocess server"
    )

# ── Constants ────────────────────────────────────────────────────
ADMIN_KEY = "e2e-admin-key-secret-12345"
E2E_SERVER_PORT = 9700
E2E_LOCAL_PORT = 9600


# ══════════════════════════════════════════════════════════════════
# cfox-server fixtures
# ══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def server_app(tmp_path):
    """Create a cfox-server app with SQLite backend for E2E testing."""
    from cfox_server.app import create_app
    from cfox_server.config import ServerSettings

    settings = ServerSettings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'e2e_server.db'}",
        storage_dir=tmp_path / "storage",
        admin_api_key=ADMIN_KEY,
        host="127.0.0.1",
        port=E2E_SERVER_PORT,
        lock_ttl_minutes=5,
        lock_cleanup_interval_seconds=9999,  # Disable auto-cleanup
        max_versions=3,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def admin_client(server_app):
    """HTTP client authenticated as admin against cfox-server."""
    transport = ASGITransport(app=server_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": ADMIN_KEY},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def anon_client(server_app):
    """HTTP client with no authentication."""
    transport = ASGITransport(app=server_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


# ══════════════════════════════════════════════════════════════════
# cfox-local fixtures
# ══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def local_app(tmp_path):
    """Create a cfox-local app with temp base_dir (no cloud)."""
    from cfox_local.app import create_app
    from cfox_local.config import Settings

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    settings = Settings(
        host="127.0.0.1",
        port=E2E_LOCAL_PORT,
        base_dir=profiles_dir,
        machine_id="e2e-machine-001",
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def local_client(local_app):
    """HTTP client for cfox-local."""
    transport = ASGITransport(app=local_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testlocal",
    ) as client:
        yield client


# ══════════════════════════════════════════════════════════════════
# Connected fixtures (cfox-local + cfox-server)
# ══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def connected_local_app(tmp_path, server_app):
    """cfox-local app connected to cfox-server (via ASGI mock)."""
    from cfox_local.app import create_app
    from cfox_local.config import Settings

    profiles_dir = tmp_path / "local_profiles"
    profiles_dir.mkdir()

    settings = Settings(
        host="127.0.0.1",
        port=E2E_LOCAL_PORT,
        base_dir=profiles_dir,
        machine_id="e2e-connected-machine",
        server_url=f"http://127.0.0.1:{E2E_SERVER_PORT}",
        server_api_key=ADMIN_KEY,
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def connected_local_client(connected_local_app):
    """HTTP client for cloud-connected cfox-local."""
    transport = ASGITransport(app=connected_local_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testlocal",
    ) as client:
        yield client


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════


async def create_server_profile(client: AsyncClient, name: str = "E2E Profile") -> dict:
    """Helper to create a profile on cfox-server."""
    resp = await client.post("/api/profiles", json={
        "name": name,
        "target_os": "windows",
        "fingerprint_config": {
            "navigator.userAgent": "Mozilla/5.0 (Windows NT 10.0) Firefox/130.0",
            "screen.width": 1920,
        },
        "tags": ["e2e"],
    })
    assert resp.status_code == 201, f"Failed to create profile: {resp.text}"
    return resp.json()


async def create_local_profile(client: AsyncClient, name: str = "E2E Local") -> dict:
    """Helper to create a profile on cfox-local."""
    resp = await client.post("/api/profiles", json={
        "name": name,
        "os": "windows",
        "tags": ["e2e"],
    })
    assert resp.status_code == 201, f"Failed to create local profile: {resp.text}"
    return resp.json()


# ══════════════════════════════════════════════════════════════════
# UI Test Fixtures (Suites 4-5)
# ══════════════════════════════════════════════════════════════════


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    """Block until server responds to GET /api/info, or timeout."""
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def ui_server(tmp_path_factory):
    """
    Start cfox-local as a real subprocess for UI browser tests.

    Requires: `npm run build` in cfox_ui/ (so static files are served).
    Yields the base URL (http://localhost:9600).
    Terminates the server on teardown.
    """
    tmp = tmp_path_factory.mktemp("ui_profiles")
    profiles_dir = tmp / "profiles"
    profiles_dir.mkdir()

    env = os.environ.copy()
    env["CFOX_BASE_DIR"] = str(profiles_dir)
    env["CFOX_PORT"] = str(E2E_LOCAL_PORT)
    env["CFOX_HOST"] = "127.0.0.1"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "cfox_local",
            "--host", "127.0.0.1",
            "--port", str(E2E_LOCAL_PORT),
            "--base-dir", str(profiles_dir),
            "--no-browser",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent.parent),  # repo root
    )

    base_url = f"http://127.0.0.1:{E2E_LOCAL_PORT}"
    if not _wait_for_server(f"{base_url}/api/info"):
        proc.terminate()
        proc.wait(timeout=5)
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        pytest.fail(f"cfox-local did not start within 30s.\nStderr:\n{stderr}")

    yield base_url

    # Teardown
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

