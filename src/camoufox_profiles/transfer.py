"""
Profile export and import.

Exports profiles as ZIP archives containing fingerprint config,
drift schedule, and browser data. Supports optional AES-256
encryption via pyzipper.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import orjson

from .models import Profile

logger = logging.getLogger(__name__)


def _has_pyzipper() -> bool:
    """Check if pyzipper is available for encryption."""
    try:
        import pyzipper
        return True
    except ImportError:
        return False


async def export_profile(
    profile: Profile,
    output_path: str,
    password: Optional[str] = None,
) -> str:
    """
    Export a profile to a ZIP archive.

    Args:
        profile: Profile to export.
        output_path: Destination path for the ZIP file.
        password: Optional password for AES-256 encryption.

    Returns:
        Absolute path to the created ZIP file.

    Raises:
        ImportError: If password is set but pyzipper is not installed.
    """
    manifest = {
        "schema_version": 2,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "target_os": profile.target_os,
        "created_at": profile.created_at.isoformat(),
        "total_sessions": profile.total_sessions,
        "tags": profile.tags,
        "notes": profile.notes,
        "creation_ip": profile.creation_ip,
        "creation_region": profile.creation_region,
        "has_browser_data": os.path.isdir(profile.user_data_dir),
    }

    fingerprint_json = orjson.dumps(
        profile.fingerprint_config, option=orjson.OPT_INDENT_2
    ).decode("utf-8")

    drift_json = orjson.dumps(
        profile.drift_schedule.to_dict(), option=orjson.OPT_INDENT_2
    ).decode("utf-8")

    manifest_json = orjson.dumps(
        manifest, option=orjson.OPT_INDENT_2
    ).decode("utf-8")

    # Proxy config (without password — security)
    proxy_info = None
    if profile.proxy:
        proxy_info = orjson.dumps({
            "server": profile.proxy.server,
            "has_credentials": bool(profile.proxy.username),
        }, option=orjson.OPT_INDENT_2).decode("utf-8")

    output_path = str(Path(output_path).resolve())

    if password:
        if not _has_pyzipper():
            raise ImportError(
                "pyzipper is required for encrypted exports. "
                "Install with: pip install camoufox-profiles[crypto]"
            )
        import pyzipper
        with pyzipper.AESZipFile(
            output_path, "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            zf.setpassword(password.encode("utf-8"))
            zf.writestr("manifest.json", manifest_json)
            zf.writestr("fingerprint.json", fingerprint_json)
            zf.writestr("drift_schedule.json", drift_json)
            if proxy_info:
                zf.writestr("proxy.json", proxy_info)
            # Add browser data
            if os.path.isdir(profile.user_data_dir):
                _add_dir_to_zip(zf, profile.user_data_dir, "browser_data")
    else:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_json)
            zf.writestr("fingerprint.json", fingerprint_json)
            zf.writestr("drift_schedule.json", drift_json)
            if proxy_info:
                zf.writestr("proxy.json", proxy_info)
            if os.path.isdir(profile.user_data_dir):
                _add_dir_to_zip(zf, profile.user_data_dir, "browser_data")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(
        "Exported profile '%s' to %s (%.1f MB%s)",
        profile.name, output_path, size_mb,
        ", encrypted" if password else "",
    )

    return output_path


async def import_profile(
    store: Any,  # ProfileStore
    zip_path: str,
    new_name: Optional[str] = None,
    password: Optional[str] = None,
) -> Profile:
    """
    Import a profile from a ZIP archive.

    Args:
        store: ProfileStore instance.
        zip_path: Path to the ZIP file.
        new_name: Optional override for the profile name.
        password: Password for encrypted archives.

    Returns:
        The imported Profile object.
    """
    zip_path = str(Path(zip_path).resolve())

    # Open ZIP (encrypted or plain)
    if password:
        if not _has_pyzipper():
            raise ImportError("pyzipper is required for encrypted imports.")
        import pyzipper
        zf = pyzipper.AESZipFile(zip_path, "r")
        zf.setpassword(password.encode("utf-8"))
    else:
        zf = zipfile.ZipFile(zip_path, "r")

    with zf:
        # Read manifest
        manifest = orjson.loads(zf.read("manifest.json"))
        fingerprint_config = orjson.loads(zf.read("fingerprint.json"))

        # Read drift schedule
        try:
            drift_data = orjson.loads(zf.read("drift_schedule.json"))
        except KeyError:
            drift_data = {}

        # Determine name
        name = new_name or manifest.get("profile_name", f"imported-{manifest.get('profile_id', 'unknown')[:8]}")

        # Create profile in store
        from .models import DriftSchedule
        profile = await store.create(
            name=name,
            target_os=manifest.get("target_os", "windows"),
            fingerprint_config=fingerprint_config,
            tags=manifest.get("tags", []),
            notes=manifest.get("notes", ""),
        )

        # Update V2 fields
        await store.update_v2_fields(
            profile.id,
            drift_schedule=DriftSchedule.from_dict(drift_data),
            creation_ip=manifest.get("creation_ip"),
            creation_region=manifest.get("creation_region"),
        )

        # Extract browser data
        browser_data_entries = [n for n in zf.namelist() if n.startswith("browser_data/")]
        if browser_data_entries:
            with tempfile.TemporaryDirectory() as tmpdir:
                for entry in browser_data_entries:
                    zf.extract(entry, tmpdir)
                src = os.path.join(tmpdir, "browser_data")
                if os.path.isdir(src):
                    # Copy to profile's user_data_dir
                    if os.path.exists(profile.user_data_dir):
                        shutil.rmtree(profile.user_data_dir)
                    shutil.copytree(src, profile.user_data_dir)

    logger.info("Imported profile '%s' from %s", name, zip_path)

    # Re-fetch to get updated fields
    return await store.get(profile.id)


def _add_dir_to_zip(zf: Any, source_dir: str, arcname_prefix: str) -> None:
    """Add a directory tree to a ZIP file."""
    source = Path(source_dir)
    for root, dirs, files in os.walk(source):
        for file in files:
            file_path = Path(root) / file
            arcname = os.path.join(
                arcname_prefix,
                str(file_path.relative_to(source)),
            )
            try:
                zf.write(str(file_path), arcname)
            except (PermissionError, OSError) as e:
                logger.debug("Skipping locked file %s: %s", file_path, e)
