# Test Strategy - Cloud Sync (Phase 3)

Version: 1.0 | Date: 2026-05-09 | Target: cfox-server + cfox-local cloud integration

---

## 1. Test Sandbox Architecture

### 1.1 Overview

Dedicated sandbox environment mo phong full stack cloud deployment.
Sandbox chay hoan toan cuc bo, khong can internet.

```
+---------------------- Test Sandbox (localhost) ---------------------+
|                                                                      |
|  +-----------------------+     +-----------------------+             |
|  | cfox-server           |     | PostgreSQL (Docker)   |             |
|  | FastAPI :8760         |---->| :5433                 |             |
|  | (test instance)       |     | database: cfox_test   |             |
|  +-----------+-----------+     +-----------------------+             |
|              |                                                        |
|  +-----------v-----------+     +-----------------------+             |
|  | cfox-local            |     | Local SQLite          |             |
|  | FastAPI :7601         |---->| (tmp_path per test)   |             |
|  | (test instance)       |     +-----------------------+             |
|  +-----------------------+                                           |
|                                                                      |
|  +--------------------------------------------------------+         |
|  | Test Runner (pytest-asyncio)                            |         |
|  | - Spin up/down sandbox per session                      |         |
|  | - Isolated tmp_path per test                            |         |
|  | - Mock network failures via aioresponses                |         |
|  +--------------------------------------------------------+         |
+----------------------------------------------------------------------+
```

### 1.2 Docker Compose (PostgreSQL)

**File:** `tests/sandbox/docker-compose.yml`

```yaml
version: "3.9"
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cfox_test
      POSTGRES_PASSWORD: cfox_test
      POSTGRES_DB: cfox_test
    ports:
      - "5433:5432"
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cfox_test"]
      interval: 1s
      timeout: 3s
      retries: 10
```

### 1.3 Sandbox Lifecycle

| Phase | Action |
|-------|--------|
| session_start | docker compose up -d -> wait healthy |
| session_start | Apply DB migrations -> create test API key |
| each_test | Truncate all tables -> seed test API key |
| session_end | docker compose down -v |

---

## 2. Test Layers

### 2.1 Unit Tests (no sandbox needed)

```
tests/cloud/
+-- unit/
|   +-- test_lock_service.py
|   +-- test_storage_service.py
|   +-- test_sync_service.py
|   +-- test_upload_queue.py
|   +-- test_cloud_client.py
|   +-- test_heartbeat_service.py
```

#### 2.1.1 test_lock_service.py (12 cases)

| Test Case | Input | Expected |
|-----------|-------|----------|
| test_acquire_lock_success | profile idle, valid machine_id | 200, lock_token returned |
| test_acquire_lock_already_locked | profile locked by other machine | 423, includes locked_by |
| test_acquire_lock_expired_ttl | lock TTL expired | 200, overwrite lock silently |
| test_renew_lock_valid_token | valid lock_token | 200, expires_at extended +120min |
| test_renew_lock_wrong_token | wrong lock_token | 403 Forbidden |
| test_renew_lock_wrong_machine | correct token, wrong machine_id | 403 ownership check |
| test_release_lock_valid | valid token + machine_id | 200, lock cleared |
| test_release_lock_wrong_token | wrong token | 403 |
| test_force_unlock | admin scope API key | 200, lock cleared |
| test_ttl_expiry_background | 10 expired locks in DB | all cleared within 60s |
| test_heartbeat_updates_expiry | valid heartbeat | lock_expires_at = now + 120min |
| test_previous_lock_race_info | lock within 60s of previous | response includes previous_lock info |

#### 2.1.2 test_storage_service.py (11 cases)

| Test Case | Input | Expected |
|-----------|-------|----------|
| test_upload_first_version | ZIP bytes, v=0 | stored as v1, checksum saved |
| test_upload_if_match_success | If-Match: 3, current=3 | 200, version becomes 4 |
| test_upload_if_match_conflict | If-Match: 3, current=5 | 409 {current:5, expected:3} |
| test_upload_checksum_mismatch | wrong Content-SHA256 | 400 Bad Request |
| test_download_returns_checksum | valid download | Content-SHA256 header included |
| test_version_rotation_keeps_3 | upload 5 times | last 3 versions retained |
| test_version_rotation_deletes_oldest | v4 uploaded, v1-v3 exist | v1 deleted |
| test_rollback_success | upload v1,v2,v3, rollback to v1 | current data = v1 |
| test_rollback_nonexistent | rollback to v99 | 404 |
| test_get_versions_list | 3 versions exist | sorted desc with size/checksum |
| test_get_essential_data_info | profile with v5 | {version, size, checksum, uploaded_at} |

