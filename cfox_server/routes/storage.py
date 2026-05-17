"""Essential data upload/download/versions routes for cfox-server."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update

from camoufox_profiles.models import _utcnow
from camoufox_profiles.models_sa import ProfileModel

from ..middleware import AuthUser, get_current_user
from ..schemas import EssentialDataInfo, MessageResponse, VersionListItem
from ..services.storage_service import StorageService

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_storage(request: Request) -> StorageService:
    """Get or create storage service."""
    settings = request.app.state.settings
    return StorageService(settings.storage_dir, settings.max_versions)


@router.post("/{profile_id}/essential-data", response_model=EssentialDataInfo)
async def upload_essential_data(
    profile_id: str,
    file: UploadFile,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Upload essential data ZIP for a profile.

    Increments the version counter and stores the file.
    Validates that the profile is locked by the uploader.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Must be locked to upload
        if not model.locked_by:
            raise HTTPException(
                status_code=409,
                detail="Profile must be locked before uploading essential data",
            )

    # Read file content
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    # Enforce upload size cap to avoid runaway browser data dumps
    max_bytes = getattr(request.app.state.settings, "max_upload_bytes", 256 * 1024 * 1024)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload too large: {len(data)} bytes (max {max_bytes})",
        )

    new_version = (model.essential_data_version or 0) + 1
    storage = _get_storage(request)
    checksum, size = storage.save(profile_id, data, new_version)

    # Update profile metadata
    now = _utcnow().isoformat()
    async with request.app.state.session_factory() as session:
        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                essential_data_version=new_version,
                essential_data_size_bytes=size,
                essential_data_checksum=checksum,
                last_synced_at=now,
                last_sync_machine=model.locked_by,
                sync_incomplete=0,
            )
        )
        await session.commit()

    logger.info(
        "Essential data uploaded: profile=%s v=%d size=%d",
        profile_id[:8], new_version, size,
    )

    return EssentialDataInfo(
        version=new_version,
        size_bytes=size,
        checksum=checksum,
        uploaded_at=now,
    )


@router.get("/{profile_id}/essential-data")
async def download_essential_data(
    profile_id: str,
    request: Request,
    version: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """
    Download essential data ZIP for a profile.

    If version=0 (default), downloads the latest version.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

    target_version = version or (model.essential_data_version or 0)
    if target_version == 0:
        raise HTTPException(status_code=404, detail="No essential data available")

    storage = _get_storage(request)
    data = storage.load(profile_id, target_version)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Version {target_version} not found")

    # Verify checksum if available
    if version == 0 and model.essential_data_checksum:
        actual = hashlib.sha256(data).hexdigest()
        if actual != model.essential_data_checksum:
            logger.error(
                "Checksum mismatch on download: profile=%s expected=%s actual=%s",
                profile_id[:8], model.essential_data_checksum[:12], actual[:12],
            )
            raise HTTPException(status_code=500, detail="Data integrity check failed")

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{profile_id}_v{target_version}.zip"',
            "X-Checksum": hashlib.sha256(data).hexdigest(),
            "X-Version": str(target_version),
        },
    )


@router.get("/{profile_id}/essential-data/versions", response_model=list[VersionListItem])
async def list_versions(
    profile_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """List all available versions of essential data for a profile."""
    storage = _get_storage(request)
    return storage.list_versions(profile_id)


@router.post("/{profile_id}/essential-data/rollback", response_model=EssentialDataInfo)
async def rollback_version(
    profile_id: str,
    version: int,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Rollback to a specific version of essential data.

    Copies the target version as the new current version.
    """
    storage = _get_storage(request)
    data = storage.load(profile_id, version)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

    new_version = (model.essential_data_version or 0) + 1
    checksum, size = storage.save(profile_id, data, new_version)

    now = _utcnow().isoformat()
    async with request.app.state.session_factory() as session:
        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                essential_data_version=new_version,
                essential_data_size_bytes=size,
                essential_data_checksum=checksum,
                last_synced_at=now,
            )
        )
        await session.commit()

    return EssentialDataInfo(
        version=new_version,
        size_bytes=size,
        checksum=checksum,
        uploaded_at=now,
    )
