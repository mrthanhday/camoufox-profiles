# Implementation Plan — cfox-server Architecture v5-final

## Goal

Implement the distributed Camoufox profile management system in 4 phases, starting from wrapping the existing V2 library into a FastAPI server, then building the Web UI, then the cloud server, and finally polish.

## Phased Approach

Each phase is **independently deployable** — Phase 1 already provides a working local API replacing CLI-only usage.

---

## Phase 1: cfox-local API — Wrap V2 for Local Profiles

> **Goal:** FastAPI server that wraps existing V2 `ProfileManager` with REST + WebSocket. System tray for lifecycle management.

### Dependencies

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pystray>=0.19.0
Pillow>=10.0     # required by pystray for icon
websockets>=12.0 # FastAPI WS support
```

### 1.1 Project scaffolding

#### [NEW] `cfox_local/__init__.py`
- Empty init

#### [NEW] `cfox_local/config.py`
- `Settings` class: `host`, `port` (7600), `base_dir` (profiles path), `machine_id` (auto-generated UUID, persisted to `~/.cfox/machine_id`)
- Load from env vars or `~/.cfox/config.json`

#### [NEW] `cfox_local/app.py`
- FastAPI app factory with lifespan
- Lifespan: init `ProfileManager`, init `BrowserSessionManager`, start background tasks
- Include all route modules
- Mount static files for future UI (`cfox_ui/dist/`)
- CORS middleware for `localhost:5173` (Vite dev)

### 1.2 BrowserSessionManager

#### [NEW] `cfox_local/session_manager.py`
- **Singleton** `BrowserSessionManager` (BSM)
- Tracks running browser sessions in-memory dict: `{profile_id: BrowserSession}`
- `BrowserSession` dataclass: `profile_id`, `source` (local/cloud), `context` (Playwright BrowserContext), `browser_pid`, `started_at`, `base_version` (None for local), `lock_token` (None for local)
- `launch(profile_id, source)` → wraps V2 `ProfileManager.launch()`, registers session
- `stop(profile_id)` → close browser context, deregister
- `get_running()` → list all active sessions
- `on_disconnect(profile_id)` → crash handler (for Phase 1: just cleanup, no upload)
- **Persist** to `running_sessions` table in SQLite for crash recovery on restart
- Recovery on startup: check PIDs, ping playwright contexts, cleanup dead sessions

### 1.3 REST API Routes

#### [NEW] `cfox_local/routes/profiles.py`
- `GET /api/profiles` → list all local profiles (Phase 1: local only, Phase 3 adds cloud merge)
- `POST /api/profiles` → create profile (delegates to `ProfileManager.create_profile()`)
- `GET /api/profiles/{id}` → get profile detail
- `PUT /api/profiles/{id}` → update metadata (name, tags, notes, proxy)
- `DELETE /api/profiles/{id}` → delete profile + user_data_dir

#### [NEW] `cfox_local/routes/browser.py`
- `POST /api/profiles/{id}/launch` → BSM.launch(), emit WS event
- `POST /api/profiles/{id}/stop` → BSM.stop(), emit WS event
- `GET /api/sessions` → list running browser sessions
- `POST /api/profiles/{id}/warmup` → run warmup (background task)

#### [NEW] `cfox_local/routes/health.py`
- `GET /api/profiles/{id}/health` → delegates to V2 `ProfileManager.health_check()`
- `GET /api/profiles/{id}/drift` → drift event history from store

#### [NEW] `cfox_local/routes/proxies.py`
- `GET /api/proxies` → list local proxy pool
- `POST /api/proxies` → add proxy
- `DELETE /api/proxies/{id}` → remove proxy
- `POST /api/proxies/check` → health check all proxies

### 1.4 WebSocket Event Stream

#### [NEW] `cfox_local/routes/ws.py`
- `WS /ws/events` → WebSocket endpoint
- `EventBus` singleton: `subscribe(ws)`, `unsubscribe(ws)`, `emit(event)`
- Events: `browser_status`, `sync_status` (Phase 3), `server_connection` (Phase 3)
- BSM calls `EventBus.emit()` on launch/stop/crash

### 1.5 System Tray

#### [NEW] `cfox_local/tray.py`
- pystray icon with menu: "Open UI", "Quit"
- "Open UI" → open default browser to `http://localhost:7600`
- "Quit" → check BSM for running browsers, prompt if any, then shutdown uvicorn

#### [NEW] `cfox_local/__main__.py`
- Entry point: start uvicorn in background thread, start tray in main thread
- Or: `cfox-local` console script for development (no tray)

#### [MODIFY] `pyproject.toml`
- Add `cfox-local` entry point
- Add new dependencies (fastapi, uvicorn, pystray, Pillow)

