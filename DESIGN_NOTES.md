# Design Notes — Antidetect Profile System

> Validated insights for building consistent fingerprint profiles on top of Camoufox.
> Each item has been reviewed against Camoufox source code and architecture.

---

## Core Principle

A valid profile is the intersection of:

```
profile = device (fingerprint)
        + history (storage)
        + environment (network)
        + time (consistency + drift)
```

Behavior (mouse, timing, scroll) is the automation layer's responsibility, not the profile manager's.

---

## 1. Fingerprint Persistence — HOW IT WORKS

Camoufox generates random fingerprints via BrowserForge on every `launch_options()` call.
However, `merge_into()` (utils.py:243) only sets keys that **don't already exist** in config.

**Implication:** If we pass a complete saved config dict via `config={}`, all random
generation is effectively bypassed. The saved fingerprint is replayed exactly.

**What gets randomized each launch (and must be saved):**
- BrowserForge fingerprint (navigator, screen, battery)
- WebGL sample from `webgl_data.db` (vendor, renderer, extensions, shaders)
- `window.history.length` — `randrange(1, 6)`
- `canvas:aaOffset` — `randint(-50, 50)`
- `fonts:spacing_seed` — `randint(0, 1_073_741_823)`
- Locale selection (statistically sampled per region)

**What is derived (auto-consistent):**
- Fonts list → auto-matched to OS in UA (update_fonts)
- GeoIP → timezone + longitude/latitude + locale (get_geolocation)
- WebRTC IP → from proxy IP (if geoip enabled)
- Firefox version in UA → from installed Camoufox version

---

## 2. Cross-Layer Consistency — ALREADY SOLVED

Camoufox's existing stack ensures internal consistency:

| Relationship | How it's enforced |
|-------------|-------------------|
| OS ↔ UA ↔ platform | BrowserForge generates matching sets |
| OS ↔ Fonts | `update_fonts()` auto-adds OS-specific font list |
| GPU ↔ Extensions ↔ Shaders | `webgl_data.db` stores real-world GPU profiles |
| IP ↔ Timezone ↔ Language | `geoip=True` derives all from IP via MaxMind |
| UA ↔ HTTP headers | `headers.User-Agent` falls back to `navigator.userAgent` |

**Our job:** Don't break this. Never allow manual override of individual
properties without understanding the full dependency chain.

---

## 3. Storage & State — USE PERSISTENT CONTEXT

Playwright's `launch_persistent_context(user_data_dir=...)` handles:
- ✅ Cookies
- ✅ localStorage / sessionStorage
- ✅ IndexedDB
- ✅ Cache / Service Workers
- ✅ Visited link history (CSS :visited)

**Each profile gets its own `user_data_dir` directory.**
No custom storage engine needed.

---

## 4. Network Identity — PROXY STRATEGY

### Fixed Proxy Per Profile (Default)
- 1 profile = 1 proxy (fixed IP)
- Residential proxies preferred over datacenter
- Proxy IP determines: timezone, language, locale, geolocation, WebRTC IP
- Changing proxy = effectively new identity (geo mismatch risk)

### Null-Proxy Profiles (Local IP)
- Profile uses the machine's local IP address
- **Risk:** Local IP can change between sessions (VPN, ISP reassignment)
- **Mitigation:** IP Consistency Guard (V2) automatically detects region changes
  and recalculates all geo properties before launch

### Centralized Proxy Pool (V2)
- Proxies managed in `proxy_pool` table with tags, health status, latency
- Profiles bound to proxy pool entries via `proxy_id`
- Auto-rotation available (opt-in, default disabled)
- Manual rotation: `cfox proxy check` → `cfox proxy add` → rebind

**TLS/JA3 fingerprint:** Not a concern. Camoufox uses Firefox's native TLS stack,
which produces authentic Firefox JA3 signatures. This is a key advantage over
Chromium-based antidetect browsers.

---

## 5. Natural Drift — IMPLEMENTED IN V2