#### 2.1.3 test_sync_service.py (11 cases)

| Test Case | Input | Expected |
|-----------|-------|----------|
| test_collect_copies_before_zip | user_data_dir with essential files | ZIP created, original untouched |
| test_collect_handles_wal | .sqlite-wal present | copy-before-zip avoids corruption |
| test_collect_only_essential | mixed files (cookies + cache) | only ESSENTIAL_PATTERNS in ZIP |
| test_restore_clean_extract | ZIP with cookies, storage | extracts cleanly, old deleted first |
| test_restore_clears_cache | ZIP extracted | cache2/ startupCache/ cleared |
| test_restore_never_merges | existing stale cookies | old deleted before new extracted |
| test_checksum_matches_collect | collect -> compute SHA-256 | matches expected |
| test_checksum_verify_restore | restore -> verify files | matches download checksum |
| test_checksum_mismatch_rejects | corrupted ZIP | exception raised, restore aborted |
| test_empty_essential_data | new profile, no browsing | minimal valid ZIP, restore no-op |
| test_essential_patterns_constant | check patterns list | covers cookies, storage, HSTS |

#### 2.1.4 test_upload_queue.py (9 cases)

| Test Case | Input | Expected |
|-----------|-------|----------|
| test_enqueue_single | 1 profile upload | completes, removed from queue |
| test_deduplication | enqueue same profile twice | only one upload executed |
| test_max_concurrent_3 | enqueue 10 profiles | max 3 active at once (Semaphore(3)) |
| test_exponential_backoff | 3 failures then success | delays: 2s, 4s, 8s -> success |
| test_backoff_cap_300s | 6 failures | delays capped at 300s |
| test_max_retries_5 | 6 consecutive failures | marked failed after 5th retry |
| test_ws_event_progress | upload in queue | WS sync_progress events emitted |
| test_ws_event_complete | upload succeeds | WS sync_complete event |
| test_ws_event_failure | upload fails 5x | WS sync_failed event |

#### 2.1.5 test_cloud_client.py (7 cases)

| Test Case | Expected |
|-----------|----------|
| test_auth_header_injection | Bearer token on all requests |
| test_retry_on_5xx | retried 3 times with backoff |
| test_no_retry_on_4xx | error propagated immediately |
| test_health_ping_success | 200, server_connected: true |
| test_health_ping_timeout | server_connected: false after timeout (5s) |
| test_connection_lost_mid_request | exception raised, retry triggered |
| test_base_url_trailing_slash | no double slash in final URL |

#### 2.1.6 test_heartbeat_service.py (7 cases)

| Test Case | Expected |
|-----------|----------|
| test_heartbeat_every_30s | PUT /heartbeat every 30s +-2s |
| test_60s_warning | WS heartbeat_warning at 60s (2 fails) |
| test_150s_critical | WS heartbeat_critical at 150s (5 fails) |
| test_300s_kill | browser closed, upload enqueued |
| test_recovery_after_intermittent | counter resets, no kill |
| test_stops_on_session_close | no more heartbeats sent |
| test_multiple_sessions_independent | each has own heartbeat loop |

---

### 2.2 Integration Tests (sandbox required)

```
tests/cloud/
+-- integration/
|   +-- test_cloud_launch_flow.py
|   +-- test_multi_machine.py
|   +-- test_conflict_resolution.py
|   +-- test_crash_recovery.py
|   +-- test_dual_source_merge.py
|   +-- test_proxy_pool_cloud.py
```

#### 2.2.1 test_cloud_launch_flow.py - Golden Path (8 scenarios)

```python
async def test_full_cloud_lifecycle(cfox_server, cfox_local, tmp_essential_dir):
    # 1. Create cloud profile via server API
    # 2. cfox-local lists it in merged profile list
    # 3. Launch -> lock acquired -> essential downloaded -> browser opens
    # 4. Simulate browsing (write cookies, localStorage)
    # 5. Close -> essential uploaded -> metadata updated -> unlock
    # 6. Verify essential data integrity (SHA-256 matches)
    # 7. Re-launch -> verify cookies persist
```