### 1.6 Verification

- `cfox-local` starts on port 7600
- `GET /api/profiles` returns existing local profiles
- `POST /api/profiles` creates profile with fingerprint
- `POST /api/profiles/{id}/launch` opens Camoufox browser
- `POST /api/profiles/{id}/stop` closes browser
- `GET /api/sessions` shows running sessions
- WebSocket `/ws/events` streams status changes
- System tray icon appears, "Open UI" works
- Process crash → restart → dead sessions cleaned up

---

## Phase 2: Web UI (React + Vite)

> **Goal:** Dashboard UI served by cfox-local as static files.

### 2.1 Scaffolding

#### [NEW] `cfox_ui/` — Vite + React + TypeScript project
- `npx -y create-vite@latest ./ --template react-ts`
- Custom CSS (no Tailwind unless requested)
- Dark theme, modern design (glassmorphism, subtle animations)
- Google Fonts: Inter

### 2.2 Core Components

#### [NEW] `cfox_ui/src/hooks/useWebSocket.ts`
- Connect to `ws://localhost:7600/ws/events`
- Auto-reconnect with exponential backoff
- Debounce burst events (150ms per profile_id)
- On reconnect: full state refresh via REST

#### [NEW] `cfox_ui/src/hooks/useProfiles.ts`
- Fetch profiles from REST API
- Merge with WS real-time updates
- Expose: `profiles`, `launchProfile()`, `stopProfile()`, `isLoading`

#### [NEW] `cfox_ui/src/pages/Profiles.tsx`
- Profile list with cards (name, status badge, source icon, tags)
- Launch/stop button with loading states
- Search + filter by tag, status, source
- Create profile dialog

#### [NEW] `cfox_ui/src/pages/ProfileDetail.tsx`
- Health report display (✓ ⚠ ✗)
- Drift event timeline
- Edit metadata (name, tags, notes)
- Proxy binding

#### [NEW] `cfox_ui/src/pages/ProxyPool.tsx`
- Proxy list with health indicators
- Add/remove proxies
- Health check button

#### [NEW] `cfox_ui/src/pages/Settings.tsx`
- Server connection (Phase 3 placeholder)
- Base directory path
- Machine ID display

#### [NEW] `cfox_ui/src/components/`
- `ProfileCard.tsx` — card with status badge, source icon
- `LaunchButton.tsx` — launch/stop with loading spinner
- `SyncIndicator.tsx` — upload/download progress (Phase 3)
- `HealthBadge.tsx` — severity badge (pass/warn/fail)

### 2.3 Build Integration

#### [MODIFY] `cfox_local/app.py`
- Serve `cfox_ui/dist/` as static files when built
- Fallback: redirect to Vite dev server URL in dev mode

### 2.4 Verification

- `npm run build` in cfox_ui → static files
- cfox-local serves UI at `http://localhost:7600`
- Profile list loads, real-time status updates via WS
- Launch/stop browser from UI
- Health check display works

---

## Phase 3: cfox-server + Cloud Sync

> **Goal:** PostgreSQL cloud backend, lock protocol, essential data sync between machines.

### 3.1 cfox-server Setup

#### [NEW] `cfox_server/__init__.py`
#### [NEW] `cfox_server/app.py` — FastAPI app with lifespan (asyncpg pool)
#### [NEW] `cfox_server/config.py` — DB URL, storage path, API keys
#### [NEW] `cfox_server/db.py` — asyncpg connection pool, schema migration

#### [NEW] `cfox_server/routes/auth.py`
- `POST /api/auth/verify` → validate API key
- Middleware: validate `Authorization: Bearer sk-...` on all endpoints
- Track `last_used_at` for each API key

#### [NEW] `cfox_server/routes/profiles.py`
- CRUD for cloud profiles (PostgreSQL)
- `PUT /api/profiles/{id}` requires `If-Match` header

#### [NEW] `cfox_server/routes/locks.py`
- `POST /api/profiles/{id}/lock` → acquire lock, return `{lock_token, previous_lock}`
- `PUT /api/profiles/{id}/heartbeat` → extend TTL, validate lock_token + machine_id
- `DELETE /api/profiles/{id}/lock` → release, validate ownership
- `DELETE /api/profiles/{id}/lock/force` → admin force-unlock

#### [NEW] `cfox_server/routes/storage.py`
- `GET /api/profiles/{id}/essential_data` → download ZIP + Content-SHA256 header
- `PUT /api/profiles/{id}/essential_data` → upload ZIP, requires If-Match + Content-SHA256 + lock_token
- `GET /api/profiles/{id}/essential_data/info` → version, size, checksum
- `GET /api/profiles/{id}/essential_data/versions` → retained versions list
- `POST /api/profiles/{id}/essential_data/rollback/{version}` → rollback

