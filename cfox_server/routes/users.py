"""User management routes for cfox-server (admin only)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select

from camoufox_profiles.models import _new_id, _utcnow
from camoufox_profiles.models_sa import UserModel

from ..middleware import AuthUser, hash_api_key, require_admin
from ..schemas import MessageResponse, UserCreate, UserListResponse, UserResponse

router = APIRouter()


@router.get("", response_model=UserListResponse)
async def list_users(
    request: Request,
    user: AuthUser = Depends(require_admin),
):
    """List all users (admin only)."""
    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(UserModel).order_by(UserModel.created_at.desc())
        )
        models = result.scalars().all()

    return UserListResponse(
        users=[
            UserResponse(
                id=m.id,
                username=m.username,
                role=m.role,
                label=m.label,
                created_at=m.created_at,
                last_used_at=m.last_used_at,
            )
            for m in models
        ]
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    request: Request,
    user: AuthUser = Depends(require_admin),
):
    """Create a new user (admin only). Returns the API key (shown once)."""
    api_key = secrets.token_urlsafe(32)

    async with request.app.state.session_factory() as session:
        # Check username uniqueness
        result = await session.execute(
            select(UserModel).where(UserModel.username == data.username)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Username '{data.username}' already exists")

        user_model = UserModel(
            id=_new_id(),
            username=data.username,
            api_key_hash=hash_api_key(api_key),
            role=data.role,
            label=data.label,
            created_at=_utcnow().isoformat(),
        )
        session.add(user_model)
        await session.commit()
        await session.refresh(user_model)

    return UserResponse(
        id=user_model.id,
        username=user_model.username,
        role=user_model.role,
        label=user_model.label,
        created_at=user_model.created_at,
        api_key=api_key,  # Only shown once
    )


@router.post("/{user_id}/rotate-key", response_model=UserResponse)
async def rotate_api_key(
    user_id: str,
    request: Request,
    user: AuthUser = Depends(require_admin),
):
    """Rotate a user's API key (admin only). Returns the new key (shown once)."""
    new_key = secrets.token_urlsafe(32)

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="User not found")

        model.api_key_hash = hash_api_key(new_key)
        await session.commit()

    return UserResponse(
        id=model.id,
        username=model.username,
        role=model.role,
        label=model.label,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        api_key=new_key,  # Only shown once
    )


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: str,
    request: Request,
    user: AuthUser = Depends(require_admin),
):
    """Delete a user (admin only). Cannot delete yourself."""
    if user_id == user.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    async with request.app.state.session_factory() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="User not found")

        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.commit()

    return MessageResponse(message=f"User '{model.username}' deleted")
