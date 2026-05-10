"""
Essential data storage service for cfox-server.

Manages versioned storage of browser profile essential data (ZIP files).
Each profile keeps up to max_versions versions with SHA-256 checksum verification.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from ..schemas import VersionListItem

logger = logging.getLogger(__name__)


class StorageService:
    """
    Filesystem-based versioned storage for essential data.

    Directory layout:
        storage_dir/
            {profile_id}/
                v1.zip
                v2.zip
                v3.zip  (newest)
    """

    def __init__(self, storage_dir: Path, max_versions: int = 3):
        self.storage_dir = storage_dir
        self.max_versions = max_versions

    def _profile_dir(self, profile_id: str) -> Path:
        """Get storage directory for a profile."""
        d = self.storage_dir / profile_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, profile_id: str, version: int) -> Path:
        """Get path for a specific version file."""
        return self._profile_dir(profile_id) / f"v{version}.zip"

    def save(
        self,
        profile_id: str,
        data: bytes,
        version: int,
    ) -> Tuple[str, int]:
        """
        Save essential data for a profile.

        Args:
            profile_id: Profile ID.
            data: ZIP file bytes.
            version: Version number.

        Returns:
            Tuple of (sha256_checksum, size_bytes).
        """
        path = self._version_path(profile_id, version)
        path.write_bytes(data)

        checksum = hashlib.sha256(data).hexdigest()
        size = len(data)

        # Rotate old versions
        self._rotate(profile_id, version)

        logger.info(
            "Saved essential data: profile=%s v=%d size=%d checksum=%s",
            profile_id[:8], version, size, checksum[:12],
        )
        return checksum, size

    def load(self, profile_id: str, version: int) -> Optional[bytes]:
        """Load essential data for a specific version."""
        path = self._version_path(profile_id, version)
        if not path.exists():
            return None
        return path.read_bytes()

    def verify(self, data: bytes, expected_checksum: str) -> bool:
        """Verify data integrity via SHA-256."""
        actual = hashlib.sha256(data).hexdigest()
        return actual == expected_checksum

    def list_versions(self, profile_id: str) -> List[VersionListItem]:
        """List all available versions for a profile."""
        profile_dir = self._profile_dir(profile_id)
        versions = []

        for path in sorted(profile_dir.glob("v*.zip")):
            try:
                v = int(path.stem[1:])  # "v3" -> 3
                stat = path.stat()
                versions.append(VersionListItem(
                    version=v,
                    size_bytes=stat.st_size,
                    created_at=_format_mtime(stat.st_mtime),
                ))
            except (ValueError, OSError):
                continue

        return sorted(versions, key=lambda v: v.version, reverse=True)

    def delete_profile(self, profile_id: str) -> None:
        """Delete all versions for a profile."""
        profile_dir = self.storage_dir / profile_id
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)

    def _rotate(self, profile_id: str, current_version: int) -> None:
        """Remove versions older than max_versions."""
        profile_dir = self._profile_dir(profile_id)
        versions = []

        for path in profile_dir.glob("v*.zip"):
            try:
                v = int(path.stem[1:])
                versions.append((v, path))
            except ValueError:
                continue

        versions.sort(key=lambda x: x[0], reverse=True)

        for v, path in versions[self.max_versions:]:
            path.unlink(missing_ok=True)
            logger.debug("Rotated old version: profile=%s v=%d", profile_id[:8], v)


def _format_mtime(mtime: float) -> str:
    """Format file modification time as ISO string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