#### [NEW] `cfox_server/routes/proxies.py`
- Cloud proxy pool CRUD

#### [NEW] `cfox_server/services/lock_service.py`
- TTL expiry background task (check every 60s, cleanup expired locks)
- Lock validation: token + machine_id
- previous_lock info from last_heartbeat_at

#### [NEW] `cfox_server/services/storage_service.py`
- Filesystem backend (S3 backend deferred)
- Version rotation: keep last 3, delete oldest on upload
- Checksum storage + validation

#### [NEW] `cfox_server/Dockerfile`

### 3.2 cfox-local Cloud Integration

#### [NEW] `cfox_local/services/cloud_client.py`
- HTTP client (httpx) for cfox-server API
- Auth header injection
- Retry on 5xx (3 retries, exponential backoff)
- Connection health ping

#### [NEW] `cfox_local/services/sync_service.py`
- `collect_essential_data()` — copy-before-zip pattern
- `restore_essential_data()` — clean extract + cache clear
- `upload_essential_data()` — with If-Match + Content-SHA256
- `download_essential_data()` — with checksum verification
- `ESSENTIAL_PATTERNS` constant

#### [NEW] `cfox_local/services/upload_queue.py`
- Deduplicated queue by profile_id
- Semaphore max 3 concurrent
- Exponential backoff: `min(2^attempt, 300)`, max 5 retries
- Emit WS events on progress/failure

#### [NEW] `cfox_local/services/heartbeat_service.py`
- Background task per cloud session: heartbeat every 30s
- Graduated failure handling: 60s warning, 150s red warning, 300s kill
- Kill browser → enqueue upload → emit WS event

#### [MODIFY] `cfox_local/session_manager.py`
- Cloud launch: lock → download → restore → launch → heartbeat
- Cloud stop: stop heartbeat → close browser → collect → upload → update metadata → unlock
- Crash handler: try upload → enqueue retry if fail
- `sync_incomplete` detection on next launch

#### [MODIFY] `cfox_local/routes/profiles.py`
- Merge local + cloud profiles in list
- Route by `source` query param

#### [NEW] `cfox_local/routes/server.py`
- `GET /api/server/status` → connection status
- `POST /api/server/connect` → {url, api_key}
- `POST /api/server/disconnect` → disable cloud

#### [MODIFY] `cfox_local/routes/proxies.py`
- Cloud primary when connected, local fallback
- Promote/demote endpoints

### 3.3 Database Migration

#### [MODIFY] PostgreSQL schema
- Apply schema from architecture (profiles, drift_events, proxy_pool, api_keys tables)
- Include: essential_data_checksum, sync_incomplete, last_heartbeat_at

#### [MODIFY] Local SQLite
- Add `running_sessions` table for BSM crash recovery (Phase 1 prep, but essential for Phase 3)

### 3.4 Verification

- cfox-server starts, accepts API key auth
- Create cloud profile from UI
- Launch cloud profile: lock → download → browser opens
- Close cloud profile: upload → unlock
- Second machine: sees lock, cannot launch (423)
- Force unlock → second machine launches → first machine gets killed after 5 min
- Concurrent modify: 409 Conflict → UI dialog
- Browser crash → auto-upload → unlock
- cfox-local restart → recover running sessions
- Checksum mismatch → download rejected
- Version rollback works (last 3 versions)

---

## Phase 4: Polish

> **Goal:** Production hardening and UX improvements.

- Essential data size monitoring + warning thresholds
- Selective cleanup UI (show origins by size, user picks which to remove)
- Profile migration (local → cloud, cloud → local)
- Background prefetch for frequently-used cloud profiles
- WS reconnection UX polish (connection status indicator)

---

## Open Questions

> None. All architectural decisions have been made and reviewed through 3 rounds of external review + 1 self-review.

## Verification Plan

### Automated Tests
- Unit tests for `sync_service.py` (collect, restore, checksum)
- Unit tests for `upload_queue.py` (dedup, backoff, max retries)
- Unit tests for `lock_service.py` (TTL, ownership, race detection)
- Integration test: launch → stop → upload → download → verify data integrity

### Manual Verification
- Multi-machine handover: Machine A launch → Machine B tries → lock blocks → A closes → B launches with A's cookies
- Network interruption: disconnect WiFi → observe graduated warnings → reconnect → browser survives
- Crash simulation: kill browser process → BSM detects → uploads → unlocks
- Force-push conflict: A and B both modify → 409 → semantic dialog
