"""Lock management routes for cfox-server."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update

from camoufox_profiles.models import _utcnow
from camoufox_profiles.models_sa import ProfileModel

from ..middleware import AuthUser, get_current_user, require_admin
from ..schemas import (
    HeartbeatRequest,
    LockRequest,
    LockResponse,
    MessageResponse,
    UnlockRequest,
)

router = APIRouter()


@router.post("/{profile_id}/lock", response_model=LockResponse)
async def lock_profile(
    profile_id: str,
    data: LockRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Acquire a lock on a profile before launching.

    Returns a lock_token that must be sent with heartbeats and unlock.
    If the profile is already locked by another machine, returns 409.
    Re-locking by the same machine reissues the token.
    """
    now = _utcnow()
    expires = now + timedelta(minutes=data.ttl_minutes)
    lock_token = secrets.token_urlsafe(24)

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        previous_lock = None

        # Check if already locked by someone else
        if model.locked_by and model.locked_by != data.machine_id:
            # Check if lock has expired
            if model.lock_expires_at:
                lock_exp = datetime.fromisoformat(model.lock_expires_at)
                if lock_exp.tzinfo is None:
                    lock_exp = lock_exp.replace(tzinfo=timezone.utc)
                if lock_exp > now:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Profile locked by {model.locked_by} until {model.lock_expires_at}",
                    )
            # Lock expired — record previous lock for info
            previous_lock = {
                "locked_by": model.locked_by,
                "locked_at": model.locked_at,
                "expired_at": model.lock_expires_at,
            }

        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                locked_by=data.machine_id,
                lock_token=lock_token,
                locked_at=now.isoformat(),
                lock_expires_at=expires.isoformat(),
                last_heartbeat_at=now.isoformat(),
            )
        )
        await session.commit()

    return LockResponse(
        lock_token=lock_token,
        locked_by=data.machine_id,
        locked_at=now.isoformat(),
        lock_expires_at=expires.isoformat(),
        essential_data_version=model.essential_data_version or 0,
        previous_lock=previous_lock,
    )


@router.post("/{profile_id}/heartbeat", response_model=MessageResponse)
async def heartbeat(
    profile_id: str,
    data: HeartbeatRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Renew the lock TTL.

    Must be called every 30s by the client. Validates lock_token + machine_id.
    """
    now = _utcnow()
    settings = request.app.state.settings

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        if model.lock_token != data.lock_token or model.locked_by != data.machine_id:
            raise HTTPException(status_code=403, detail="Lock ownership mismatch")

        new_expires = now + timedelta(minutes=settings.lock_ttl_minutes)

        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                last_heartbeat_at=now.isoformat(),
                lock_expires_at=new_expires.isoformat(),
            )
        )
        await session.commit()

    return MessageResponse(message="Heartbeat accepted", detail=new_expires.isoformat())


@router.post("/{profile_id}/unlock", response_model=MessageResponse)
async def unlock_profile(
    profile_id: str,
    data: UnlockRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """
    Release a lock after session ends.

    Validates lock_token + machine_id before releasing.
    """
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        if model.lock_token != data.lock_token or model.locked_by != data.machine_id:
            raise HTTPException(status_code=403, detail="Lock ownership mismatch")

        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                locked_by=None,
                lock_token=None,
                locked_at=None,
                lock_expires_at=None,
                last_heartbeat_at=None,
            )
        )
        await session.commit()

    return MessageResponse(message="Profile unlocked")


@router.post("/{profile_id}/force-unlock", response_model=MessageResponse)
async def force_unlock_profile(
    profile_id: str,
    request: Request,
    user: AuthUser = Depends(require_admin),
):
    """Force-unlock a profile (admin only). Used for stuck locks."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(ProfileModel).where(ProfileModel.id == profile_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Profile not found")

        if not model.locked_by:
            return MessageResponse(message="Profile was not locked")

        previous_owner = model.locked_by

        await session.execute(
            update(ProfileModel)
            .where(ProfileModel.id == profile_id)
            .values(
                locked_by=None,
                lock_token=None,
                locked_at=None,
                lock_expires_at=None,
                last_heartbeat_at=None,
            )
        )
        await session.commit()

    return MessageResponse(message=f"Force-unlocked profile (was locked by {previous_owner})")
