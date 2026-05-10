# Camoufox Profiles — Testing Guide

> **Last updated:** 2026-05-11

---

## Overview

The testing infrastructure covers **3 layers**: unit tests, E2E integration tests, and browser automation tests.

### Test Summary

| Layer | Location | Tests | Status |
|-------|----------|-------|--------|
| **E2E** | `tests/e2e/` | 42 | ✅ 41 passed, 1 deselected |
| **Unit** | `tests/` | 3 files | ✅ |
| **Browser** | `tests/async/`, `browser-tests/` | varies | Manual |

---

## E2E Test Suites

### Suite 1: Server API (`test_server_api.py`)

Tests the `cfox-server` REST API using in-process ASGI transport.

| Test | Description |
|------|-------------|
| `test_profile_search_filter` | Profile search with keyword filtering |
| `test_profile_pagination` | Pagination with offset/limit |
| `test_lock_expired_relock` | Lock expiry + re-acquisition by another machine |
| `test_version_rotation` | Essential data version rotation (keeps last N) |

**Execution:** In-process via `httpx.ASGITransport` (no ports needed)

### Suite 2: Local API (`test_local_api.py`)

Tests the `cfox-local` REST API end-to-end.

| Test | Description |
|------|-------------|
| `test_local_info` | GET /api/info returns machine_id, hostname |
| `test_local_settings_get` | GET /api/settings returns current config |
| `test_local_settings_update_max_tags` | PUT /api/settings updates max_tags |
| `test_local_settings_base_dir` | Settings includes base_dir path |
| `test_local_settings_invalid` | Rejects invalid settings |
| `test_local_browse_dirs` | GET /api/settings/browse lists directories |
| `test_local_drives` | GET /api/settings/drives returns drive list |
| `test_local_profile_crud` | Create → Read → Update → Delete lifecycle |
| `test_local_profile_with_tags` | Profile creation with tags |
| `test_local_server_status` | Server status when disconnected |
| `test_local_sessions_empty` | Sessions list when no browsers running |
| `test_local_browser_launch_real` | Real browser launch *(real_browser marker)* |

**Execution:** In-process via `httpx.ASGITransport`

### Suite 3: Cloud Client (`test_cloud_client.py`)

Tests the `CloudClient` service against the server API.

| Test | Description |
|------|-------------|
| `test_cloud_connect_health` | Connect to server + health check |
| `test_cloud_connect_bad_url` | Graceful failure on bad URL |
| `test_cloud_profile_crud` | Remote profile create → read → update → delete |
| `test_cloud_lock_unlock` | Lock acquire + release cycle |
| `test_cloud_essential_roundtrip` | Upload + download essential data with checksum |
| `test_cloud_cache_invalidation` | Cache invalidation after write operations |
| `test_cloud_retry_on_timeout` | Retry behavior on network timeout |
| `test_cloud_api_error_no_retry` | No retry on 4xx API errors |

**Execution:** In-process; CloudClient connects to ASGI-hosted server

### Suite 4: UI Settings (`test_ui_settings.py`)

Tests the Settings page via a real subprocess server.

| Test | Description |
|------|-------------|
| `test_ui_settings_loads` | Settings page loads successfully |
| `test_ui_machine_id_display` | Machine ID displayed in UI |
| `test_ui_max_tags_edit` | Max tags setting can be edited |
| `test_ui_directory_browser` | Directory browser API works |
| `test_ui_cloud_section` | Cloud settings section visible |
| `test_ui_danger_zone_visible` | Danger zone section present |
| `test_ui_reset_confirm` | Reset requires confirmation |

**Execution:** Real subprocess on port `9600`; tests hit HTTP endpoints

### Suite 5: UI Profiles (`test_ui_profiles.py`)

Tests the Profiles page via a real subprocess server.

| Test | Description |
|------|-------------|
| `test_ui_profiles_empty` | Empty state when no profiles exist |
| `test_ui_create_profile` | Create a new profile via API |
| `test_ui_profile_card_info` | Profile card displays correct info |
| `test_ui_edit_profile_name` | Edit profile name via PUT |
| `test_ui_delete_profile` | Delete profile via API |
| `test_ui_sidebar_navigation` | Sidebar navigation between pages |

