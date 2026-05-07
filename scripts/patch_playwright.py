#!/usr/bin/env python3
"""
Patch Playwright's coreBundle.js to fix crash on pageError without location.

Problem:
    Playwright's Firefox protocol handler assumes pageError.location is always
    defined. When Camoufox/Firefox sends an uncaught error without location
    (e.g. from YouTube Studio web workers), Playwright's Node.js server crashes
    with: TypeError: Cannot read properties of undefined (reading 'url')

Fix:
    Add optional chaining (?.) and fallback defaults at two sites:
    1. FFPage._onUncaughtError  — where location enters from Juggler protocol
    2. BrowserContextDispatcher — where location is destructured for dispatch

Usage:
    python scripts/patch_playwright.py          # patch
    python scripts/patch_playwright.py --check  # check if already patched
    python scripts/patch_playwright.py --revert # revert patch (from backup)

This should be run after every `pip install playwright` or `pip install -U playwright`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def find_core_bundle() -> Path:
    """Locate Playwright's coreBundle.js in the installed package."""
    try:
        import playwright
    except ImportError:
        print("ERROR: playwright is not installed.", file=sys.stderr)
        sys.exit(1)

    pkg_dir = Path(playwright.__file__).parent
    bundle = pkg_dir / "driver" / "package" / "lib" / "coreBundle.js"
    if not bundle.exists():
        print(f"ERROR: coreBundle.js not found at {bundle}", file=sys.stderr)
        sys.exit(1)

    return bundle


# ---------- patch definitions ----------
# Each patch is (old_string, new_string, description)
PATCHES = [
    (
        # Patch 1: FFPage._onUncaughtError — null-safe location passthrough
        'this._page.addPageError(error, params2.location);',
        'this._page.addPageError(error, params2.location || { url: "", lineNumber: 0, columnNumber: 0 });',
        "FFPage._onUncaughtError: null-safe location fallback",
    ),
    (
        # Patch 2: BrowserContextDispatcher — null-safe location destructure
        """            location: {
              url: pageError.location.url,
              line: pageError.location.lineNumber,
              column: pageError.location.columnNumber
            }""",
        """            location: {
              url: pageError.location?.url || "",
              line: pageError.location?.lineNumber || 0,
              column: pageError.location?.columnNumber || 0
            }""",
        "BrowserContextDispatcher: optional chaining on pageError.location",
    ),
]


def check_patched(content: str) -> tuple[bool, list[str]]:
    """Check if all patches are already applied. Returns (all_applied, details)."""
    details = []
    all_applied = True
    for _, new, desc in PATCHES:
        if new in content:
            details.append(f"  [OK] {desc}")
        else:
            details.append(f"  [MISSING] {desc}")
            all_applied = False
    return all_applied, details


def apply_patches(bundle: Path) -> bool:
    """Apply all patches. Returns True if any changes were made."""
    content = bundle.read_text(encoding="utf-8")

    # Check if already patched
    already, details = check_patched(content)
    if already:
        print("All patches already applied:")
        for d in details:
            print(d)
        return False

    # Create backup
    backup = bundle.with_suffix(".js.bak")
    if not backup.exists():
        shutil.copy2(bundle, backup)
        print(f"Backup created: {backup}")

    # Apply patches
    changed = False
    for old, new, desc in PATCHES:
        if new in content:
            print(f"  [SKIP] Already applied: {desc}")
            continue
        if old not in content:
            print(f"  [WARN] Target not found (Playwright version changed?): {desc}")
            continue
        content = content.replace(old, new)
        print(f"  [OK] Applied: {desc}")
        changed = True

    if changed:
        bundle.write_text(content, encoding="utf-8")
        print(f"\nPatched: {bundle}")

    return changed


def revert_patch(bundle: Path) -> None:
    """Revert to backup if available."""
    backup = bundle.with_suffix(".js.bak")
    if not backup.exists():
        print("No backup found. Cannot revert.", file=sys.stderr)
        sys.exit(1)

    shutil.copy2(backup, bundle)
    print(f"Reverted to backup: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch Playwright coreBundle.js for pageError.location crash fix"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if patches are applied without modifying files"
    )
    parser.add_argument(
        "--revert", action="store_true",
        help="Revert patches from backup"
    )
    args = parser.parse_args()

    bundle = find_core_bundle()
    print(f"coreBundle.js: {bundle}")
    print(f"Size: {bundle.stat().st_size:,} bytes\n")

    if args.revert:
        revert_patch(bundle)
    elif args.check:
        content = bundle.read_text(encoding="utf-8")
        applied, details = check_patched(content)
        print("Patch status:")
        for d in details:
            print(d)
        sys.exit(0 if applied else 1)
    else:
        apply_patches(bundle)


if __name__ == "__main__":
    main()