| Scenario | Steps | Verification |
|----------|-------|-------------|
| Create and list | POST cloud profile -> GET merged list | Profile appears with source: cloud |
| Launch flow | POST /launch -> WS events | downloading -> launching -> running |
| Lock protection | Try launch from 2nd instance | 423 Locked |
| Browser use | Write cookies via Playwright | Cookies stored in user_data_dir |
| Close flow | POST /stop -> WS events | uploading -> idle, sync: ok |
| Data integrity | Compare pre/post SHA-256 | Checksums match |
| Re-launch persistence | Launch again -> read cookies | Cookies from previous session present |
| Session count tracking | Launch 3 times | total_sessions: 3, last_used_at updated |

#### 2.2.2 test_multi_machine.py (5 scenarios)

Two cfox-local instances on :7601 and :7602, different machine_ids.

| Scenario | Machine A | Machine B | Expected |
|----------|-----------|-----------|----------|
| Lock blocks cross-machine | Launches profile X | Tries launch profile X | A: running, B: 423 |
| Force unlock | Running X | Force-unlock X | A: killed, B: can lock |
| Graceful handover | Stops X (upload+unlock) | Waits -> launches | B gets A cookies |
| Crash handover | Kill A browser process | Monitors lock | A uploads on crash, B can lock after |
| Heartbeat race | A heartbeating normally | B waits | A lock extended, B stays blocked |

#### 2.2.3 test_conflict_resolution.py (6 scenarios)

| Scenario | Setup | Expected |
|----------|-------|----------|
| Version 409 | A downloads v3, B uploads v3->v4, A uploads If-Match:3 | 409 {current:4, expected:3} |
| Checksum mismatch | Upload with wrong SHA-256 | 400, upload rejected |
| Download corrupt | Server sends corrupt ZIP | Client rejects, retries download |
| Concurrent create | A and B create same profile name | unique constraint, 409 |
| sync_incomplete flag | Upload succeeds but metadata update times out | flag: true, UI warning on next launch |
| Rollback after conflict | v5 corrupted -> rollback to v4 | v4 restored, client gets v4 |

#### 2.2.4 test_crash_recovery.py (6 scenarios)

| Scenario | Simulation | Expected |
|----------|------------|----------|
| Browser process crash | Kill Playwright browser subprocess | BSM detects -> tries upload -> unlock |
| Crash mid-upload | Kill cfox-local during upload | upload_queue retries on restart |
| Upload retry success | Server 503 on 1st attempt | backoff -> succeeds -> unlocks |
| Upload exhausted | Server down for >30min | 5 retries -> sync_failed, lock TTL cleanup |
| Zombie detection on restart | cfox-local crash, PID stale | Recovery: ping context -> dead -> cleanup |
| running_sessions recovery | Kill cfox-local, restart | sessions table restores, dead cleaned |

#### 2.2.5 test_dual_source_merge.py (6 scenarios)

| Scenario | Expected |
|----------|----------|
| Local + cloud merged | GET /api/profiles returns both, sorted by last_used_at |
| source=local filter | Only local profiles returned |
| source=cloud filter | Only cloud profiles returned |
| Server disconnected | Only local shown, server_connected: false |
| Server reconnected | Full merge again |
| Duplicate UUID handling | source param resolves ambiguity |

---

### 2.3 API Route Tests (FastAPI TestClient)

```
tests/cloud/
+-- routes/
|   +-- test_cfox_server_profiles.py
|   +-- test_cfox_server_locks.py
|   +-- test_cfox_server_storage.py
|   +-- test_cfox_server_proxies.py
|   +-- test_cfox_local_server.py
|   +-- test_cfox_local_profiles.py
```

#### cfox-server route tests

| Endpoint | Test Cases |
|----------|-----------|
| POST /api/profiles | Auth required, valid create, duplicate name, invalid fingerprint |
| GET /api/profiles | List all, filter by tag/OS, pagination |
| GET /api/profiles/{id} | Found, not found, 401 without auth |
| PUT /api/profiles/{id} | Update with If-Match, 409 on conflict, 404 |
| DELETE /api/profiles/{id} | Cant delete locked, force delete with admin |
| POST /api/profiles/{id}/lock | Lock success, 423 when locked, TTL parameter |
| PUT /api/profiles/{id}/heartbeat | Valid token, invalid token, wrong machine_id |
| DELETE /api/profiles/{id}/lock | Unlock success, token validation |
| POST /api/profiles/{id}/lock/force | Force unlock (admin scope required) |
| PUT /api/profiles/{id}/essential_data | Upload with If-Match + Content-SHA256, 409, 400 |
| GET /api/profiles/{id}/essential_data | Download with Content-SHA256 header, 404 |
| GET /api/profiles/{id}/essential_data/info | Version info, 404 |
| GET /api/profiles/{id}/essential_data/versions | Version list sorted desc |
| POST /api/profiles/{id}/essential_data/rollback/{v} | Rollback success, 404 on bogus version |

