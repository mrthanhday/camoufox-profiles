# Phase 3 Implementation Checklist - Per File Tracking

> Use this to track progress. Mark each file as TODO -> IN PROGRESS -> DONE.
> Last updated: 2026-05-09 (v2.0 — aligned with PHASE3_PLAN.md v2.0)

---

## 3.0 Unified Data Layer Refactor

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 1 | `src/camoufox_profiles/models_sa.py` | NEW | [ ] TODO | SQLAlchemy 2.0 models: Profile, DriftEvent, ProxyPool, TagMeta, User |
| 2 | `src/camoufox_profiles/db.py` | NEW | [ ] TODO | Shared engine factory (SQLite + PostgreSQL) |
| 3 | `src/camoufox_profiles/store_sa.py` | NEW | [ ] TODO | SQLAlchemy-based ProfileStore (replaces raw SQL store.py) |
| 4 | `src/camoufox_profiles/manager.py` | MODIFY | [ ] TODO | Switch to ProfileStoreSA |
| 5 | `cfox_local/config.py` | MODIFY | [ ] TODO | Add database_url field |

---

## 3.1 cfox-server Scaffolding

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 6 | `cfox_server/__init__.py` | NEW | [ ] TODO | Empty init |
| 7 | `cfox_server/config.py` | NEW | [ ] TODO | Settings via pydantic-settings |
| 8 | `cfox_server/schemas.py` | NEW | [ ] TODO | Pydantic v2 request/response schemas |
| 9 | `cfox_server/middleware.py` | NEW | [ ] TODO | API key auth (lookup users table, role extraction) |
| 10 | `cfox_server/app.py` | NEW | [ ] TODO | FastAPI factory + lifespan (uses shared db.py) |
| 11 | `pyproject.toml` | MODIFY | [ ] TODO | Add [server] extras, shared SQLAlchemy deps |

---

## 3.2 Profile CRUD + Lock Protocol + Users

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 12 | `cfox_server/routes/__init__.py` | NEW | [ ] TODO | Empty init |
| 13 | `cfox_server/routes/profiles.py` | NEW | [ ] TODO | CRUD with If-Match, pagination |
| 14 | `cfox_server/routes/locks.py` | NEW | [ ] TODO | Lock/heartbeat/unlock/force-unlock |
| 15 | `cfox_server/routes/users.py` | NEW | [ ] TODO | User CRUD, role mgmt, key rotation (admin only) |
| 16 | `cfox_server/services/__init__.py` | NEW | [ ] TODO | Empty init |
| 17 | `cfox_server/services/lock_service.py` | NEW | [ ] TODO | TTL expiry background task |

---

## 3.3 Essential Data Storage

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 18 | `cfox_server/routes/storage.py` | NEW | [ ] TODO | Upload/download/versions/rollback |
| 19 | `cfox_server/services/storage_service.py` | NEW | [ ] TODO | Version rotation + checksum verify |

---

## 3.4 Sync Service (Local — No Server Dependency)

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 20 | `cfox_local/services/__init__.py` | NEW | [ ] TODO | Empty init |
| 21 | `cfox_local/services/sync_service.py` | NEW | [ ] TODO | Copy-before-zip, clean extract, SHA-256, configurable patterns |

---

## 3.5 Cloud Client

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 22 | `cfox_local/services/cloud_client.py` | NEW | [ ] TODO | httpx client + auth + retry + 30s cache |
| 23 | `cfox_local/routes/server.py` | NEW | [ ] TODO | /api/server/status, connect, disconnect |
| 24 | `cfox_local/config.py` | MODIFY | [ ] TODO | Add server_url, server_api_key, cloud_enabled |
| 25 | `cfox_local/app.py` | MODIFY | [ ] TODO | Include server route, init CloudClient |

---

## 3.6 Upload Queue + Heartbeat

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 26 | `cfox_local/services/upload_queue.py` | NEW | [ ] TODO | Dedup, Semaphore(3), exp backoff, max 5 retries |
| 27 | `cfox_local/services/heartbeat_service.py` | NEW | [ ] TODO | 30s interval, graduated kill + force-close browser |

---

## 3.7 Dual-Source Modification

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 28 | `cfox_local/session_manager.py` | MODIFY | [ ] TODO | Cloud launch/stop/heartbeat-death/crash flow |
| 29 | `cfox_local/routes/profiles.py` | MODIFY | [ ] TODO | Merge local + cloud, source annotation + routing |
| 30 | `cfox_local/routes/proxies.py` | MODIFY | [ ] TODO | Cloud primary, local fallback |

