# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Camoufox?

Camoufox is an **open-source anti-detect browser** built on Firefox with robust fingerprint injection capabilities. Unlike competitors that use JavaScript injection, Camoufox intercepts fingerprinting at the **C++ implementation level**, making spoofed properties undetectable through JavaScript inspection.

**Key differentiators:**
- **Firefox-based** (not Chromium): Juggler operates at a lower level than CDP, more resistant to JS leaks, better fingerprinting resistance research
- **No JS injection**: All fingerprint spoofing happens in C++ before JavaScript can observe it
- **Crowdblending**: Uses BrowserForge for statistical fingerprint distribution matching real traffic
- **Proven stealth**: Passes DataDome, Cloudflare, Imperva, reCaptcha with high scores
- **Open core**: Most code is public; some advanced features (canvas rotation) are closed-source to prevent reverse engineering by bot detection providers

**Use case**: Web scraping, automation, and testing that requires avoiding bot detection systems while maintaining indistinguishable browser fingerprints.

## Critical Context: Dual Repository Structure

**Camoufox uses TWO git repositories:**

1. **Outer Repo** (`/home/azureuser/camoufox/`): Tracks patches, scripts, docs, Makefile
2. **Inner Repo** (`camoufox-{version}/`): Firefox source code with full git history.  This changes depending upon what is in `upstream.sh`

The inner repo is **NOT** a submodule. It's a standalone Firefox git repository cloned from the exact commit that Playwright targets. This enables `git log`, `git blame`, and `git diff` on Firefox code to understand upstream changes.

## Repository Philosophy: Git-Based vs Tarball

**CRITICAL:** This repo uses Playwright's exact Firefox git commit, not Mozilla's release tarballs. This provides full Firefox git history for debugging upstream changes.

**Key implications:**
- `make retag-baseline` ONLY works with git repo approach (requires `unpatched^` parent)
- `make setup` is INCOMPATIBLE with git repo approach (destroys Firefox history)
- When fixing `additions/`, use `make retag-baseline` to update the baseline (or `make copy-additions` for quick syncing)

**For details, see [FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md)**

## Essential Commands

```bash
# Patch workflow
make revert                              # Start fresh from baseline
make patch patches/foo.patch             # Apply single patch
make dir                                 # Apply all patches
make tagged-checkpoint                   # Save checkpoint
make revert-checkpoint                   # Return to checkpoint
python3 scripts/next_patch.py <patch>    # Find next patch alphabetically

# Building & running
make bootstrap                           # Bootstrap build environment (first time)
make build                               # Build Firefox
make run                                 # Run built browser
make run args="--headless https://..."   # Run headless

# Additions management
make copy-additions                      # Copy additions/ to source (fast, no git operations)
make retag-baseline                      # Rebuild 'unpatched' tag with updated additions/ (full git reset)

# Development
make edits                               # Open developer UI (patch manager)
make edit-cfg                            # Edit camoufox.cfg
make ff-dbg                              # Setup vanilla Firefox for debugging

# Release builds
python3 multibuild.py --target linux windows macos --arch x86_64 arm64           # Sequential (default)
python3 multibuild.py --target linux windows macos --arch x86_64 arm64 --parallel # Parallel (faster)
```

**Note:** `--parallel` builds multiple targets concurrently with isolated mozconfigs. No conflicts, supports incremental builds.

**See [WORKFLOW.md](WORKFLOW.md) for detailed patch workflow instructions.**

## Architecture Overview

### Three-Layer Design

**Every patch exists to prevent bot detection.** Camoufox's architecture ensures fingerprints are spoofed before JavaScript can observe them:

#### Layer 1: MaskConfig System (`additions/camoucfg/`)
Header-only C++ system that injects spoofing config at compile time. Firefox's internal APIs read from MaskConfig instead of real system values. Enables spoofing:
- Navigator (userAgent, platform, hardwareConcurrency, languages, etc.)
- Screen/window dimensions, devicePixelRatio
- WebGL (renderer, vendor, parameters, extensions, shader precision)
- AudioContext (sampleRate, outputLatency, maxChannelCount)
- Geolocation, timezone, locale, Intl
- Battery API, voices, media devices

