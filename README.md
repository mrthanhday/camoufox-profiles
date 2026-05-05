# camoufox-profiles

Persistent antidetect browser profile management for [Camoufox](https://camoufox.com/) (coryking fork, Firefox 142).

Each profile maintains a **consistent fingerprint** across sessions — same device identity, same browsing history, same cookies — with **natural aging** via the drift engine.

## Installation

```bash
pip install -e ".[dev]"

# Optional: encrypted export/import
pip install -e ".[crypto]"
```

## Quick Start

### CLI (`cfox`)

```bash
# Create a profile
cfox create shop-account-1 --os windows --tag ecommerce

# Warmup — build natural browsing history
cfox warmup shop-account-1

# Launch — same fingerprint every time, with drift
cfox launch shop-account-1

# Health diagnostics
cfox health shop-account-1

# List all profiles
cfox list --tag ecommerce

# Proxy pool management
cfox proxy add http://us-proxy.example.com:8080 -u user -p pass --tag us
cfox proxy list
cfox proxy check

# Export / Import
cfox export shop-account-1 ./backup.zip --password mysecret
cfox import ./backup.zip --name restored-account
```

### Async API

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
    print(f"Created: {profile.name} ({profile.id})")

    # Warmup — build natural browsing history
    report = await pm.warmup(profile.id)
    print(f"Warmup: {report.successful_visits}/{report.total_visits} sites visited")

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

### Sync API

```python
from camoufox_profiles import ProfileManagerSync, ProxyConfig

pm = ProfileManagerSync("./my_profiles")
pm.initialize()

profile = pm.create_profile(name="test-1", os="windows")

with pm.launch(profile.id) as context:
    page = context.new_page()
    page.goto("https://example.com")

pm.close()
```

## Key Concepts

### Fingerprint Persistence

When a profile is created, a complete Camoufox fingerprint is generated (via BrowserForge) and **saved permanently**. This includes:

- Navigator properties (UA, platform, hardware concurrency, etc.)
- Screen dimensions and color depth
- WebGL vendor/renderer and shader precision
- Canvas and audio fingerprint seeds
- Font list matching the target OS
- Timezone, locale, and geolocation (from proxy IP)

Every subsequent launch replays this exact configuration.

### Natural Drift (V2)

Profiles age naturally over time to avoid "frozen fingerprint" detection:

- **UA version drift**: Firefox version bumps to match the installed Camoufox binary (e.g. 135 → 142)
- **Viewport jitter**: ±3px randomization on window dimensions
- **History length**: Natural variation between 1-8 entries
- **Schedule tracking**: Per-profile drift schedule with configurable intervals

Immutable properties (OS, GPU, screen resolution, CPU cores, fonts) are **never** drifted.

Setting `drift=False` disables cosmetic drift but **never** disables the IP safety guard.

### IP Consistency Guard (V2)

For null-proxy profiles (using local IP), the launcher automatically:

1. Checks the current public IP region against the stored creation region
2. If the region changed (e.g. VPN switched), recalculates all geo properties (timezone, locale, coordinates, WebRTC IP)
3. Logs the change as a drift event for auditing

This prevents anti-bot detection from seeing "timezone says US, IP says Germany".

### Storage Persistence

Each profile uses Playwright's persistent context with its own `user_data_dir`, preserving:

- Cookies and session tokens
- localStorage and IndexedDB
- Browser cache and service workers
- CSS `:visited` history

### Proxy Pool (V2)

Centralized proxy management with database-driven health tracking:

- Add/remove proxies with tags for organization
- Automatic health checking with latency measurement
- Bind proxies to profiles via `proxy_id`
- Optional auto-rotation from tagged pools

### Health Diagnostics (V2)

Comprehensive profile health checks:

| Check | Severity | Description |
|-------|----------|-------------|
| UA staleness | warning/critical | Profile's Firefox version vs installed version |
| IP region mismatch | critical | Current IP region vs stored region (null-proxy) |
| Proxy health | critical | Proxy responsiveness and IP resolution |
| Data directory | warning | Browser data directory exists and has content |
| Drift schedule | info | Drift configuration and schedule status |

### Export / Import (V2)

Profiles can be exported to ZIP archives containing fingerprint config, drift schedule, and browser data. Optional AES-256 encryption via `pyzipper`.

Proxy passwords are **excluded** from exports for security.

## API Reference

### `ProfileManager(base_dir)`

| Method | Description |
|--------|-------------|
| `initialize()` | Create database and directories |
| `create_profile(name, os, proxy, proxy_id, ...)` | Create profile with persistent fingerprint |
| `launch(profile_id, drift, headless, ...)` | Launch browser (async context manager) |
| `warmup(profile_id, extra_urls, ...)` | Build browsing history |
| `health_check(profile_id)` | Run health diagnostics |
| `batch_health_check(profile_ids, concurrency)` | Parallel health check |
| `get_drift_history(profile_id)` | Get drift event audit log |
| `update_drift_schedule(profile_id, ...)` | Configure drift behavior |
| `add_proxy(server, username, password, tags)` | Add proxy to pool |
| `list_proxies(tag, alive_only)` | List proxy pool entries |
| `check_proxies(concurrency)` | Health-check all proxies |
| `bind_proxy(profile_id, proxy_id)` | Bind proxy to profile |
| `export_profile(profile_id, output_path, password)` | Export to ZIP |
| `import_profile(zip_path, new_name, password)` | Import from ZIP |
| `get_profile(profile_id)` | Get profile by ID |
| `get_profile_by_name(name)` | Get profile by name |
| `list_profiles(tag, os, search, ...)` | List profiles with filters |
| `update_profile(profile_id, ...)` | Update name/tags/notes |
| `delete_profile(profile_id)` | Delete profile + browser data |
| `count_profiles()` | Count profiles |
| `close()` | Close database connection |

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

## Architecture

```
src/camoufox_profiles/
├── models.py       # Profile, DriftSchedule, ProxyPoolEntry, HealthReport
├── store.py        # Async + Sync SQLite (WAL mode) with schema migration
├── migrations.py   # V1→V2 schema migration engine
├── fingerprint.py  # Camoufox fingerprint capture via BrowserForge
├── launcher.py     # Browser launch with IP guard + drift integration
├── drift.py        # Natural fingerprint aging engine
├── proxy.py        # Centralized proxy pool management
├── health.py       # Profile health diagnostics
├── batch.py        # Parallel operations (warmup, health check)
├── transfer.py     # ZIP export/import with optional AES-256
├── warmup.py       # Browser warmup with popular sites
├── manager.py      # High-level API orchestrating all features
├── cli.py          # CLI entry point (cfox)
└── exceptions.py   # Custom exception hierarchy
```
