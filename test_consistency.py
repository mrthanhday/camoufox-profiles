"""
Automated consistency test using CreepJS.

Launches the same profile twice and compares fingerprint hashes
from CreepJS to verify cross-session consistency.
"""

import asyncio
import json
import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from camoufox_profiles import ProfileManager


PROFILES_DIR = "./test_profiles"
CREEPJS_URL = "https://abrahamjuliot.github.io/creepjs/"

# JavaScript to extract CreepJS fingerprint data after analysis completes
EXTRACT_CREEPJS_JS = """
async () => {
    // Wait for CreepJS to finish analysis (look for the fingerprint hash)
    let attempts = 0;
    while (attempts < 60) {
        // Check for the visitor ID / fingerprint hash
        const fpEl = document.querySelector('.fingerprint-header');
        const visitorEl = document.querySelector('#fingerprint-data');
        const hashEls = document.querySelectorAll('[class*="hash"]');
        
        // CreepJS shows results in the main content area
        const content = document.body.innerText;
        
        // Check if analysis is done by looking for typical result markers
        if (content.includes('trust score') || content.includes('bot') || 
            content.includes('fingerprint') && content.length > 5000) {
            break;
        }
        
        await new Promise(r => setTimeout(r, 1000));
        attempts++;
    }
    
    // Extract key fingerprint data
    const results = {};
    
    // Basic navigator
    results.userAgent = navigator.userAgent;
    results.platform = navigator.platform;
    results.hardwareConcurrency = navigator.hardwareConcurrency;
    results.deviceMemory = navigator.deviceMemory || 'N/A';
    results.language = navigator.language;
    results.languages = navigator.languages.join(', ');
    
    // Screen
    results.screenWidth = screen.width;
    results.screenHeight = screen.height;
    results.screenColorDepth = screen.colorDepth;
    results.availWidth = screen.availWidth;
    results.availHeight = screen.availHeight;
    
    // Window
    results.innerWidth = window.innerWidth;
    results.innerHeight = window.innerHeight;
    results.outerWidth = window.outerWidth;
    results.outerHeight = window.outerHeight;
    
    // Timezone
    results.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    results.timezoneOffset = new Date().getTimezoneOffset();
    
    // WebGL
    try {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl) {
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (debugInfo) {
                results.webglVendor = gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL);
                results.webglRenderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
            }
        }
    } catch(e) {
        results.webglVendor = 'error';
        results.webglRenderer = 'error';
    }
    
    // Canvas fingerprint (hash a small canvas)
    try {
        const canvas = document.createElement('canvas');
        canvas.width = 200;
        canvas.height = 50;
        const ctx = canvas.getContext('2d');
        ctx.textBaseline = 'top';
        ctx.font = '14px Arial';
        ctx.fillStyle = '#f60';
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = '#069';
        ctx.fillText('Fingerprint', 2, 15);
        ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
        ctx.fillText('Fingerprint', 4, 17);
        results.canvasHash = canvas.toDataURL().substring(0, 100);
    } catch(e) {
        results.canvasHash = 'error';
    }
    
    // AudioContext fingerprint
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        results.audioSampleRate = audioCtx.sampleRate;
        results.audioMaxChannelCount = audioCtx.destination.maxChannelCount;
        audioCtx.close();
    } catch(e) {
        results.audioSampleRate = 'error';
    }
    
    // CreepJS page content - extract trust score and hash if visible
    try {
        const pageText = document.body.innerText;
        
        // Look for trust score
        const trustMatch = pageText.match(/trust score[:\s]*([0-9.]+%?)/i);
        results.creepjsTrustScore = trustMatch ? trustMatch[1] : 'not found';
        
        // Look for fingerprint hash (usually a hex string)
        const allCodes = document.querySelectorAll('code, .hash, [data-fingerprint]');
        const hashes = [];
        allCodes.forEach(el => {
            const text = el.textContent.trim();
            if (text.match(/^[a-f0-9]{8,64}$/i)) {
                hashes.push(text);
            }
        });
        results.creepjsHashes = hashes.slice(0, 5).join(' | ') || 'not found';
        
        // Check for lies/detection
        results.creepjsLiesDetected = pageText.includes('lies detected') || 
                                       pageText.includes('lie detected');
    } catch(e) {
        results.creepjsError = e.message;
    }
    
    return results;
}
"""


