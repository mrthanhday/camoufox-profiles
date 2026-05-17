# Camoufox Profiles — Progress Tracker

> **Last updated:** 2026-05-18

---

## Phase Summary

| Phase | Status | Files | Description |
|-------|--------|-------|-------------|
| 1. cfox-local API | ✅ Complete | 13 | FastAPI server wrapping ProfileManager |
| 2. Web UI | ✅ Complete | 28 | React + Vite dashboard |
| 3. Cloud Sync | ✅ Complete | 33 | cfox-server + sync services + Docker |
| 4. E2E Tests | ✅ Complete | 8 | 42 tests across 6 suites |
| 5. Polish & bugfix | ✅ Complete | — | Routes/store fixes, hardening, doc cleanup |

---

## Phase 1: cfox-local API

FastAPI server wrapping V2 `ProfileManager` with REST + WebSocket.

**Files:** `cfox_local/`

| File | Purpose |
|------|---------|
| `app.py` | FastAPI factory, lifespan, CORS, static mount |
| `config.py` | Settings, machine_id persistence |
| `session_manager.py` | BrowserSessionManager singleton (launch/stop/crash recovery, AsyncExitStack-based) |
| `tray.py` | System tray (pystray) |
| `__main__.py` | Entry point (console + tray modes) |
| `routes/profiles.py` | Profile CRUD |
| `routes/browser.py` | Launch/stop/sessions/warmup |
| `routes/health.py` | Health check + drift history |
| `routes/proxies.py` | Local proxy pool |
| `routes/tags.py` | Tag management |
| `routes/server.py` | Cloud server status/connect |
| `routes/ws.py` | EventBus + WebSocket endpoint |

---

## Phase 2: Web UI

React + Vite + TypeScript dashboard served by cfox-local as static files.

**Files:** `cfox_ui/src/`

| Area | Files | Details |
|------|-------|---------|
| Core | 4 | `App.tsx`, `api.ts`, `main.tsx`, `index.css` |
| Hooks | 2 | `useProfiles.ts`, `useWebSocket.ts` |
| Pages | 4 | Profiles, ProxyPool, Settings, TagManager |
| Components | 17 | ProfileCard, Modals (7), Inline editors (2), Proxy (4), etc. |

---

## Phase 3: Cloud Sync

Self-hosted cfox-server with PostgreSQL + cloud sync services in cfox-local.

### cfox-server files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI factory, admin bootstrap (writes generated key to file) |
| `config.py` | Pydantic settings (env vars, `max_upload_bytes`) |
| `middleware.py` | API key authentication (SHA-256) |
| `schemas.py` | Request/response Pydantic schemas |
| `routes/profiles.py` | Cloud profile CRUD |
| `routes/locks.py` | Lock acquire/release/heartbeat |
| `routes/storage.py` | Essential data upload/download/versions (size-capped) |
| `routes/users.py` | User management (admin) |
| `services/lock_service.py` | Background lock cleanup |
| `services/storage_service.py` | File storage + version rotation |

### Cloud services in cfox-local

| File | Purpose |
|------|---------|
| `services/cloud_client.py` | HTTP client SDK (retry with full jitter backoff) |
| `services/heartbeat_service.py` | Periodic heartbeat for active cloud sessions |
| `services/sync_service.py` | Profile sync orchestrator |
| `services/upload_queue.py` | Background upload queue with dedup |

### Shared data layer

| File | Purpose |
|------|---------|
| `src/camoufox_profiles/db.py` | Unified database engine factory |
| `src/camoufox_profiles/store_sa.py` | SQLAlchemy store implementation |
| `src/camoufox_profiles/models_sa.py` | SQLAlchemy ORM models |

### Infrastructure

| File | Purpose |
|------|---------|
| `docker-compose.yml` | PostgreSQL + cfox-server |
| `Dockerfile.server` | cfox-server container |
| `.env.example` | Environment template |

---

## Phase 4: E2E Tests

| Suite | File | Tests | Execution |
|-------|------|-------|-----------|
| 1. Server API | `test_server_api.py` | 4 | In-process (ASGI) |
| 2. Local API | `test_local_api.py` | 12 | In-process (ASGI) |
| 3. Cloud Client | `test_cloud_client.py` | 8 | In-process (ASGI) |
| 4. UI Settings | `test_ui_settings.py` | 7 | Subprocess (:9600) |
| 5. UI Profiles | `test_ui_profiles.py` | 6 | Subprocess (:9600) |
| 6. Cross-System | `test_cross_system.py` | 5 | In-process (ASGI) |

