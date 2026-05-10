"""API key authentication middleware for cfox-server."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from camoufox_profiles.models import _utcnow
from camoufox_profiles.models_sa import UserModel

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class AuthUser:
    """Authenticated user context."""

    def __init__(self, user_id: str, username: str, role: str):
        self.user_id = user_id
        self.username = username
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


async def get_current_user(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> AuthUser:
    """
    Resolve authenticated user from X-API-Key header.

    Looks up the hashed key in the users table. Updates last_used_at.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    session_factory = request.app.state.session_factory
    key_hash = hash_api_key(api_key)

    async with session_factory() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.api_key_hash == key_hash)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Update last_used_at
        await session.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(last_used_at=_utcnow().isoformat())
        )
        await session.commit()

    return AuthUser(user_id=user.id, username=user.username, role=user.role)


async def require_admin(
    user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Require admin role."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
