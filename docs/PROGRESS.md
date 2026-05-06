# cfox-server — Progress & Phase 3-4 Roadmap

> Last updated: 2026-05-06

## Completed

### ✅ Phase 1: cfox-local API
FastAPI server wrapping V2 `ProfileManager` with REST + WebSocket.

**Files:** `cfox_local/` (11 files)
- `app.py` — FastAPI factory, lifespan, CORS, static mount
- `config.py` — Settings, machine_id persistence
- `session_manager.py` — BrowserSessionManager singleton (launch/stop/crash/recovery)
- `tray.py` — System tray (pystray)
- `__main__.py` — Entry point (console + tray modes)
- `routes/profiles.py` — Profile CRUD
- `routes/browser.py` — Launch/stop/sessions/warmup
- `routes/health.py` — Health check + drift history
- `routes/proxies.py` — Local proxy pool
- `routes/ws.py` — EventBus + WebSocket endpoint

### ✅ Phase 2: Web UI (React + Vite)
Dashboard UI served by cfox-local as static files.

**Files:** `cfox_ui/src/` (12 files)
- `api.ts` — Typed REST client
- `hooks/useWebSocket.ts` — Auto-reconnect + debounce
- `hooks/useProfiles.ts` — Profile state + WS live updates
- `components/StatusBadge.tsx`, `ProfileCard.tsx`, `CreateProfileModal.tsx`, `HealthModal.tsx`
- `pages/Profiles.tsx`, `ProxyPool.tsx`, `Settings.tsx`
- `App.tsx` — Sidebar layout

---

## Remaining

### 🔲 Phase 3: cfox-server + Cloud Sync

> See `docs/IMPLEMENTATION_PLAN.md` §Phase 3 and `docs/ARCHITECTURE_V5.md` §3-7 for full details.

**Key deliverables:**

1. **cfox-server** (PostgreSQL backend)
   - `cfox_server/` — New FastAPI app
   - Profile CRUD + API key auth
   - Lock protocol (lock/heartbeat/unlock + TTL expiry)
   - Essential data storage (upload/download/versions/rollback)
   - Cloud proxy pool
   - Dockerfile

2. **cfox-local cloud integration**
   - `cfox_local/services/cloud_client.py` — HTTP client for cfox-server
   - `cfox_local/services/sync_service.py` — Copy-before-zip + clean extract
   - `cfox_local/services/upload_queue.py` — Deduplicated, max 3 concurrent
   - `cfox_local/services/heartbeat_service.py` — 30s heartbeat, kill after 10 fails
   - Modify `session_manager.py` — Cloud launch flow (lock→download→launch→heartbeat)
   - Modify `routes/profiles.py` — Merge local + cloud profiles
   - New `routes/server.py` — Cloud connection management

**Critical patterns to follow:**
- **Copy-Before-Zip:** Never ZIP from live `user_data_dir`
- **Clean Extract:** Delete essential files → extract (never merge)
- **Optimistic Concurrency:** `If-Match: base_version` on all uploads
- **SHA-256 Integrity:** Checksum verification on both upload and download
- **Graduated Kill:** 60s warning → 150s red → 300s kill browser

### 🔲 Phase 4: Polish

- Essential data size monitoring + cleanup suggestions
- Profile migration (local ↔ cloud)
- Background prefetch for frequently-used cloud profiles
- WS reconnection UX polish

---

## Reference Documents

| Document | Content |
|----------|---------|
| `docs/ARCHITECTURE_V5.md` | Full architecture (v5-final, 3x reviewed) |
| `docs/IMPLEMENTATION_PLAN.md` | Detailed file-by-file implementation plan |
| `docs/PROGRESS.md` | This file — status tracker |
