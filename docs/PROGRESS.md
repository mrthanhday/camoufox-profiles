# Camoufox Profiles — Progress Tracker

> **Last updated:** 2026-05-11

---

## Phase Summary

| Phase | Status | Duration | Files | Description |
|-------|--------|----------|-------|-------------|
| 1. cfox-local API | ✅ Complete | — | 13 | FastAPI server wrapping ProfileManager |
| 2. Web UI | ✅ Complete | — | 28 | React + Vite dashboard |
| 3. Cloud Sync | ✅ Complete | — | 33 | cfox-server + sync services + Docker |
| 4. E2E Tests | ✅ Complete | — | 8 | 42 tests across 6 suites |
| 5. Polish | 🔲 Planned | — | — | See Remaining section |

---

## Phase 1: cfox-local API ✅

FastAPI server wrapping V2 `ProfileManager` with REST + WebSocket.

**Files:** `cfox_local/` (13 files)

| File | Purpose |
|------|---------|
| `app.py` | FastAPI factory, lifespan, CORS, static mount |
| `config.py` | Settings, machine_id persistence |
| `session_manager.py` | BrowserSessionManager singleton (launch/stop/crash/recovery) |
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

## Phase 2: Web UI ✅

React + Vite + TypeScript dashboard served by cfox-local as static files.

**Files:** `cfox_ui/src/` (28 files)

| Area | Files | Details |
|------|-------|---------|
| Core | 4 | `App.tsx`, `api.ts`, `main.tsx`, `index.css` |
| Hooks | 2 | `useProfiles.ts`, `useWebSocket.ts` |
| Pages | 4 | Profiles, ProxyPool, Settings, TagManager |
| Components | 17 | ProfileCard, Modals (7), Inline editors (2), Proxy (4), etc. |
| Assets | 1 | SVG/icons |

---

## Phase 3: Cloud Sync ✅

Self-hosted cfox-server with PostgreSQL + cloud sync services in cfox-local.

### cfox-server files

| File | Purpose |
|------|---------|
| `app.py` | FastAPI factory, admin bootstrap, lifespan |
| `config.py` | Pydantic settings (env vars) |
| `middleware.py` | API key authentication (HMAC-SHA256) |
| `schemas.py` | Request/response Pydantic schemas |
| `routes/profiles.py` | Cloud profile CRUD |
| `routes/locks.py` | Lock acquire/release/heartbeat |
| `routes/storage.py` | Essential data upload/download/versions |
| `routes/users.py` | User management (admin) |
| `services/lock_service.py` | Background lock cleanup |
| `services/storage_service.py` | File storage + version rotation |

### Cloud services in cfox-local

| File | Purpose |
|------|---------|
| `services/cloud_client.py` | HTTP client SDK for cfox-server |
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

## Phase 4: E2E Tests ✅

Comprehensive test suite covering all system layers.

**Files:** `tests/e2e/` (8 files, 42 tests)

| Suite | File | Tests | Execution |
|-------|------|-------|-----------|
| 1. Server API | `test_server_api.py` | 4 | In-process (ASGI) |
| 2. Local API | `test_local_api.py` | 12 | In-process (ASGI) |
| 3. Cloud Client | `test_cloud_client.py` | 8 | In-process (ASGI) |
| 4. UI Settings | `test_ui_settings.py` | 7 | Subprocess (:9600) |
| 5. UI Profiles | `test_ui_profiles.py` | 6 | Subprocess (:9600) |
| 6. Cross-System | `test_cross_system.py` | 5 | In-process (ASGI) |

**Test results:** `41 passed, 1 deselected (real_browser), 0 failed`

**Bugs fixed during testing:**
- `ProfileNotFoundError` unhandled in route handlers (500 → 404)
- Heartbeat state assertion mismatch (`"healthy"` vs `"normal"`)
- httpx `ASGITransport.app` attribute name change

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
| Lock ownership | Server validates lock_token + machine_id |
| Upload queue | Dedup by profile_id, max 3 concurrent, exp backoff |
| Heartbeat | 30s interval, graduated: warn → critical → force-close |
| Version retention | Server keeps last 3 versions, rollback API |
| Migration strategy | Auto-migrate on startup |
| Cloud cache | 30s TTL, invalidate on write |

---

## Remaining (Phase 5: Polish)

- [ ] Essential data size monitoring + cleanup suggestions
- [ ] Profile migration UI (local → cloud, cloud → local)
- [ ] Background prefetch for frequently-used cloud profiles
- [ ] WS reconnection UX polish
- [ ] Cloud UI components (source badges, lock warnings, sync status)
- [ ] CI/CD pipeline for Python tests + UI lint
- [ ] Performance optimization for large profile sets (100+)
- [ ] Dark mode theme improvements

---

## Reference Documents

| Document | Location | Content |
|----------|----------|---------|
| README | `README.md` | Full project documentation |
| Architecture | `docs/ARCHITECTURE.md` | System architecture v6 |
| Progress | `docs/PROGRESS.md` | This file — status tracker |
| Phase 3 Plan | `docs/PHASE3_PLAN.md` | Phase 3 detailed implementation plan |
| Testing | `docs/TESTING.md` | E2E test strategy and execution |
| Architecture V5 | `docs/ARCHITECTURE_V5.md` | Previous architecture version |
| Workflow | `WORKFLOW.md` | Firefox patching workflow |
