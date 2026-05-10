"""Profile CRUD routes for cfox-server."""

from __future__ import annotations

import re
from typing import Optional

import orjson
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import delete, func, select, update

from camoufox_profiles.models import _new_id, _utcnow
from camoufox_profiles.models_sa import ProfileModel

from ..middleware import AuthUser, get_current_user
from ..schemas import (
    MessageResponse,
    ProfileCreate,
    ProfileListResponse,
    ProfileResponse,
    ProfileUpdate,
)

router = APIRouter()


def _model_to_response(m: ProfileModel) -> ProfileResponse:
    """Convert ORM model to API response."""
    tags = orjson.loads(m.tags or "[]") if isinstance(m.tags, str) else (m.tags or [])
    fp = orjson.loads(m.fingerprint_config) if isinstance(m.fingerprint_config, str) else m.fingerprint_config

    return ProfileResponse(
        id=m.id,
        name=m.name,
        created_at=m.created_at,
        last_used_at=m.last_used_at,
        target_os=m.target_os,
        fingerprint_config=fp,
        proxy_server=m.proxy_server,
        proxy_username=m.proxy_username,
        proxy_password=m.proxy_password,
        user_data_dir=m.user_data_dir or "",
        total_sessions=m.total_sessions or 0,
        tags=tags,
        notes=m.notes or "",
        firefox_base_version=m.firefox_base_version,
        proxy_id=m.proxy_id,
        warmup_completed=bool(m.warmup_completed),
        locked_by=m.locked_by,
        lock_expires_at=m.lock_expires_at,
        essential_data_version=m.essential_data_version or 0,
        essential_data_size_bytes=m.essential_data_size_bytes or 0,
        sync_incomplete=bool(m.sync_incomplete),
        last_synced_at=m.last_synced_at,
        last_sync_machine=m.last_sync_machine,
    )


@router.get("", response_model=ProfileListResponse)
async def list_profiles(
    request: Request,
    tag: Optional[str] = None,
    target_os: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, le=1000),
    offset: int = 0,
    user: AuthUser = Depends(get_current_user),
):
    """List all profiles with optional filters."""
    stmt = select(ProfileModel)
    count_stmt = select(func.count()).select_from(ProfileModel)

    if tag:
        stmt = stmt.where(ProfileModel.tags.contains(f'"{tag}"'))
        count_stmt = count_stmt.where(ProfileModel.tags.contains(f'"{tag}"'))
    if target_os:
        stmt = stmt.where(ProfileModel.target_os == target_os)
        count_stmt = count_stmt.where(ProfileModel.target_os == target_os)
    if search:
        pattern = f"%{search}%"
        cond = ProfileModel.name.ilike(pattern) | ProfileModel.notes.ilike(pattern)
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    stmt = stmt.order_by(ProfileModel.created_at.desc()).limit(limit).offset(offset)

    async with request.app.state.session_factory() as session:
        result = await session.execute(stmt)
        models = result.scalars().all()
        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

    return ProfileListResponse(
        profiles=[_model_to_response(m) for m in models],
        total=total,
    )


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    data: ProfileCreate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Create a new cloud profile."""
    profile_id = _new_id()
    now = _utcnow().isoformat()

    # Extract Firefox version from fingerprint
    ua = data.fingerprint_config.get("navigator.userAgent", "")
    ff_version = None
    match = re.search(r"Firefox/(\d+)\.0", ua)
    if match:
        ff_version = int(match.group(1))

    model = ProfileModel(
        id=profile_id,
        name=data.name,
        created_at=now,
        target_os=data.target_os,
        fingerprint_config=orjson.dumps(data.fingerprint_config).decode("utf-8"),
        proxy_server=data.proxy_server,
        proxy_username=data.proxy_username,
        proxy_password=data.proxy_password,
        user_data_dir=data.user_data_dir or f"cloud/{profile_id}",
        tags=orjson.dumps(data.tags).decode("utf-8"),
        notes=data.notes,
        firefox_base_version=ff_version,
        proxy_id=data.proxy_id,
    )

    async with request.app.state.session_factory() as session:
        # Check name uniqueness
        existing = await session.execute(
            select(ProfileModel).where(ProfileModel.name == data.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Profile '{data.name}' already exists")
        session.add(model)
        await session.commit()
        await session.refresh(model)

    return _model_to_response(model)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Get a profile by ID."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _model_to_response(model)


@router.patch("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: str,
    data: ProfileUpdate,
    request: Request,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    user: AuthUser = Depends(get_current_user),
):
    """
    Update a profile's mutable fields.

    Supports optimistic concurrency via If-Match header containing
    the expected essential_data_version.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Optimistic concurrency check
        if if_match is not None:
            try:
                expected = int(if_match)
                if model.essential_data_version != expected:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Version conflict: expected {expected}, got {model.essential_data_version}",
                    )
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid If-Match header")

        # Check name uniqueness
        if data.name is not None and data.name != model.name:
            existing = await session.execute(
                select(ProfileModel).where(
                    ProfileModel.name == data.name,
                    ProfileModel.id != profile_id,
                )
            )
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail=f"Name '{data.name}' already taken")

        values = {}
        if data.name is not None:
            values["name"] = data.name
        if data.tags is not None:
            values["tags"] = orjson.dumps(data.tags).decode("utf-8")
        if data.notes is not None:
            values["notes"] = data.notes
        if data.total_sessions is not None:
            values["total_sessions"] = data.total_sessions
        if data.last_used_at is not None:
            values["last_used_at"] = data.last_used_at

        if values:
            await session.execute(
                update(ProfileModel)
                .where(ProfileModel.id == profile_id)
                .values(**values)
            )
            await session.commit()

    # Re-fetch updated model
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()

    return _model_to_response(model)


@router.delete("/{profile_id}", response_model=MessageResponse)
async def delete_profile(
    profile_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Delete a profile and its associated essential data."""
    import shutil

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Cannot delete locked profiles
        if model.locked_by:
            raise HTTPException(
                status_code=409,
                detail=f"Profile is locked by {model.locked_by}. Unlock first.",
            )

        await session.execute(
            delete(ProfileModel).where(ProfileModel.id == profile_id)
        )
        await session.commit()

    # Delete essential data files
    settings = request.app.state.settings
    data_dir = settings.storage_dir / profile_id
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)

    return MessageResponse(message=f"Profile {profile_id} deleted")