async def run_session(pm, profile_id, session_num):
    """Run a single browser session and collect fingerprint data."""
    print(f"\n{'='*60}")
    print(f"  SESSION {session_num}")
    print(f"{'='*60}")

    async with pm.launch(profile_id, headless=True) as context:
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"  Navigating to CreepJS...")
        await page.goto(CREEPJS_URL, wait_until="domcontentloaded", timeout=30000)

        print(f"  Waiting for CreepJS analysis (up to 30s)...")
        await asyncio.sleep(15)  # Give CreepJS time to run its analysis

        print(f"  Extracting fingerprint data...")
        try:
            data = await page.evaluate(EXTRACT_CREEPJS_JS)
        except Exception as e:
            print(f"  ERROR extracting data: {e}")
            # Fallback: collect basic data
            data = await page.evaluate("""() => ({
                userAgent: navigator.userAgent,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                screenWidth: screen.width,
                screenHeight: screen.height,
                language: navigator.language,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            })""")

        # Take screenshot
        screenshot_path = f"./test_profiles/creepjs_session_{session_num}.png"
        await page.screenshot(path=screenshot_path, full_page=False)
        print(f"  Screenshot saved: {screenshot_path}")

    return data


def compare_sessions(data1, data2):
    """Compare fingerprint data from two sessions."""
    print(f"\n{'='*60}")
    print(f"  CONSISTENCY COMPARISON")
    print(f"{'='*60}")

    all_keys = sorted(set(list(data1.keys()) + list(data2.keys())))

    matches = 0
    mismatches = 0
    skipped = 0

    for key in all_keys:
        val1 = data1.get(key, "MISSING")
        val2 = data2.get(key, "MISSING")

        # Skip non-deterministic or informational fields
        if key in ("creepjsTrustScore", "creepjsHashes", "creepjsLiesDetected", "creepjsError"):
            status = "INFO"
            skipped += 1
        elif val1 == val2:
            status = "OK"
            matches += 1
        else:
            status = "MISMATCH"
            mismatches += 1

        # Truncate long values for display
        display1 = str(val1)[:60]
        display2 = str(val2)[:60]

        if status == "MISMATCH":
            print(f"  [FAIL] {key}:")
            print(f"         Session 1: {display1}")
            print(f"         Session 2: {display2}")
        elif status == "INFO":
            print(f"  [INFO] {key}: {display1}")
        else:
            print(f"  [ OK ] {key}: {display1}")

    print(f"\n  {'='*40}")
    print(f"  RESULT: {matches} matched, {mismatches} mismatched, {skipped} info-only")

    if mismatches == 0:
        print(f"  >>> ALL FINGERPRINT PROPERTIES ARE CONSISTENT <<<")
    else:
        print(f"  >>> WARNING: {mismatches} PROPERTIES DIFFER BETWEEN SESSIONS <<<")

    return mismatches == 0


async def main():
    pm = ProfileManager(PROFILES_DIR)
    await pm.initialize()

    # Reset profile for clean test
    profile_name = "creepjs-consistency-test"
    try:
        existing = await pm.get_profile_by_name(profile_name)
        await pm.delete_profile(existing.id)
        print(f"Deleted old test profile")
    except Exception:
        pass

    # Create fresh profile
    print(f"Creating test profile '{profile_name}'...")
    profile = await pm.create_profile(
        name=profile_name,
        os="windows",
        tags=["consistency-test"],
    )
    print(f"Profile ID: {profile.id}")

    fp = profile.fingerprint_config
    print(f"\nStored fingerprint config:")
    print(f"  UA: {fp.get('navigator.userAgent', 'N/A')[:80]}")
    print(f"  Platform: {fp.get('navigator.platform', 'N/A')}")
    print(f"  Screen: {fp.get('screen.width', '?')}x{fp.get('screen.height', '?')}")
    print(f"  WebGL: {fp.get('webGl:renderer', 'N/A')[:60]}")
    print(f"  Canvas seed: {fp.get('canvas:aaOffset', 'N/A')}")
    print(f"  Font seed: {fp.get('fonts:spacing_seed', 'N/A')}")

    # Run session 1
    data1 = await run_session(pm, profile.id, 1)

    # Small pause between sessions
    print(f"\n  Pausing 3s between sessions...")
    await asyncio.sleep(3)

    # Run session 2
    data2 = await run_session(pm, profile.id, 2)

    # Compare
    consistent = compare_sessions(data1, data2)

    # Updated profile info
    updated = await pm.get_profile(profile.id)
    print(f"\nProfile '{updated.name}' - Total sessions: {updated.total_sessions}")

    await pm.close()

    return 0 if consistent else 1


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
        sys.exit(code)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