---

## 3. Conftest Design

### 3.1 tests/cloud/conftest.py - Session-level fixtures

Key fixtures:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| sandbox_db_url | session | PostgreSQL connection string for test |
| sandbox_up | session | docker compose up/down lifecycle |
| test_api_key | session | Shared API key for test auth |
| cfox_server | session | Start cfox-server on port 8760 |
| server_client | function | httpx.AsyncClient with Bearer token |
| unauthenticated_client | function | httpx.AsyncClient without auth |
| clean_db | function | TRUNCATE all tables between tests |
| cfox_local | function | Start cfox-local on port 7601 |
| cfox_local_b | function | Second instance on port 7602 (multi-machine) |
| local_client | function | httpx client for cfox-local |
| tmp_essential_dir | function | Fake user_data_dir with essential files |

### 3.2 tests/cloud/unit/conftest.py - Mock fixtures

| Fixture | Purpose |
|---------|---------|
| mock_cloud_client | httpx.MockTransport for cloud_client tests |
| tmp_storage_dir | Temp dir for storage_service filesystem tests |
| mock_db_session | Mock SQLAlchemy async session |

---

## 4. Test Dependencies

### 4.1 pyproject.toml additions

```toml
[tool.pytest.ini_options]
markers = [
    "cloud: tests requiring cloud sandbox (Docker + PostgreSQL)",
    "unit: fast unit tests, no external dependencies",
    "integration: tests requiring full sandbox",
    "slow: tests taking > 10 seconds",
]

[project.optional-dependencies]
test-cloud = [
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "asyncpg>=0.29.0",
    "sqlalchemy[asyncio]>=2.0",
    "alembic>=1.13.0",
    "freezegun>=1.4.0",
]
```

### 4.2 Running Tests

```bash
# Unit tests only (fast, no Docker)
pytest tests/cloud/unit/ -v

# Integration tests (requires Docker sandbox)
pytest tests/cloud/integration/ -v -m cloud

# All cloud tests
pytest tests/cloud/ -v

# Skip slow tests
pytest tests/cloud/ -v -m "not slow"

# Specific test file with coverage
pytest tests/cloud/unit/test_lock_service.py -v --cov=cfox_server --cov-report=term

# Full coverage report
pytest tests/cloud/ -v --cov=cfox_server --cov=cfox_local/services --cov-report=html
```

---

## 5. Manual Verification Checklist

Scenarios that CANNOT be fully automated. Must be checked manually before Phase 3 release.

### 5.1 Multi-Machine Handover (Real Browsers)

- [ ] Machine A launch cloud profile -> login to a site -> cookies written
- [ ] Machine A close -> upload completes -> unlock
- [ ] Machine B launch same profile -> A cookies present -> session preserved
- [ ] Machine B close -> upload -> unlock OK

### 5.2 Network Interruption Resilience

- [ ] Launch cloud profile, browser running normally
- [ ] Disconnect WiFi on client machine
- [ ] Observe graduated warnings: 60s warn -> 150s critical -> 300s kill
- [ ] Reconnect WiFi before kill threshold -> heartbeat recovers, browser survives
- [ ] Let it reach kill threshold -> browser closed, upload enqueued on reconnect

### 5.3 Crash Simulation (Real Browser)

- [ ] Launch cloud profile
- [ ] Kill browser process via Task Manager or kill -9
- [ ] BSM detects disconnect within 5 seconds
- [ ] Essential data collected from copy and uploaded
- [ ] Lock released on server
- [ ] Re-launch profile -> cookies from crashed session intact

### 5.4 Force-Push Conflict Resolution

- [ ] Machine A downloads essential_data v5, launches browser
- [ ] After A closes, Machine B downloads v5, launches browser
- [ ] Machine A closes first -> uploads v5->v6 successfully
- [ ] Machine B closes -> tries upload with If-Match: 5 -> 409 Conflict
- [ ] UI dialog shows version conflict with context (you have v5, server is v6)
- [ ] User picks: Download fresh version and retry / Force overwrite