---

## Phase 5: Polish & bugfix

Recent fixes (2026-05-18):

| Area | Fix |
|------|-----|
| `cfox_local/routes/health.py` | Wrong field names (`report.score`, `c.name`, `e.event_type`) → use canonical `HealthReport` / `HealthCheck` / `DriftEvent` API and compute score locally |
| `cfox_local/routes/browser.py` | Warmup called `warmup_profile` with wrong signature → delegate to `ProfileManager.warmup` |
| `src/camoufox_profiles/batch.py` | `WarmupReport.sites_visited/sites_attempted` → use `successful_visits / total_visits` |
| `src/camoufox_profiles/manager.py` | `batch_health_check` invocation now matches `batch.py` signature; `check_proxies` returns `List[ProxyPoolEntry]` |
| `src/camoufox_profiles/store.py` | `update()` now accepts proxy fields; routes no longer issue raw SQL |
| `cfox_local/routes/profiles.py` | Removed dead self-import + duplicated update_data; tag-limit reads from app settings |
| `cfox_local/__main__.py` | Imported `Any` (typing) — tray mode no longer NameErrors |
| `cfox_server/routes/storage.py` | `request: Request` is required positional; upload size capped via `max_upload_bytes` |
| `cfox_server/app.py` | Generated admin API key written to `data/admin_api_key.generated` (chmod 0600) instead of stdout |
| `cfox_local/session_manager.py` | Uses `AsyncExitStack` instead of holding raw context manager — robust across Playwright versions |
| `cfox_local/services/cloud_client.py` | Retry uses exponential backoff with full jitter |
| `tests/e2e/test_local_api.py` | Supports both `transport.app` and `transport._app` (httpx version compat) |
| `src/camoufox_profiles/cli.py` | Added `cfox proxy bind <profile> <proxy_id>` |
| `src/camoufox_profiles/__init__.py` | Version bumped to 0.3.0 (sync with `pyproject.toml`) |
| Repo cleanup | Removed leaked test DBs, log files, screenshots, `manual_test.py`, scratch text; added gitignore entries |
| Docs cleanup | Consolidated to `ARCHITECTURE.md` (v6); removed `ARCHITECTURE_V5.md`, `IMPLEMENTATION_PLAN.md`, `PHASE3_PLAN.md`, `TEST_STRATEGY.md`, `TRACKING.md`, root-level `design.md` |

---

## Key Design Decisions

| Decision | Value |
|----------|-------|
| Deployment model | Self-hosted dedicated server |
| Database unification | SQLAlchemy 2.0 (SQLite local, PostgreSQL server) |
| Profile ID | UUID4 shared ID space |
| Multi-user | `users` table with `admin`/`member` roles, API key auth |
| Sync protocol | Copy-before-zip + clean extract (never merge) |
| Concurrency | Optimistic: `If-Match: base_version`, 409 on conflict |
| Data integrity | SHA-256 checksum on upload + download |
| Upload size cap | `max_upload_bytes` (default 256 MB) |
| Lock ownership | Server validates lock_token + machine_id |
| Upload queue | Dedup by profile_id, max 3 concurrent, exponential backoff |
| Heartbeat | 30s interval, graduated: warn → critical → force-close |
| Version retention | Server keeps last 3 versions, rollback API |
| Migration strategy | Auto-migrate on startup |
| Cloud cache | 30s TTL, invalidate on write |
| Retry backoff | Exponential with full jitter |

---

## Reference Documents

| Document | Location | Content |
|----------|----------|---------|
| README | `README.md` | Full project documentation |
| Architecture | `docs/ARCHITECTURE.md` | System architecture v6 |
| Progress | `docs/PROGRESS.md` | This file — status tracker |
| Testing | `docs/TESTING.md` | E2E test strategy and execution |
| Design notes | `DESIGN_NOTES.md` | Profile system design rationale |
| Camoufox arch | `CAMOUFOX_ARCHITECTURE.md` | Firefox patches & MaskConfig system |
| Workflow | `WORKFLOW.md` | Firefox patching workflow |
| Build fixes | `BUILD_FIXES_142.md` | Firefox 142 build fixes |
| FF142 upgrade | `FIREFOX_142_UPGRADE_NOTES.md` | Per-patch upgrade notes |
| Upgrade workflow | `FIREFOX_UPGRADE_WORKFLOW.md` | Upgrade-time decision tree |
| Claude guide | `CLAUDE.md` | Agent guidance for the codebase |