**Execution:** Real subprocess on port `9600`

### Suite 6: Cross-System (`test_cross_system.py`)

Tests interactions between cfox-local and cfox-server.

| Test | Description |
|------|-------------|
| `test_server_status_connected` | Server status reflects connection state |
| `test_server_connect_disconnect` | Connect → disconnect lifecycle |
| `test_cloud_launch_flow` | Lock → download → launch simulation |
| `test_heartbeat_integration` | Heartbeat service state tracking |
| `test_upload_queue_integration` | Upload queue dedup + processing |

**Execution:** In-process; both apps in same test process

---

## Test Infrastructure

### Fixtures (`conftest.py`)

```python
# In-process fixtures (fast, no ports)
@pytest.fixture
async def server_app():
    """cfox-server with in-memory SQLite"""

@pytest.fixture
async def admin_client(server_app):
    """Authenticated httpx client via ASGI transport"""

@pytest.fixture
async def local_app(tmp_path):
    """cfox-local with temp directory"""

@pytest.fixture
async def local_client(local_app):
    """httpx client for local server"""

# Subprocess fixture (for UI tests)
@pytest.fixture(scope="module")
def ui_server(tmp_path_factory):
    """Real cfox-local subprocess on port 9600
    - Launches with --no-browser --host 127.0.0.1 --port 9600
    - Waits for /api/info readiness
    - Kills process on teardown
    """
```

### Custom Markers

```python
# pytest markers registered in conftest.py
@pytest.mark.real_browser   # Requires Camoufox binary
@pytest.mark.ui             # Requires built UI + subprocess
```

### Configuration

```ini
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

---

## Running Tests

### Quick Commands

```bash
# All E2E tests (excluding real browser)
python -m pytest tests/e2e/ -v -m "not real_browser"

# API tests only (fast, ~5s)
python -m pytest tests/e2e/test_server_api.py tests/e2e/test_local_api.py tests/e2e/test_cloud_client.py -v

# UI tests only (requires built UI, ~7s)
cd cfox_ui && npm run build && cd ..
python -m pytest tests/e2e/test_ui_settings.py tests/e2e/test_ui_profiles.py -v

# Cross-system tests
python -m pytest tests/e2e/test_cross_system.py -v

# Full suite including real browser
python -m pytest tests/e2e/ -v

# Unit tests
python -m pytest tests/test_store.py tests/test_fingerprint.py tests/test_warmup.py -v
```

### Prerequisites

| Test Category | Requirements |
|---------------|-------------|
| API tests (Suite 1-3, 6) | Python + dev dependencies only |
| UI tests (Suite 4-5) | Built UI (`cd cfox_ui && npm run build`) |
| Real browser test | Camoufox binary installed |

### CI Environment

In CI where Camoufox binary is not available:

```bash
python -m pytest tests/e2e/ -v -m "not real_browser"
```

---

## Adding New Tests

### API Test Template

```python
@pytest.mark.asyncio
async def test_new_endpoint(local_client: httpx.AsyncClient):
    """Test description."""
    resp = await local_client.get("/api/your-endpoint")
    assert resp.status_code == 200
    data = resp.json()
    assert "expected_field" in data
```

### UI Test Template

```python
@pytest.mark.ui
def test_ui_feature(ui_server):
    """Test UI feature via API."""
    base = ui_server  # "http://127.0.0.1:9600"
    resp = httpx.get(f"{base}/api/your-endpoint")
    assert resp.status_code == 200
```

---

## Bugs Found During Testing

| Bug | Location | Root Cause | Fix |
|-----|----------|-----------|-----|
| GET deleted profile → 500 | `cfox_local/routes/profiles.py` | `ProfileNotFoundError` uncaught | Wrapped in try/except → 404 |
| Heartbeat test fails | `test_cross_system.py` | State is `"healthy"` not `"normal"` | Updated assertion |
| Lock test fails | `test_server_api.py` | `ASGITransport._app` → `.app` | Updated attribute access |
