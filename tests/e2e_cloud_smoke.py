"""
E2E Smoke Test: Cloud Integration

Tests the full stack:
  cfox_server (port 8700, SQLite) ←→ cfox_local (port 7600) ←→ API calls

Test flow:
  1. Start cfox_server with SQLite (no Postgres needed)
  2. Start cfox_local (isolated config — no auto-connect)
  3. Connect cfox_local to cfox_server via Settings API
  4. Create a cloud profile via cfox_local
  5. List profiles — verify cloud profile appears
  6. Update the cloud profile
  7. Verify update persisted
  8. Delete the cloud profile
  9. Verify deletion
  10. Disconnect
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

# ── Config ───────────────────────────────────────────────────────
SERVER_PORT = 8710  # Use different port to avoid conflicts
LOCAL_PORT = 7610
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
LOCAL_URL = f"http://127.0.0.1:{LOCAL_PORT}"
ADMIN_API_KEY = "test-admin-key-12345"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("e2e")


# ── Process management ───────────────────────────────────────────

def start_server(tmp_dir: Path) -> subprocess.Popen:
    """Start cfox_server with SQLite backend."""
    db_path = tmp_dir / "server.db"
    storage_dir = tmp_dir / "server_storage"
    storage_dir.mkdir(exist_ok=True)

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "STORAGE_DIR": str(storage_dir),
        "HOST": "127.0.0.1",
        "PORT": str(SERVER_PORT),
        "ADMIN_API_KEY": ADMIN_API_KEY,
        "LOCK_TTL_MINUTES": "120",
        "MAX_VERSIONS": "3",
    }

    log.info("Starting cfox_server on :%d (SQLite: %s)", SERVER_PORT, db_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "cfox_server"],
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def start_local(tmp_dir: Path) -> subprocess.Popen:
    """Start cfox_local with isolated config (no auto-connect)."""
    base_dir = tmp_dir / "local_profiles"
    base_dir.mkdir(exist_ok=True)

    # Create an isolated config directory to prevent reading ~/.cfox/config.json
    config_dir = tmp_dir / "cfox_home" / ".cfox"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Write minimal config WITHOUT cloud credentials
    config = {
        "host": "127.0.0.1",
        "port": LOCAL_PORT,
        "base_dir": str(base_dir),
    }
    (config_dir / "config.json").write_text(json.dumps(config))
    (config_dir / "machine_id").write_text("test-machine-e2e")

    env = {
        **os.environ,
        # Override USERPROFILE/HOME so Settings.load() reads our isolated config
        "USERPROFILE": str(tmp_dir / "cfox_home"),
        "HOME": str(tmp_dir / "cfox_home"),
        # Also set explicit env vars as double-safety
        "CFOX_HOST": "127.0.0.1",
        "CFOX_PORT": str(LOCAL_PORT),
        "CFOX_BASE_DIR": str(base_dir),
    }

    log.info("Starting cfox_local on :%d (isolated home: %s)", LOCAL_PORT, tmp_dir / "cfox_home")
    proc = subprocess.Popen(
        [sys.executable, "-m", "cfox_local", "--no-browser"],
        env=env,
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


async def wait_for_service(url: str, name: str, timeout: int = 20) -> bool:
    """Wait for a service to become healthy."""
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    log.info("✅ %s is UP (%s)", name, url)
                    return True
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(0.5)
    log.error("❌ %s failed to start within %ds", name, timeout)
    return False


def dump_proc_output(proc: Optional[subprocess.Popen], name: str, max_lines: int = 30):
    """Read and log process output for debugging."""
    if proc and proc.stdout:
        try:
            # Non-blocking read
            import msvcrt
            import ctypes
            # Fallback: just try readline with a short timeout
        except ImportError:
            pass
        # For debugging, we won't try to read non-blocking on Windows
        log.info("  (Cannot dump %s output non-blocking on Windows)", name)


def kill_proc(proc: Optional[subprocess.Popen], name: str):
    """Kill a process gracefully."""
    if proc and proc.poll() is None:
        log.info("Stopping %s (PID %d)...", name, proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.info("  → %s stopped", name)


# ── Test assertions ──────────────────────────────────────────────

class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def check(self, label: str, condition: bool, detail: str = ""):
        if condition:
            log.info("  ✅ PASS: %s", label)
            self.passed += 1
        else:
            msg = f"  ❌ FAIL: {label}" + (f" — {detail}" if detail else "")
            log.error(msg)
            self.failed += 1
            self.errors.append(msg)

    def summary(self):
        total = self.passed + self.failed
        log.info("=" * 60)
        if self.failed == 0:
            log.info("🎉 ALL %d TESTS PASSED", total)
        else:
            log.error("💥 %d/%d FAILED", self.failed, total)
            for err in self.errors:
                log.error("   %s", err)
        log.info("=" * 60)
        return self.failed == 0


# ── Main test flow ───────────────────────────────────────────────

async def run_tests():
    """Execute the E2E cloud integration smoke test."""
    result = TestResult()
    client = httpx.AsyncClient(base_url=LOCAL_URL, timeout=60)

    try:
        # ── 1. Server health (direct) ────────────────────────────
        log.info("─── Test 1: Server health check (direct) ───")
        async with httpx.AsyncClient(timeout=5) as srv_client:
            resp = await srv_client.get(f"{SERVER_URL}/api/health")
            result.check("Server /api/health returns 200", resp.status_code == 200)
            data = resp.json()
            result.check("Server status is 'ok'", data.get("status") == "ok")

        # ── 2. Local health ──────────────────────────────────────
        log.info("─── Test 2: Local service health ───")
        resp = await client.get("/api/info")
        result.check("Local /api/info returns 200", resp.status_code == 200)
        info = resp.json()
        log.info("  → Machine ID: %s, Version: %s", info.get("machine_id"), info.get("version"))

        # ── 3. Initial state — no cloud connection ───────────────
        log.info("─── Test 3: Initial cloud status (disconnected) ───")
        resp = await client.get("/api/server/status")
        data = resp.json()
        log.info("  → Status: %s", json.dumps(data))
        result.check("Cloud initially not connected", data["connected"] is False)

        # ── 4. List profiles — local only ────────────────────────
        log.info("─── Test 4: List profiles (local only) ───")
        resp = await client.get("/api/profiles")
        data = resp.json()
        result.check("Profiles endpoint returns 200", resp.status_code == 200)
        result.check("server_connected is false", data["server_connected"] is False)
        initial_count = len(data["profiles"])
        log.info("  → Initial local profiles: %d", initial_count)

        # ── 5. Configure cloud settings via Settings API ─────────
        log.info("─── Test 5: Configure cloud settings ───")
        resp = await client.put("/api/settings", json={
            "server_url": SERVER_URL,
            "server_api_key": ADMIN_API_KEY,
        })
        result.check("Settings update returns 200", resp.status_code == 200,
                     f"status={resp.status_code}, body={resp.text[:300]}")
        if resp.status_code == 200:
            settings_data = resp.json()
            result.check("Settings has server_url", settings_data.get("server_url") == SERVER_URL)
            log.info("  → Cloud enabled: %s", settings_data.get("cloud_enabled"))

        # ── 6. Check cloud status after settings update ──────────
        log.info("─── Test 6: Cloud status after settings ───")
        # Settings update should auto-connect
        resp = await client.get("/api/server/status")
        data = resp.json()
        log.info("  → Status after settings: %s", json.dumps(data))
        auto_connected = data.get("connected", False)

        if not auto_connected:
            # Manually connect if settings didn't auto-connect
            log.info("  → Auto-connect didn't happen, trying manual connect...")
            resp = await client.post("/api/server/connect")
            data = resp.json()
            log.info("  → Connect response: %s", json.dumps(data))

        resp = await client.get("/api/server/status")
        data = resp.json()
        result.check("Server connected", data["connected"] is True,
                     json.dumps(data))
        result.check("Server healthy", data.get("healthy") is True,
                     json.dumps(data))

        # ── 7. Create a cloud profile ────────────────────────────
        log.info("─── Test 7: Create cloud profile ───")
        cloud_profile_data = {
            "name": "e2e-cloud-test-profile",
            "os": "windows",
            "tags": ["e2e", "smoke-test"],
            "notes": "Created by E2E smoke test",
            "source": "cloud",
        }
        resp = await client.post("/api/profiles", json=cloud_profile_data)
        log.info("  → Create response status: %d", resp.status_code)
        log.info("  → Create response body: %s", resp.text[:500])
        result.check("Cloud profile created (201)", resp.status_code == 201,
                     f"status={resp.status_code}, body={resp.text[:300]}")

        cloud_id = None
        if resp.status_code == 201:
            cloud_profile = resp.json()
            cloud_id = cloud_profile["id"]
            log.info("  → Created profile: id=%s, name=%s, source=%s",
                     cloud_id, cloud_profile.get("name"), cloud_profile.get("source"))
            result.check("Profile has source='cloud'",
                         cloud_profile.get("source") == "cloud",
                         f"actual source={cloud_profile.get('source')}")
            result.check("Profile name matches", cloud_profile["name"] == "e2e-cloud-test-profile")
            result.check("Profile has tags", cloud_profile.get("tags") == ["e2e", "smoke-test"])

        # ── 8. (SKIPPED) Create local profile ────────────────────
        # Local profile creation involves fingerprint generation (60+ seconds)
        # and is out of scope for cloud integration testing.
        log.info("─── Test 8: Create local profile (SKIPPED — fingerprint gen too slow) ───")
        local_id = None  # Not created

        # ── 9. List profiles — should have cloud ─────────────────
        log.info("─── Test 9: List profiles (with cloud) ───")
        resp = await client.get("/api/profiles")
        data = resp.json()
        all_profiles = data["profiles"]
        log.info("  → server_connected: %s", data["server_connected"])

        cloud_profiles = [p for p in all_profiles if p.get("source") == "cloud"]
        local_profiles = [p for p in all_profiles if p.get("source") == "local"]
        log.info("  → Total: %d (local=%d, cloud=%d)",
                 len(all_profiles), len(local_profiles), len(cloud_profiles))
        if cloud_profiles:
            log.info("  → First cloud profile: %s", json.dumps(cloud_profiles[0], indent=2)[:300])

        result.check("server_connected is true in list", data["server_connected"] is True)
        result.check("At least 1 cloud profile in list", len(cloud_profiles) >= 1)

        if cloud_id:
            found = any(p["id"] == cloud_id for p in cloud_profiles)
            result.check("Created cloud profile found in list", found)

        # ── 10. Get cloud profile by ID ──────────────────────────
        if cloud_id:
            log.info("─── Test 10: Get cloud profile by ID ───")
            resp = await client.get(f"/api/profiles/{cloud_id}", params={"source": "cloud"})
            log.info("  → GET response: status=%d body=%s", resp.status_code, resp.text[:300])
            result.check("Get cloud profile returns 200", resp.status_code == 200,
                         f"status={resp.status_code}, body={resp.text[:200]}")
            if resp.status_code == 200:
                p = resp.json()
                result.check("Fetched profile name matches", p["name"] == "e2e-cloud-test-profile")
                result.check("Fetched profile source is cloud", p.get("source") == "cloud")

        # ── 11. Update cloud profile ─────────────────────────────
        if cloud_id:
            log.info("─── Test 11: Update cloud profile ───")
            resp = await client.put(
                f"/api/profiles/{cloud_id}",
                params={"source": "cloud"},
                json={"name": "e2e-cloud-UPDATED", "notes": "Updated by E2E test"},
            )
            log.info("  → PUT response: status=%d body=%s", resp.status_code, resp.text[:300])
            result.check("Update cloud profile returns 200", resp.status_code == 200,
                         f"status={resp.status_code}, body={resp.text[:200]}")
            if resp.status_code == 200:
                updated = resp.json()
                result.check("Updated name matches", updated["name"] == "e2e-cloud-UPDATED")
                result.check("Updated notes matches", updated.get("notes") == "Updated by E2E test")

        # ── 12. Verify update persisted (re-fetch) ───────────────
        if cloud_id:
            log.info("─── Test 12: Verify cloud update persisted ───")
            resp = await client.get(f"/api/profiles/{cloud_id}", params={"source": "cloud"})
            if resp.status_code == 200:
                p = resp.json()
                result.check("Re-fetched name is updated", p["name"] == "e2e-cloud-UPDATED")
                result.check("Re-fetched notes is updated", p.get("notes") == "Updated by E2E test")

        # ── 13. Delete cloud profile ─────────────────────────────
        if cloud_id:
            log.info("─── Test 13: Delete cloud profile ───")
            resp = await client.delete(f"/api/profiles/{cloud_id}", params={"source": "cloud"})
            log.info("  → DELETE response: status=%d body=%s", resp.status_code, resp.text[:200])
            result.check("Delete cloud profile returns 200 or 204",
                         resp.status_code in (200, 204),
                         f"status={resp.status_code}")

        # ── 14. Verify cloud profile gone ────────────────────────
        if cloud_id:
            log.info("─── Test 14: Verify cloud profile deleted ───")
            resp = await client.get(f"/api/profiles/{cloud_id}", params={"source": "cloud"})
            result.check("Deleted cloud profile returns 404", resp.status_code == 404,
                         f"status={resp.status_code}")

            resp = await client.get("/api/profiles")
            all_profiles = resp.json()["profiles"]
            found = any(p["id"] == cloud_id for p in all_profiles)
            result.check("Deleted profile not in list", not found)

        # ── 15. Disconnect from cloud ────────────────────────────
        log.info("─── Test 15: Disconnect from cloud ───")
        resp = await client.post("/api/server/disconnect")
        data = resp.json()
        result.check("Disconnect returns connected=false", data["connected"] is False)

        resp = await client.get("/api/server/status")
        data = resp.json()
        result.check("Server status shows disconnected", data["connected"] is False)

        # ── 16. List profiles after disconnect ───────────────────
        log.info("─── Test 16: List profiles after disconnect ───")
        resp = await client.get("/api/profiles")
        data = resp.json()
        result.check("server_connected false after disconnect", data["server_connected"] is False)
        cloud_in_list = [p for p in data["profiles"] if p.get("source") == "cloud"]
        result.check("No cloud profiles after disconnect", len(cloud_in_list) == 0)

    except Exception as e:
        log.error("💥 Test execution error: %s", e, exc_info=True)
        result.check("No unhandled exceptions", False, str(e))
    finally:
        await client.aclose()

    return result


async def main():
    """Orchestrate the full E2E test run."""
    log.info("=" * 60)
    log.info("🚀 E2E Cloud Integration Smoke Test")
    log.info("=" * 60)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cfox_e2e_"))
    log.info("Temp directory: %s", tmp_dir)

    server_proc = None
    local_proc = None

    try:
        # Start services
        server_proc = start_server(tmp_dir)
        await asyncio.sleep(2)

        if server_proc.poll() is not None:
            stdout = server_proc.stdout.read() if server_proc.stdout else ""
            log.error("Server process exited immediately! Output:\n%s", stdout)
            sys.exit(1)

        local_proc = start_local(tmp_dir)
        await asyncio.sleep(2)

        if local_proc.poll() is not None:
            stdout = local_proc.stdout.read() if local_proc.stdout else ""
            log.error("Local process exited immediately! Output:\n%s", stdout)
            sys.exit(1)

        # Wait for both services
        server_ok = await wait_for_service(f"{SERVER_URL}/api/health", "cfox_server")
        local_ok = await wait_for_service(f"{LOCAL_URL}/api/info", "cfox_local")

        if not server_ok or not local_ok:
            log.error("Services failed to start, aborting.")
            sys.exit(1)

        # Run tests
        result = await run_tests()
        success = result.summary()
        sys.exit(0 if success else 1)

    finally:
        kill_proc(local_proc, "cfox_local")
        kill_proc(server_proc, "cfox_server")
        log.info("Temp dir preserved at: %s", tmp_dir)


if __name__ == "__main__":
    asyncio.run(main())