### What Drifts
Profiles age naturally over time to avoid "frozen fingerprint" detection:

| Property | Mechanism | Interval | Safe? |
|----------|-----------|----------|-------|
| Firefox version in UA | Bumps to match installed binary | ~28 days (configurable) | ✅ Real browsers do this |
| Viewport dimensions | ±3px jitter on width/height | Each launch | ✅ Window resize is normal |
| `window.history.length` | Random between 1-8 | Each launch | ✅ Varies in real usage |

### What NEVER Drifts
These properties are immutable for a profile's lifetime:

- OS / platform
- GPU (WebGL vendor/renderer)
- Screen resolution and color depth
- CPU cores (`hardwareConcurrency`)
- Font list
- Canvas/audio fingerprint seeds

**Rationale:** These correspond to physical hardware. Real users don't change GPUs or OSes between sessions.

### Drift Schedule
Each profile has a `DriftSchedule` with per-property toggles:

```python
DriftSchedule(
    drift_ua_version=True,          # Enable UA version bumps
    drift_viewport=True,            # Enable viewport jitter
    drift_history_length=True,      # Enable history randomization
    ua_drift_interval_days=28,      # Days between UA bumps
    viewport_jitter_range=3,        # Max ±px jitter
)
```

Setting `drift=False` on launch disables cosmetic drift but **never** disables
the IP Consistency Guard — that is a safety mechanism, not a cosmetic feature.

### Drift Events
All drift actions are recorded as immutable audit events in `drift_events` table:

```
Event: ua_version | old=Firefox/135.0 | new=Firefox/142.0 | timestamp
Event: viewport_jitter | old=1920x1080 | new=1922x1080 | timestamp
Event: geo_ip_change | old=US/1.2.3.4 | new=DE/5.6.7.8 | timestamp
```

---

## 6. IP Consistency Guard — IMPLEMENTED IN V2

**Problem:** Null-proxy profiles derive geo properties (timezone, locale, coordinates)
from the public IP at creation time. If the IP's region changes between sessions
(VPN switch, ISP reassignment), the profile becomes inconsistent:

```
Session 1: IP=US → timezone=America/New_York, locale=en-US
Session 2: IP=DE → timezone still America/New_York → DETECTED!
```

**Solution:** Before every launch of a null-proxy profile:

1. Resolve current public IP and region
2. Compare against `last_known_region`
3. If region changed:
   - Recalculate all geo properties from new IP
   - Update fingerprint config with new timezone/locale/coordinates/WebRTC IP
   - Log a `geo_ip_change` drift event
   - Update `last_known_ip` and `last_known_region`
4. If region same: no action

**This guard runs ALWAYS, regardless of `drift=True/False`.**

---

## 7. Common Mistakes to Avoid

| Mistake | Why it fails | Our mitigation |
|---------|-------------|----------------|
| Random fingerprint every session | Bot detection: "device changes identity" | Persist & replay exact config |
| No storage persistence | "User with amnesia" — no cookies, no history | Playwright persistent_context |
| Proxy doesn't match fingerprint | IP says US, timezone says Vietnam | GeoIP auto-derives locale from proxy IP |
| Brand new profile used immediately | No browsing history = suspicious | Built-in warmup engine |
| Datacenter IP + consumer fingerprint | ASN/ISP mismatch | Document: use residential proxies |
| Canvas/audio hash changes per session | Fingerprint hash inconsistency | Save canvas:aaOffset + fonts:spacing_seed |
| Frozen fingerprint for months | Firefox version stuck at 135 while world uses 142 | Drift engine bumps UA version |
| Local IP region changed silently | Timezone/locale mismatch with IP | IP Consistency Guard auto-recalibrates |

---

## 8. Profile Lifecycle

```
Creation → Warmup → Active use → Aging (drift) → Trust increases
```

- Profile "age" correlates with trust score on many platforms
- Older profiles with consistent history are less likely to be flagged
- Drift engine ensures the fingerprint evolves naturally with time
- Health diagnostics catch issues before they cause detection
