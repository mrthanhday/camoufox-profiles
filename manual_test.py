"""
Manual test script for camoufox-profiles.

Creates a profile (or reuses existing) and launches Camoufox for manual testing.
Visit these sites to verify fingerprint consistency:
  - https://browserscan.net
  - https://abrahamjuliot.github.io/creepjs/
  - https://iphey.com
  - https://bot.sannysoft.com

Usage:
    # First run: creates profile + launches browser
    python manual_test.py

    # Second run: reuses same profile (fingerprint should be identical)
    python manual_test.py

    # With warmup first:
    python manual_test.py --warmup

    # Headless mode:
    python manual_test.py --headless

    # Delete profile and start fresh:
    python manual_test.py --reset

    # Specify profile name:
    python manual_test.py --name "my-test-profile"
"""

import argparse
import asyncio
import json
import os
import sys

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from camoufox_profiles import ProfileManager, ProxyConfig


# Test sites for fingerprint verification
TEST_SITES = [
    "https://browserscan.net",
    "https://abrahamjuliot.github.io/creepjs/",
    "https://bot.sannysoft.com",
]

PROFILE_NAME = "manual-test"
PROFILES_DIR = "./test_profiles"


async def main():
    parser = argparse.ArgumentParser(description="Manual test for camoufox-profiles")
    parser.add_argument("--name", default=PROFILE_NAME, help="Profile name")
    parser.add_argument("--warmup", action="store_true", help="Run warmup before launch")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--reset", action="store_true", help="Delete existing profile and recreate")
    parser.add_argument("--os", default="windows", choices=["windows", "macos", "linux"], help="Target OS")
    parser.add_argument("--proxy", default=None, help="Proxy server (e.g. http://user:pass@host:port)")
    parser.add_argument("--site", default=None, help="Open specific site on launch")
    args = parser.parse_args()

    pm = ProfileManager(PROFILES_DIR)
    await pm.initialize()

    profile_name = args.name

    # Handle --reset
    if args.reset:
        try:
            existing = await pm.get_profile_by_name(profile_name)
            await pm.delete_profile(existing.id)
            print(f"🗑️  Deleted profile '{profile_name}'")
        except Exception:
            pass

    # Try to load existing profile
    profile = None
    try:
        profile = await pm.get_profile_by_name(profile_name)
        print(f"✅ Loaded existing profile '{profile.name}'")
        print(f"   ID: {profile.id}")
        print(f"   OS: {profile.target_os}")
        print(f"   Sessions: {profile.total_sessions}")
        print(f"   Created: {profile.created_at}")
        print(f"   Last used: {profile.last_used_at or 'never'}")
    except Exception:
        pass

    # Create new profile if needed
    if profile is None:
        print(f"\n🔧 Creating new profile '{profile_name}'...")

        proxy_config = None
        if args.proxy:
            # Parse proxy string like http://user:pass@host:port
            proxy_config = ProxyConfig(server=args.proxy)

        profile = await pm.create_profile(
            name=profile_name,
            os=args.os,
            proxy=proxy_config,
            geoip=True if proxy_config else None,
            tags=["manual-test"],
            notes="Created by manual_test.py",
        )

        print(f"✅ Profile created!")
        print(f"   ID: {profile.id}")
        print(f"   OS: {profile.target_os}")

        # Show some fingerprint details
        fp = profile.fingerprint_config
        print(f"\n📋 Fingerprint snapshot:")
        print(f"   UA: {fp.get('navigator.userAgent', 'N/A')[:80]}...")
        print(f"   Platform: {fp.get('navigator.platform', 'N/A')}")
        print(f"   Screen: {fp.get('screen.width', '?')}x{fp.get('screen.height', '?')}")
        print(f"   CPU cores: {fp.get('navigator.hardwareConcurrency', 'N/A')}")
        print(f"   WebGL vendor: {fp.get('webGl:vendor', 'N/A')}")
        print(f"   WebGL renderer: {fp.get('webGl:renderer', 'N/A')}")
        print(f"   Canvas seed: {fp.get('canvas:aaOffset', 'N/A')}")
        print(f"   Font seed: {fp.get('fonts:spacing_seed', 'N/A')}")

    # Run warmup if requested
    if args.warmup:
        print(f"\n🔄 Running warmup...")
        report = await pm.warmup(profile.id, headless=True)
        print(f"   Visited: {report.successful_visits}/{report.total_visits} sites")
        print(f"   Duration: {report.total_duration_seconds:.0f}s")

    # Launch browser for manual testing
    print(f"\n🚀 Launching browser...")
    print(f"   Profile: {profile.name}")
    print(f"   Headless: {args.headless}")
    print()

    if not args.headless:
        print("=" * 60)
        print("  MANUAL TEST — Browser is open for testing")
        print("=" * 60)
        print()
        print("  Recommended test sites:")
        for site in TEST_SITES:
            print(f"    → {site}")
        print()
        print("  What to verify:")
        print("    1. Fingerprint values match across sessions")
        print("    2. No red flags on browserscan.net")
        print("    3. CreepJS hash stays the same on relaunch")
        print("    4. Cookies/localStorage persist between sessions")
        print()
        print("  Press Ctrl+C or close the browser to exit.")
        print("=" * 60)
        print()

    async with pm.launch(profile.id, headless=args.headless) as context:
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to the specified site or the first test site
        target = args.site or TEST_SITES[0]
        print(f"  Opening: {target}")
        await page.goto(target)

        if not args.headless:
            # Keep browser open until user closes it or presses Ctrl+C
            try:
                while True:
                    await asyncio.sleep(1)
                    # Check if browser is still open
                    if not context.pages:
                        print("\n  Browser closed by user.")
                        break
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n  Shutting down...")
        else:
            # In headless mode, just grab some fingerprint data and exit
            print("\n  Collecting fingerprint data (headless)...")
            fp_data = await page.evaluate("""() => ({
                userAgent: navigator.userAgent,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                screenWidth: screen.width,
                screenHeight: screen.height,
                colorDepth: screen.colorDepth,
                language: navigator.language,
                languages: navigator.languages,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            })""")
            print(f"\n  Live fingerprint from browser:")
            for key, value in fp_data.items():
                print(f"    {key}: {value}")

    # Show updated session count
    updated = await pm.get_profile(profile.id)
    print(f"\n✅ Session #{updated.total_sessions} complete.")

    await pm.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye!")