**Key insight:** Firefox's C++ code reads spoofed values from MaskConfig headers, so JavaScript sees spoofed properties natively—no runtime injection required.

#### Layer 2: Juggler (`additions/juggler/`)
Custom Playwright protocol for Firefox. Forked from Puppeteer/Juggler with critical patches:
- Sandboxed page agent JS (invisible to page context)
- No frame execution context leaks
- `navigator.webdriver` fixed
- Component registration compatible with modern Firefox (e.g., `external: False` for Firefox 142+)

**Why not CDP?** Juggler operates at a lower level than Chrome DevTools Protocol, making it harder to detect through JavaScript inspection.

#### Layer 3: Patches (`patches/`)
Applied in **alphabetical filename order** (not directory structure). Categories:
- **Fingerprint spoofing**: `webgl-spoofing.patch`, `font-hijacker.patch`, `audio-context-spoofing.patch`, `geolocation-spoofing.patch`
- **Stealth fixes**: `force-default-pointer.patch` (headless pointer detection), `shadow-root-bypass.patch`, `disable-remote-subframes.patch`
- **Debloat/optimizations**: LibreWolf patches, `no-css-animations.patch`, telemetry removal
- **Playwright integration**: `patches/playwright/*.patch` (bootstrap, leak fixes)

**Critical rule:** Patches apply alphabetically. If B depends on A, A's filename must come first.

## Fixing Broken Patches (Critical Workflow)

**Rule #1:** NEVER delete a patch without understanding its stealth goal.

When a patch fails, you MUST:
1. **Understand stealth intent**: What fingerprinting vector or bot detection does this prevent?
2. **Determine why it failed**: File moved? Code refactored? API changed?
3. **Find new location**: Search Firefox git history to see where code moved
4. **Replicate stealth goal**: Achieve same protection in new Firefox architecture

**Example stealth goals:**
- `remove-cfrprefs.patch`: Hide CFR recommendation checkboxes (disabled in camoufox.cfg but still visible = detectable mismatch)
- `force-default-pointer.patch`: Report "fine" pointer even in headless (prevents headless detection)
- `webgl-spoofing.patch`: Make MaskConfig take precedence over Firefox's RFP for WebGL (avoids fingerprint inconsistencies)

### Regenerating a Patch:
```bash
# 1. Fix code in Firefox source (inner repo)
cd camoufox-142.0.1-fork.27
vim browser/components/preferences/main.js  # Fix the code

# 2. Verify ALL hunks from original patch are recreated
git status && git diff  # Does this match the original patch's intent?

# 3. Generate new patch (ENTIRE repo diff, not selective!)
git diff > ../patches/remove-cfrprefs.patch

# 4. Test it applies cleanly
cd .. && make revert-checkpoint && make patch patches/remove-cfrprefs.patch

# 5. Commit to outer repo
git add patches/remove-cfrprefs.patch
git commit -m "Fix remove-cfrprefs for FF142 JS config migration"
```

**See [WORKFLOW.md](WORKFLOW.md) for detailed investigation guidelines and examples.**

## Common Gotchas

1. **Alphabetical patch order**: Patches apply by filename sort order (not directory). Dependencies must be encoded in filenames.

2. **Offset vs FAILED hunk**:
   - Offset/fuzz = patch applied but line numbers shifted (usually safe)
   - FAILED hunk = patch could not apply (MUST investigate stealth intent)

3. **Component registration (Firefox 142+)**: Components with `categories` + `constructor` + no `headers` default to `external: True`, which can't have constructors. Fix: `"external": False` in components.conf.

4. **Additions vs patches**:
   - **Additions** (`additions/`): Copied at baseline creation (`unpatched` tag)
   - **Patches** (`patches/`): Applied after baseline
   - If you modify `additions/`, run `make copy-additions` for quick sync or `make retag-baseline` to update baseline

5. **Two git repos**: Changes to Firefox source go in inner repo (for generating patches). Changes to patch files go in outer repo (for version control).

## Firefox Upgrade Process

**High-level steps** (see [FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md) for details):

1. Find Playwright's target commit from `browser_patches/firefox/UPSTREAM_CONFIG.sh` (use release branch)
2. Clone that exact Firefox commit with git history
3. Copy additions, commit, tag as `unpatched`
4. Apply patches with `make dir`, fix breaks one-by-one
5. Document changes in upgrade notes

