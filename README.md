# 🦊 camoufox-profiles

Persistent antidetect browser profile management for [Camoufox](https://camoufox.com/) — a stealthy Firefox fork (v142). Full-stack system: **Core Library** + **Local Server** + **Cloud Server** + **Web Dashboard**.

Each profile maintains a **consistent fingerprint** across sessions — same device identity, same browsing history, same cookies — with **natural aging** via the drift engine.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        cfox-ui (React)                          │
│  Profiles │ Proxy Pool │ Tag Manager │ Settings                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST + WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     cfox-local (FastAPI)                         │
│  Profile CRUD │ Browser Sessions │ Proxy Pool │ Health │ Tags   │
│  Session Manager │ Sync Service │ Upload Queue │ Heartbeat      │
└──────┬─────────────────────┬────────────────────────────────────┘
       │ SQLite (local)      │ HTTPS (cloud sync)
       ▼                     ▼
┌──────────────┐  ┌──────────────────────────────────────────────┐
│ camoufox_    │  │            cfox-server (FastAPI)              │
│ profiles     │  │  Profile Store │ Lock Service │ Storage       │
│ (Core Lib)   │  │  User Mgmt │ Essential Data │ Version Ctrl   │
│              │  │  PostgreSQL + File Storage                    │
└──────────────┘  └──────────────────────────────────────────────┘
```

### Components

| Component | Tech | Port | Purpose |
|-----------|------|------|---------|
| `camoufox_profiles` | Python library | — | Core: fingerprint, drift, proxy, health, warmup, export |
| `cfox-local` | FastAPI + Uvicorn | 7600 | Desktop launcher: browser sessions, settings, UI server |
| `cfox-server` | FastAPI + PostgreSQL | 8700 | Cloud: profile sync, locking, version control, multi-user |
| `cfox-ui` | React + Vite + TypeScript | — | Web dashboard (built & served by cfox-local) |

---

## Installation

### Quick Start (recommended)

```powershell
# Windows (PowerShell)
.\scripts\setup-dev.ps1
```

```bash
# Linux / macOS
bash scripts/setup-dev.sh
```

### Manual

```bash
# Step 1: Install stable Playwright wheel (avoids source-build SSL issue)
pip install playwright==1.52.0

# Step 2: Editable install (Playwright will be upgraded from the fork)
pip install -e ".[dev]"

# Step 3: Install browser binaries
python -m playwright install
```

### Optional extras

```bash
pip install -e ".[crypto]"    # Encrypted export/import (AES-256)
pip install -e ".[tray]"      # System tray icon (Windows/macOS)
pip install -e ".[server]"    # cfox-server dependencies (PostgreSQL)
```

---

## Usage

### 1. CLI (`cfox`)

```bash
# Profile management
cfox create shop-account-1 --os windows --tag ecommerce
cfox launch shop-account-1        # Same fingerprint every time
cfox warmup shop-account-1        # Build natural browsing history
cfox health shop-account-1        # Run health diagnostics
cfox list --tag ecommerce

# Proxy pool
cfox proxy add http://us-proxy.example.com:8080 -u user -p pass --tag us
cfox proxy list
cfox proxy check

# Export / Import
cfox export shop-account-1 ./backup.zip --password mysecret
cfox import ./backup.zip --name restored-account
```

### 2. Desktop App (`cfox-local`)

```bash
# Console mode
python -m cfox_local

# With system tray
python -m cfox_local --tray

# Custom settings
python -m cfox_local --port 7600 --base-dir ~/my-profiles --no-browser
```

Then open **http://localhost:7600** for the Web Dashboard.

### 3. Cloud Server (`cfox-server`)

```bash
# Using Docker Compose (recommended)
cp .env.example .env
# Edit .env with your passwords
docker compose up -d

# Manual
pip install -e ".[server]"
python -m cfox_server
```

See [Server Deployment](#server-deployment) for production setup.

### 4. Python API

```python
import asyncio
from camoufox_profiles import ProfileManager, ProxyConfig

async def main():
    pm = ProfileManager("./my_profiles")
    await pm.initialize()

    # Create a profile (fingerprint is generated and saved)
    profile = await pm.create_profile(
        name="shop-account-1",
        os="windows",
        proxy=ProxyConfig(
            server="http://us-proxy.example.com:8080",
            username="user",
            password="pass",
        ),
    )

    # Warmup — build natural browsing history
    report = await pm.warmup(profile.id)

    # Launch — same fingerprint every time, with drift
    async with pm.launch(profile.id) as context:
        page = await context.new_page()
        await page.goto("https://browserscan.net")
        input("Press Enter to close...")

    # Health check
    health = await pm.health_check(profile.id)
    print(f"Health: {health.status}")

    await pm.close()

asyncio.run(main())
```

#### Sync API

```python
from camoufox_profiles import ProfileManagerSync

pm = ProfileManagerSync("./my_profiles")
pm.initialize()

profile = pm.create_profile(name="test-1", os="windows")

with pm.launch(profile.id) as context:
    page = context.new_page()
    page.goto("https://example.com")

pm.close()
```

---

## Key Concepts

### Fingerprint Persistence

When a profile is created, a complete Camoufox fingerprint is generated (via BrowserForge) and **saved permanently**:

- Navigator properties (UA, platform, hardware concurrency, etc.)
- Screen dimensions and color depth
- WebGL vendor/renderer and shader precision
- Canvas and audio fingerprint seeds
- Font list matching the target OS
- Timezone, locale, and geolocation (from proxy IP)

Every subsequent launch replays this exact configuration.

### Natural Drift

Profiles age naturally over time to avoid "frozen fingerprint" detection:

- **UA version drift**: Firefox version bumps to match the installed Camoufox binary
- **Viewport jitter**: ±3px randomization on window dimensions
- **History length**: Natural variation between 1-8 entries
- **Schedule tracking**: Per-profile drift schedule with configurable intervals

Immutable properties (OS, GPU, screen resolution, CPU cores, fonts) are **never** drifted.

### IP Consistency Guard

For null-proxy profiles (using local IP), the launcher automatically:

1. Checks the current public IP region against the stored creation region
2. If the region changed, recalculates all geo properties (timezone, locale, coordinates)
3. Logs the change as a drift event for auditing

### Cloud Sync (Phase 3)

Multi-machine profile sync via self-hosted `cfox-server`:

- **Lock-based concurrency**: Only one machine can use a profile at a time
- **Essential data**: Cookies, localStorage, session tokens synced automatically
- **Version control**: Server keeps last 3 versions with rollback support
- **Heartbeat monitoring**: Graduated health states (healthy → warn → critical)
- **Upload queue**: Dedup by profile_id, max 3 concurrent, exponential backoff

### Proxy Pool

Centralized proxy management with database-driven health tracking:

- Add/remove proxies with tags for organization
- Automatic health checking with latency measurement
- Bind proxies to profiles via `proxy_id`

### Health Diagnostics

| Check | Severity | Description |
|-------|----------|-------------|
| UA staleness | warning/critical | Profile's Firefox version vs installed version |
| IP region mismatch | critical | Current IP region vs stored region (null-proxy) |
| Proxy health | critical | Proxy responsiveness and IP resolution |
| Data directory | warning | Browser data directory exists and has content |
| Drift schedule | info | Drift configuration and schedule status |

---

## Web Dashboard

The `cfox-ui` provides a hacker-themed web dashboard with 4 pages:

| Page | Features |
|------|----------|
| **Profiles** | CRUD, launch/stop browser, health check, batch create, bulk edit, import/export, inline proxy editing |
| **Proxy Pool** | Add/remove/check proxies, bulk import, tag filtering, health status |
| **Tag Manager** | Create/rename/delete tags, profile counts, batch operations |
| **Settings** | Storage path, directory browser, max tags config, cloud settings, system info, danger zone reset |

Real-time updates via WebSocket — browser status changes reflect instantly.

---

## Server Deployment

### Docker Compose (recommended)

```bash
cp .env.example .env
# Edit .env:
#   POSTGRES_PASSWORD=your-secure-password
#   ADMIN_API_KEY=your-api-key
#   SERVER_PORT=8700

docker compose up -d
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://cfox:cfox@localhost:5432/cfox` | PostgreSQL connection |
| `STORAGE_DIR` | `data/essential_data` | Essential data file storage |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8700` | Server port |
| `LOCK_TTL_MINUTES` | `120` | Lock auto-expire time |
| `MAX_VERSIONS` | `3` | Essential data version retention |
| `ADMIN_API_KEY` | _(auto-generated)_ | Initial admin API key |

### Connecting cfox-local to cfox-server

```bash
# Set in environment or ~/.cfox/config.json
export CFOX_SERVER_URL=http://your-server:8700
export CFOX_SERVER_API_KEY=your-api-key

python -m cfox_local
```

---

## Testing

### E2E Test Suites

The project includes a comprehensive E2E test suite (42 tests across 6 suites):

| Suite | File | Tests | Description |
|-------|------|-------|-------------|
| 1 | `test_server_api.py` | 4 | Server API: search, pagination, lock expiry, version rotation |
| 2 | `test_local_api.py` | 12 | Local API: info, settings, browse, CRUD, tags, sessions |
| 3 | `test_cloud_client.py` | 8 | Cloud client: connect, CRUD, lock, retry, cache |
| 4 | `test_ui_settings.py` | 7 | Settings UI: sections, machine ID, max tags, directory browser |
| 5 | `test_ui_profiles.py` | 6 | Profiles UI: empty state, CRUD, sidebar navigation |
| 6 | `test_cross_system.py` | 5 | Cross-system: server status, connect, launch flow, heartbeat |

### Running Tests

```bash
# All tests (fast — excludes real browser)
python -m pytest tests/e2e/ -v -m "not real_browser"

# Only API tests (no subprocess needed)
python -m pytest tests/e2e/test_server_api.py tests/e2e/test_local_api.py tests/e2e/test_cloud_client.py -v

# Only UI tests (requires: cd cfox_ui && npm run build)
python -m pytest tests/e2e/test_ui_settings.py tests/e2e/test_ui_profiles.py -v

# Full suite including real browser launch
python -m pytest tests/e2e/ -v
```

### Test Architecture

- **Suites 1-3, 6**: In-process via ASGI transport (fast, no ports)
- **Suites 4-5**: Real subprocess on `:9600` with built UI served as static files
- **`@pytest.mark.real_browser`**: Tests requiring actual Camoufox binary (skippable in CI)
- **`@pytest.mark.ui`**: Tests requiring built UI + subprocess server

---

## API Reference

### Core Library (`ProfileManager`)

| Method | Description |
|--------|-------------|
| `initialize()` | Create database and directories |
| `create_profile(name, os, proxy, ...)` | Create profile with persistent fingerprint |
| `launch(profile_id, drift, headless, ...)` | Launch browser (async context manager) |
| `warmup(profile_id, extra_urls, ...)` | Build browsing history |
| `health_check(profile_id)` | Run health diagnostics |
| `batch_health_check(profile_ids)` | Parallel health check |
| `get_drift_history(profile_id)` | Get drift event audit log |
| `add_proxy(server, username, password, tags)` | Add proxy to pool |
| `list_proxies(tag, alive_only)` | List proxy pool entries |
| `check_proxies(concurrency)` | Health-check all proxies |
| `export_profile(profile_id, output_path, password)` | Export to ZIP |
| `import_profile(zip_path, new_name, password)` | Import from ZIP |
| `list_profiles(tag, os, search, ...)` | List profiles with filters |
| `delete_profile(profile_id)` | Delete profile + browser data |

### cfox-local REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/info` | GET | System info (machine_id, hostname, version) |
| `/api/settings` | GET/PUT | Application settings |
| `/api/settings/browse` | GET | Directory browser |
| `/api/settings/drives` | GET | Available drives |
| `/api/profiles` | GET/POST | List/create profiles |
| `/api/profiles/{id}` | GET/PUT/DELETE | Profile CRUD |
| `/api/profiles/{id}/launch` | POST | Launch browser |
| `/api/profiles/{id}/stop` | POST | Stop browser |
| `/api/sessions` | GET | Active browser sessions |
| `/api/profiles/{id}/health` | GET | Health check |
| `/api/proxies` | GET/POST | Proxy pool management |
| `/api/tags` | GET/POST | Tag management |
| `/api/ws` | WS | Real-time events |

### cfox-server REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server health check |
| `/api/profiles` | GET/POST | Cloud profile CRUD |
| `/api/profiles/{id}` | GET/PUT/DELETE | Profile operations |
| `/api/profiles/{id}/lock` | POST | Acquire lock |
| `/api/profiles/{id}/unlock` | POST | Release lock |
| `/api/profiles/{id}/heartbeat` | POST | Heartbeat for lock renewal |
| `/api/profiles/{id}/essential` | GET/POST | Essential data upload/download |
| `/api/profiles/{id}/versions` | GET | Version history |
| `/api/profiles/{id}/rollback` | POST | Rollback to previous version |
| `/api/users` | GET/POST | User management (admin) |

### CLI Commands

| Command | Description |
|---------|-------------|
| `cfox create <name>` | Create profile with fresh fingerprint |
| `cfox list` | List profiles with filters |
| `cfox launch <name>` | Launch browser interactively |
| `cfox warmup <name>` | Warmup with popular sites |
| `cfox delete <name>` | Delete profile and browser data |
| `cfox health <name>` | Run health diagnostics |
| `cfox proxy add <server>` | Add proxy to pool |
| `cfox proxy list` | List proxies in pool |
| `cfox proxy check` | Health-check all proxies |
| `cfox export <name> <path>` | Export to ZIP archive |
| `cfox import <path>` | Import from ZIP archive |

---

## Project Structure

```
camoufox-profiles/
├── src/camoufox_profiles/      # Core library (17 modules)
│   ├── models.py               #   Profile, DriftSchedule, ProxyPoolEntry, HealthReport
│   ├── store.py                #   Async + Sync SQLite (WAL mode)
│   ├── store_sa.py             #   SQLAlchemy store (PostgreSQL)
│   ├── models_sa.py            #   SQLAlchemy ORM models
│   ├── db.py                   #   Database engine factory
│   ├── migrations.py           #   Schema migration engine
│   ├── fingerprint.py          #   Camoufox fingerprint via BrowserForge
│   ├── launcher.py             #   Browser launch + IP guard + drift
│   ├── drift.py                #   Natural fingerprint aging engine
│   ├── proxy.py                #   Centralized proxy pool management
│   ├── health.py               #   Profile health diagnostics
│   ├── batch.py                #   Parallel operations
│   ├── transfer.py             #   ZIP export/import + AES-256
│   ├── warmup.py               #   Browser warmup with popular sites
│   ├── manager.py              #   High-level API orchestrator
│   ├── cli.py                  #   CLI entry point (cfox)
│   └── exceptions.py           #   Custom exception hierarchy
│
├── cfox_local/                 # Desktop server (7 modules + 7 routes)
│   ├── app.py                  #   FastAPI factory, lifespan, CORS
│   ├── config.py               #   Settings, machine_id persistence
│   ├── session_manager.py      #   BrowserSessionManager (launch/stop/recover)
│   ├── tray.py                 #   System tray (pystray)
│   ├── __main__.py             #   Entry point (console + tray)
│   ├── routes/
│   │   ├── profiles.py         #     Profile CRUD
│   │   ├── browser.py          #     Launch/stop/sessions
│   │   ├── health.py           #     Health check + drift
│   │   ├── proxies.py          #     Local proxy pool
│   │   ├── tags.py             #     Tag management
│   │   ├── server.py           #     Cloud server status
│   │   └── ws.py               #     EventBus + WebSocket
│   └── services/
│       ├── cloud_client.py     #     CloudClient (cfox-server SDK)
│       ├── heartbeat_service.py#     Lock heartbeat monitoring
│       ├── sync_service.py     #     Profile sync orchestrator
│       └── upload_queue.py     #     Background upload queue
│
├── cfox_server/                # Cloud server (4 routes + 2 services)
│   ├── app.py                  #   FastAPI factory, admin bootstrap
│   ├── config.py               #   Pydantic settings (env vars)
│   ├── middleware.py           #   API key auth middleware
│   ├── schemas.py              #   Request/response schemas
│   ├── routes/
│   │   ├── profiles.py         #     Cloud profile CRUD
│   │   ├── locks.py            #     Lock acquire/release/heartbeat
│   │   ├── storage.py          #     Essential data upload/download
│   │   └── users.py            #     User management
│   └── services/
│       ├── lock_service.py     #     Lock cleanup background task
│       └── storage_service.py  #     File storage + version rotation
│
├── cfox_ui/                    # Web dashboard (React + Vite + TS)
│   └── src/
│       ├── App.tsx             #   Sidebar layout + routing
│       ├── api.ts              #   Typed REST client
│       ├── hooks/
│       │   ├── useProfiles.ts  #     Profile state + WS live updates
│       │   └── useWebSocket.ts #     Auto-reconnect WebSocket
│       ├── pages/
│       │   ├── Profiles.tsx    #     Profile list + actions
│       │   ├── ProxyPool.tsx   #     Proxy management
│       │   ├── Settings.tsx    #     Application settings
│       │   └── TagManager.tsx  #     Tag CRUD
│       └── components/         #   17 reusable components
│
├── tests/
│   ├── e2e/                    # E2E test suites (42 tests)
│   │   ├── conftest.py         #   Fixtures: ASGI transport + subprocess
│   │   ├── test_server_api.py  #   Suite 1: Server API
│   │   ├── test_local_api.py   #   Suite 2: Local API
│   │   ├── test_cloud_client.py#   Suite 3: Cloud client
│   │   ├── test_ui_settings.py #   Suite 4: Settings UI
│   │   ├── test_ui_profiles.py #   Suite 5: Profiles UI
│   │   └── test_cross_system.py#   Suite 6: Cross-system
│   ├── test_fingerprint.py     # Unit: fingerprint generation
│   ├── test_store.py           # Unit: SQLite store
│   └── test_warmup.py          # Unit: warmup engine
│
├── scripts/                    # Build & dev scripts
├── patches/                    # Firefox stealth patches
├── additions/                  # Firefox additions (juggler, camoucfg)
├── bundle/                     # Fonts & configs for packaging
│
├── Makefile                    # Firefox build system (fetch, patch, build, package)
├── multibuild.py               # Multi-target build orchestrator
├── docker-compose.yml          # cfox-server + PostgreSQL
├── Dockerfile.server           # cfox-server container
├── pyproject.toml              # Python packaging config
└── .github/workflows/
    ├── build.yml               # Firefox cross-platform build & release
    └── ci.yml                  # Python tests + UI lint
```

---

## License

[Business Source License (BSL)](LICENSE)
