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
        + time (consistency)
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

## 4. Network Identity — FIXED PROXY PER PROFILE

Rules:
- 1 profile = 1 proxy (fixed IP)
- Residential proxies preferred over datacenter
- Proxy IP determines: timezone, language, locale, geolocation, WebRTC IP
- Changing proxy = effectively new identity (geo mismatch risk)

**TLS/JA3 fingerprint:** Not a concern. Camoufox uses Firefox's native TLS stack,
which produces authentic Firefox JA3 signatures. This is a key advantage over
Chromium-based antidetect browsers.

---

## 5. Common Mistakes to Avoid

| Mistake | Why it fails | Our mitigation |
|---------|-------------|----------------|
| Random fingerprint every session | Bot detection: "device changes identity" | Persist & replay exact config |
| No storage persistence | "User with amnesia" — no cookies, no history | Playwright persistent_context |
| Proxy doesn't match fingerprint | IP says US, timezone says Vietnam | GeoIP auto-derives locale from proxy IP |
| Brand new profile used immediately | No browsing history = suspicious | Built-in warmup engine |
| Datacenter IP + consumer fingerprint | ASN/ISP mismatch | Document: use residential proxies |
| Canvas/audio hash changes per session | Fingerprint hash inconsistency | Save canvas:aaOffset + fonts:spacing_seed |

---

## 6. Future Considerations (V2+)

### Natural Drift
- Firefox version: bump +1 every ~28 days (match real update cycle)
- Viewport: micro-shift ±3px occasionally
- History length: grow naturally with usage
- NEVER change: OS, GPU, screen resolution, CPU cores, font list

### Profile Lifecycle
- Creation → Warmup → Active use → Aging (trust increases)
- Profile "age" correlates with trust score on many platforms
- Older profiles with consistent history are less likely to be flagged