**Why Playwright's commit?** Their patches expect specific line numbers from their commit. Using Mozilla's tarball causes 88+ reject files.

## Profile Management System (`src/camoufox_profiles/`)

This repo contains a **profile management layer** on top of Camoufox, built as an installable Python package with a CLI (`cfox`).

### Architecture

```
src/camoufox_profiles/
├── models.py        # Profile, DriftSchedule, DriftEvent, ProxyPoolEntry, HealthReport
├── store.py         # Async + Sync SQLite (WAL mode) with schema versioning
├── migrations.py    # V1→V2 additive schema migration engine
├── fingerprint.py   # Camoufox fingerprint capture via BrowserForge
├── launcher.py      # Browser launch with IP consistency guard + drift engine
├── drift.py         # Natural fingerprint aging (UA version, viewport, history)
├── proxy.py         # Centralized proxy pool CRUD + health checking
├── health.py        # Profile health diagnostics (5 check types)
├── batch.py         # Parallel operations via asyncio.Semaphore
├── transfer.py      # ZIP export/import with optional AES-256 (pyzipper)
├── warmup.py        # Browser warmup with popular sites
├── manager.py       # High-level API wiring all features
├── cli.py           # CLI entry point: cfox <command>
└── exceptions.py    # Custom exception hierarchy
```

### Key Design Rules

1. **IP guard ≠ drift**: The IP consistency guard is a safety mechanism for null-proxy profiles. It runs ALWAYS, even when `drift=False`.
2. **Proxy passwords excluded from exports**: Only `server` and `has_credentials` flag are exported.
3. **Fingerprint immutables**: OS, GPU, screen resolution, CPU cores, and fonts are NEVER modified after creation.
4. **Schema migrations**: Use additive `ALTER TABLE ADD COLUMN` with `_column_exists()` checks for idempotency.
5. **SQL comment stripping**: Migration parser strips `-- comment` lines before splitting by `;` to prevent multi-line CREATE TABLE corruption.

### CLI Entry Point

```bash
cfox create <name> [--os windows|macos|linux] [--proxy server] [--tag tag]
cfox list [--tag tag] [--os os]
cfox launch <name> [--headless] [--no-drift]
cfox warmup <name> [--headless]
cfox delete <name>
cfox health <name>
cfox proxy add <server> [-u user] [-p pass] [--tag tag]
cfox proxy list [--tag tag]
cfox proxy check
cfox export <name> <path> [--password secret]
cfox import <path> [--name new_name] [--password secret]
```

### Database

SQLite in WAL mode at `<base_dir>/profiles.db`. V2 schema includes:
- `profiles` — Main table with fingerprint config, drift schedule, IP tracking
- `drift_events` — Immutable audit log of all fingerprint changes
- `proxy_pool` — Centralized proxy entries with health status
- `schema_migrations` — Version tracking for additive migrations

### Testing Profile System

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run profile system tests
python -m pytest tests/ -v

