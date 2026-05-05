# camoufox-profiles

Persistent antidetect browser profile management for [Camoufox](https://camoufox.com/).

Each profile maintains a **consistent fingerprint** across sessions — same device identity, same browsing history, same cookies — instead of randomizing on every launch.

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

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

    # Launch — same fingerprint every time
    async with pm.launch(profile.id) as context:
        page = await context.new_page()
        await page.goto("https://browserscan.net")
        input("Press Enter to close...")

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

### Storage Persistence

Each profile uses Playwright's persistent context with its own `user_data_dir`, preserving:

- Cookies and session tokens
- localStorage and IndexedDB
- Browser cache and service workers
- CSS `:visited` history

### Proxy Binding

Each profile is bound to a fixed proxy. When GeoIP is enabled, the proxy IP automatically determines:
- Timezone
- Language/locale
- Geolocation coordinates

This ensures cross-layer consistency between network identity and fingerprint.

## API Reference

### `ProfileManager(base_dir)`

| Method | Description |
|--------|-------------|
| `initialize()` | Create database and directories |
| `create_profile(name, os, proxy, ...)` | Create profile with persistent fingerprint |
| `launch(profile_id, headless, ...)` | Launch browser (async context manager) |
| `warmup(profile_id, extra_urls, ...)` | Build browsing history |
| `get_profile(profile_id)` | Get profile by ID |
| `get_profile_by_name(name)` | Get profile by name |
| `list_profiles(tag, os, search, ...)` | List profiles with filters |
| `update_profile(profile_id, ...)` | Update name/tags/notes |
| `delete_profile(profile_id)` | Delete profile + browser data |
| `count_profiles()` | Count profiles |
| `close()` | Close database connection |
