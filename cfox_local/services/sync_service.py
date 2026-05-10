"""
Browser profile sync service for cfox-local.

Collects essential browser data from a Firefox profile into a ZIP archive
for cloud upload, and restores it on download. Uses copy-before-zip to
avoid locking issues with open SQLite databases.

CRITICAL: Never merge essential data — always full replace + cache clear.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Essential file patterns — these are the browser state files worth syncing.
# Extended set includes form data, permissions, and content preferences.
ESSENTIAL_PATTERNS: List[str] = [
    # Core browser data
    "cookies.sqlite*",
    "places.sqlite*",
    "favicons.sqlite*",
    "storage.sqlite*",
    # Login data
    "key4.db",
    "logins.json",
    "cert9.db",
    # Session + preferences
    "prefs.js",
    "sessionstore.jsonlz4",
    "sessionCheckpoints.json",
    # Extended essentials (Phase 3 additions)
    "permissions.sqlite*",
    "formhistory.sqlite*",
    "content-prefs.sqlite*",
    # Web storage
    "webappsstore.sqlite*",
    # Extension storage
    "extension-preferences.json",
]

# Max size before warning (200MB)
SIZE_WARNING_BYTES = 200 * 1024 * 1024


def collect_essential_data(
    profile_dir: str | Path,
    output_path: Optional[str | Path] = None,
) -> Tuple[Path, str, int]:
    """
    Collect essential browser data into a ZIP archive.

    Uses copy-before-zip strategy:
    1. Copy matching files to a temp directory (avoids SQLite lock issues)
    2. Create ZIP from the temp directory
    3. Calculate SHA-256 checksum

    Args:
        profile_dir: Path to the Firefox profile directory.
        output_path: Optional output ZIP path. If None, creates a temp file.

    Returns:
        Tuple of (zip_path, sha256_checksum, size_bytes).
    """
    profile_dir = Path(profile_dir)
    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile directory not found: {profile_dir}")

    # Step 1: Copy files to temp directory
    with tempfile.TemporaryDirectory(prefix="cfox_sync_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        copied = _copy_matching_files(profile_dir, tmp_path)

        if not copied:
            logger.warning("No essential files found in %s", profile_dir)

        # Step 2: Create ZIP archive
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".zip", prefix="cfox_essential_")
            import os
            os.close(fd)

        output_path = Path(output_path)
        _create_zip(tmp_path, output_path)

    # Step 3: Checksum + size
    data = output_path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    size = len(data)

    if size > SIZE_WARNING_BYTES:
        logger.warning(
            "Essential data is large: %dMB (profile=%s). Consider cleanup.",
            size // (1024 * 1024), profile_dir.name,
        )

    logger.info(
        "Collected essential data: %d files, %dKB, checksum=%s",
        copied, size // 1024, checksum[:12],
    )

    return output_path, checksum, size


def restore_essential_data(
    zip_path: str | Path,
    profile_dir: str | Path,
    expected_checksum: Optional[str] = None,
    clear_cache: bool = True,
) -> int:
    """
    Restore essential browser data from a ZIP archive into a profile directory.

    IMPORTANT: This replaces files — never merges. The profile directory should
    exist but the browser MUST NOT be running.

    Args:
        zip_path: Path to the essential data ZIP.
        profile_dir: Target Firefox profile directory.
        expected_checksum: Optional SHA-256 to verify before extracting.
        clear_cache: Clear browser cache after restore (recommended).

    Returns:
        Number of files restored.
    """
    zip_path = Path(zip_path)
    profile_dir = Path(profile_dir)

    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    # Verify checksum
    if expected_checksum:
        actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        if actual != expected_checksum:
            raise ValueError(
                f"Checksum mismatch: expected {expected_checksum[:12]}..., got {actual[:12]}..."
            )

    # Ensure target directory exists
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Extract — full replace (overwrite existing files)
    restored = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            zf.extract(info, profile_dir)
            restored += 1

    # Clear cache directories
    if clear_cache:
        _clear_cache(profile_dir)

    logger.info("Restored %d files to %s", restored, profile_dir)
    return restored


def verify_checksum(file_path: str | Path, expected: str) -> bool:
    """Verify SHA-256 checksum of a file."""
    data = Path(file_path).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    return actual == expected


def _copy_matching_files(src: Path, dst: Path) -> int:
    """Copy files matching ESSENTIAL_PATTERNS from src to dst."""
    import fnmatch

    copied = 0
    for pattern in ESSENTIAL_PATTERNS:
        for file_path in src.glob(pattern):
            if file_path.is_file():
                rel = file_path.relative_to(src)
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, target)
                copied += 1

    return copied


def _create_zip(source_dir: Path, output: Path) -> None:
    """Create a ZIP archive from all files in source_dir."""
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(source_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(source_dir)
                zf.write(file_path, arcname)


def _clear_cache(profile_dir: Path) -> None:
    """Clear Firefox cache directories after restore."""
    cache_dirs = [
        profile_dir / "cache2",
        profile_dir / "startupCache",
        profile_dir / "shader-cache",
    ]
    for cache_dir in cache_dirs:
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            logger.debug("Cleared cache: %s", cache_dir.name)