# Manual CLI testing
cfox create test-1 --os windows
cfox health test-1
cfox launch test-1
```

## Desktop Server (`cfox_local/`)

FastAPI server wrapping ProfileManager with REST + WebSocket API. Entry point: `python -m cfox_local` or `cfox-local`.

### Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI factory, lifespan, CORS, static file serving |
| `config.py` | Settings, machine_id persistence, config.json |
| `session_manager.py` | BrowserSessionManager — PID tracking, crash recovery, concurrent sessions |
| `routes/*.py` | 7 route modules: profiles, browser, health, proxies, tags, server, ws |
| `services/cloud_client.py` | HTTP SDK for cfox-server (connect, CRUD, lock, upload) |
| `services/heartbeat_service.py` | Periodic heartbeat for cloud sessions (30s) |
| `services/sync_service.py` | Profile sync orchestrator (copy-before-zip) |
| `services/upload_queue.py` | Background upload queue (dedup, max 3 concurrent) |

### Running

```bash
python -m cfox_local                          # Default: http://localhost:7600
python -m cfox_local --port 7600 --no-browser # No auto-open, custom port
python -m cfox_local --tray                   # System tray mode
```

## Cloud Server (`cfox_server/`)

Self-hosted profile management server with PostgreSQL backend.

### Key Modules

| Module | Purpose |
|--------|---------|
| `app.py` | FastAPI factory, admin bootstrap, lifespan |
| `config.py` | Pydantic settings from env vars |
| `middleware.py` | API key auth (HMAC-SHA256) |
| `schemas.py` | Request/response schemas |
| `routes/profiles.py` | Cloud profile CRUD |
| `routes/locks.py` | Lock acquire/release/heartbeat |
| `routes/storage.py` | Essential data upload/download/versions |
| `routes/users.py` | User management (admin/member roles) |
| `services/lock_service.py` | Background lock cleanup |
| `services/storage_service.py` | File storage + version rotation |

### Deployment

```bash
# Docker Compose (recommended)
docker compose up -d

# Manual
pip install -e ".[server]"
python -m cfox_server
```

## Web Dashboard (`cfox_ui/`)

React + Vite + TypeScript SPA served by cfox-local.

### Pages

| Page | File | Features |
|------|------|----------|
| Profiles | `pages/Profiles.tsx` | CRUD, launch/stop, batch create, bulk edit, import |
| Proxy Pool | `pages/ProxyPool.tsx` | Proxy CRUD, bulk import, health check |
| Tag Manager | `pages/TagManager.tsx` | Tag CRUD, profile counts |
| Settings | `pages/Settings.tsx` | Storage, cloud config, system info, reset |

### Building

```bash
cd cfox_ui && npm ci && npm run build
# Output: cfox_ui/dist/ (served by cfox-local as static files)
```

## E2E Testing System

42 tests across 6 suites in `tests/e2e/`.

### Running Tests

```bash
# All E2E (fast, no real browser needed)
python -m pytest tests/e2e/ -v -m "not real_browser"

# Only API tests
python -m pytest tests/e2e/test_server_api.py tests/e2e/test_local_api.py tests/e2e/test_cloud_client.py -v

# UI tests (requires: cd cfox_ui && npm run build)
python -m pytest tests/e2e/test_ui_settings.py tests/e2e/test_ui_profiles.py -v
```

### Test Architecture

- **Suites 1-3, 6**: In-process via `httpx.ASGITransport` (no ports needed)
- **Suites 4-5**: Real subprocess on `:9600` with built UI
- Markers: `@pytest.mark.real_browser` (skip in CI), `@pytest.mark.ui`

## Key Documentation

- **[FIREFOX_UPGRADE_WORKFLOW.md](FIREFOX_UPGRADE_WORKFLOW.md)**: Why git-based approach, how `retag-baseline` and `copy-additions` work, repo-in-repo structure
- **[WORKFLOW.md](WORKFLOW.md)**: Patch investigation process, stealth intent analysis, checkpoint workflow
- **[FIREFOX_142_UPGRADE_NOTES.md](FIREFOX_142_UPGRADE_NOTES.md)**: Version-specific changes and patch fixes
- **[BUILD_FIXES_142.md](BUILD_FIXES_142.md)**: Build errors and fixes for Firefox 142 upgrade
- **[DESIGN_NOTES.md](DESIGN_NOTES.md)**: Profile system design decisions, drift engine, IP guard logic
- **[README.md](README.md)**: Full project documentation (all components)
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**: System architecture v6
- **[docs/TESTING.md](docs/TESTING.md)**: E2E test strategy and guide
- **[docs/PROGRESS.md](docs/PROGRESS.md)**: Phase completion tracker
- **`Makefile`**: Firefox build system targets

## Testing & Validation

### Firefox Build
After fixes, validate against bot detection systems:
```bash
make tests  # Run automated Playwright tests
make build && make run  # Manual testing
```

### Profile System + Full Stack
```bash
pip install -e ".[dev]"
python -m pytest tests/e2e/ -v -m "not real_browser"  # E2E (42 tests)
python -m pytest tests/ -v                              # Unit tests
cfox create test --os windows && cfox health test && cfox delete test
```

**Production testing sites:**
- WAFs: DataDome, Cloudflare (Turnstile/Interstitial), Imperva
- Fingerprinting: CreepJS, BrowserScan, Browserleaks
- Scores: reCaptcha (target: 0.9+), Incolumitas (0.8-1.0)