### 5.5 Checksum Integrity Verification

- [ ] Upload profile with known content, verify SHA-256 stored correctly
- [ ] Manually corrupt the ZIP file on server filesystem
- [ ] Download attempt -> client computes SHA-256 -> detects mismatch
- [ ] Client rejects download -> WS warning event emitted

### 5.6 Version Retention and Rollback

- [ ] Upload 3 versions: v1, v2, v3 of essential data
- [ ] Rollback to v1 via API endpoint
- [ ] Download -> verify v1 content is restored as current
- [ ] v2 and v3 still available in versions history
- [ ] Upload v4 -> v1 deleted (3-version cap), v2/v3/v4 retained

---

## 6. Test File Tree (Final Layout)

```
tests/
+-- conftest.py                      # Playwright fixtures (existing)
+-- server.py                        # Test HTTP server (existing)
+-- test_store.py                    # V2 store tests (existing)
+-- test_fingerprint.py              # V2 fingerprint tests (existing)
+-- test_warmup.py                   # V2 warmup tests (existing)
|   test_consistency.py              # V2 consistency (existing)
|
+-- sandbox/
|   +-- docker-compose.yml           # PostgreSQL container for tests
|
+-- cloud/
|   +-- __init__.py
|   +-- conftest.py                  # Session-level sandbox + server fixtures
|   +-- conftest_unit.py             # Unit-only mock fixtures (no sandbox)
|   |
|   +-- unit/
|   |   +-- __init__.py
|   |   +-- test_lock_service.py     # 12 test cases
|   |   +-- test_storage_service.py  # 11 test cases
|   |   +-- test_sync_service.py     # 11 test cases
|   |   +-- test_upload_queue.py     # 9 test cases
|   |   +-- test_cloud_client.py     # 7 test cases
|   |   +-- test_heartbeat_service.py # 7 test cases
|   |
|   +-- routes/
|   |   +-- __init__.py
|   |   +-- test_cfox_server_profiles.py
|   |   +-- test_cfox_server_locks.py
|   |   +-- test_cfox_server_storage.py
|   |   +-- test_cfox_server_proxies.py
|   |   +-- test_cfox_local_server.py
|   |   +-- test_cfox_local_profiles.py
|   |
|   +-- integration/
|       +-- __init__.py
|       +-- test_cloud_launch_flow.py   # 8 scenarios
|       +-- test_multi_machine.py       # 5 scenarios
|       +-- test_conflict_resolution.py # 6 scenarios
|       +-- test_crash_recovery.py      # 6 scenarios
|       +-- test_dual_source_merge.py   # 6 scenarios
|       +-- test_proxy_pool_cloud.py    # 4 scenarios
|
+-- async/                               # Playwright async tests (existing)
    +-- ...
```

---

## 7. CI Integration (GitHub Actions)

```yaml
name: Cloud Tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test-cloud]"
      - run: pytest tests/cloud/unit/ -v

  integration:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: cfox_test
          POSTGRES_PASSWORD: cfox_test
          POSTGRES_DB: cfox_test
        ports:
          - 5433:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 1s
          --health-timeout 3s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[test-cloud]"
      - run: pytest tests/cloud/integration/ tests/cloud/routes/ -v
```

---

## 8. Summary: Test Count and Coverage Targets

| Layer | Files | Test Cases (min) | Coverage Target |
|-------|-------|-----------------|-----------------|
| Unit (services) | 6 | ~57 | 90%+ line coverage |
| Route tests | 6 | ~50 | 85%+ line coverage |
| Integration | 6 | ~35 | N/A (scenario-based) |
| **Total** | **18** | **~142** | -- |

### Implementation Priority

1. **Sandbox infrastructure** - docker-compose + conftest fixtures (make it runnable first)
2. **Unit: lock_service + storage_service** - critical path, highest risk
3. **Unit: sync_service + upload_queue** - data integrity core
4. **Unit: cloud_client + heartbeat_service** - connectivity layer
5. **Routes: cfox-server** - API contract validation
6. **Routes: cfox-local cloud** - client-side routing
7. **Integration: cloud_launch_flow** - golden path end-to-end
8. **Integration: multi_machine + crash_recovery** - edge cases
9. **Integration: conflict + merge + proxy** - remaining scenarios
10. **Manual verification** - pre-release gate before Phase 3 sign-off