---

## 3.8 Docker + Deployment

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| 31 | `cfox_server/Dockerfile` | NEW | [ ] TODO | Production container |
| 32 | `docker-compose.yml` | NEW | [ ] TODO | PostgreSQL + cfox-server (project root) |
| 33 | `pyproject.toml` | MODIFY | [ ] TODO | cfox-server entry point (combine with #11) |

---

## Test Files (Phase 3)

From `docs/TEST_STRATEGY.md`.

### Sandbox Infrastructure

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| T1 | `tests/sandbox/docker-compose.yml` | NEW | [ ] TODO | PostgreSQL container |
| T2 | `tests/cloud/__init__.py` | NEW | [ ] TODO | |
| T3 | `tests/cloud/conftest.py` | NEW | [ ] TODO | Session-level sandbox fixtures |
| T4 | `tests/cloud/conftest_unit.py` | NEW | [ ] TODO | Unit-only mock fixtures |

### Unit Tests

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| T5 | `tests/cloud/unit/__init__.py` | NEW | [ ] TODO | |
| T6 | `tests/cloud/unit/test_lock_service.py` | NEW | [ ] TODO | 12 cases |
| T7 | `tests/cloud/unit/test_storage_service.py` | NEW | [ ] TODO | 11 cases |
| T8 | `tests/cloud/unit/test_sync_service.py` | NEW | [ ] TODO | 11 cases |
| T9 | `tests/cloud/unit/test_upload_queue.py` | NEW | [ ] TODO | 9 cases |
| T10 | `tests/cloud/unit/test_cloud_client.py` | NEW | [ ] TODO | 7 cases |
| T11 | `tests/cloud/unit/test_heartbeat_service.py` | NEW | [ ] TODO | 7 cases |
| T12 | `tests/cloud/unit/test_store_sa.py` | NEW | [ ] TODO | Unified store tests (SQLite + PostgreSQL) |

### Route Tests

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| T13 | `tests/cloud/routes/__init__.py` | NEW | [ ] TODO | |
| T14 | `tests/cloud/routes/test_cfox_server_profiles.py` | NEW | [ ] TODO | |
| T15 | `tests/cloud/routes/test_cfox_server_locks.py` | NEW | [ ] TODO | |
| T16 | `tests/cloud/routes/test_cfox_server_storage.py` | NEW | [ ] TODO | |
| T17 | `tests/cloud/routes/test_cfox_server_users.py` | NEW | [ ] TODO | User CRUD + role tests |
| T18 | `tests/cloud/routes/test_cfox_local_server.py` | NEW | [ ] TODO | |
| T19 | `tests/cloud/routes/test_cfox_local_profiles.py` | NEW | [ ] TODO | |

### Integration Tests

| # | File | Action | Status | Notes |
|---|------|--------|--------|-------|
| T20 | `tests/cloud/integration/__init__.py` | NEW | [ ] TODO | |
| T21 | `tests/cloud/integration/test_cloud_launch_flow.py` | NEW | [ ] TODO | 8 scenarios |
| T22 | `tests/cloud/integration/test_multi_machine.py` | NEW | [ ] TODO | 5 scenarios |
| T23 | `tests/cloud/integration/test_conflict_resolution.py` | NEW | [ ] TODO | 6 scenarios |
| T24 | `tests/cloud/integration/test_crash_recovery.py` | NEW | [ ] TODO | 6 scenarios |
| T25 | `tests/cloud/integration/test_dual_source_merge.py` | NEW | [ ] TODO | 6 scenarios |
| T26 | `tests/cloud/integration/test_proxy_pool_cloud.py` | NEW | [ ] TODO | 4 scenarios |

---

## Summary

| Sub-phase | New Files | Modify Files | Total |
|-----------|-----------|-------------|-------|
| 3.0 Unified Data Layer | 3 | 2 | 5 |
| 3.1 Scaffolding | 5 | 1 | 6 |
| 3.2 Profile + Lock + Users | 6 | 0 | 6 |
| 3.3 Storage | 2 | 0 | 2 |
| 3.4 Sync Service | 2 | 0 | 2 |
| 3.5 Cloud Client | 2 | 2 | 4 |
| 3.6 Queue + Heartbeat | 2 | 0 | 2 |
| 3.7 Dual-Source | 0 | 3 | 3 |
| 3.8 Docker | 2 | 1 | 3 |
| **Implementation** | **24** | **9** | **33** |
| Tests | 26 | 0 | 26 |
| **Grand Total** | **50** | **9** | **59** |
