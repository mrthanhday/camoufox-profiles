"""
cfox-server FastAPI application factory.

Self-hosted profile management server with PostgreSQL backend.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

from camoufox_profiles.db import create_engine, create_session_factory, init_db
from camoufox_profiles.models import _new_id, _utcnow
from camoufox_profiles.models_sa import UserModel

from .config import ServerSettings, get_settings
from .middleware import hash_api_key

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server startup/shutdown lifecycle."""
    settings: ServerSettings = app.state.settings

    # Initialize database engine
    engine = create_engine(settings.database_url)
    await init_db(engine)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory

    # Ensure storage directory exists
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    # Bootstrap admin user if ADMIN_API_KEY is set and no admin exists
    await _bootstrap_admin(session_factory, settings.admin_api_key)

    # Start background lock cleanup
    from .services.lock_service import LockCleanupService
    lock_cleanup = LockCleanupService(session_factory, settings)
    lock_cleanup.start()
    app.state.lock_cleanup = lock_cleanup

    logger.info(
        "cfox-server started on %s:%d (db=%s)",
        settings.host, settings.port,
        settings.database_url.split("@")[-1] if "@" in settings.database_url else "local",
    )

    yield

    # Shutdown
    lock_cleanup.stop()
    await engine.dispose()
    logger.info("cfox-server stopped")


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    """Create the FastAPI app with all routes mounted."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="cfox-server",
        version="0.1.0",
        description="Self-hosted Camoufox profile management server",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Register routes
    from .routes import locks, profiles, storage, users

    app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"])
    app.include_router(locks.router, prefix="/api/profiles", tags=["locks"])
    app.include_router(storage.router, prefix="/api/profiles", tags=["storage"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "cfox-server"}

    return app


async def _bootstrap_admin(session_factory, admin_api_key: str) -> None:
    """Create initial admin user if none exists."""
    async with session_factory() as session:
        result = await session.execute(
            select(UserModel).where(UserModel.role == "admin")
        )
        if result.scalar_one_or_none():
            return  # Admin already exists

    # Generate or use provided key
    api_key = admin_api_key or secrets.token_urlsafe(32)

    async with session_factory() as session:
        admin = UserModel(
            id=_new_id(),
            username="admin",
            api_key_hash=hash_api_key(api_key),
            role="admin",
            label="Bootstrap admin",
            created_at=_utcnow().isoformat(),
        )
        session.add(admin)
        await session.commit()

    if not admin_api_key:
        # Don't log raw API key to stdout — write it to a file with restrictive
        # permissions so log aggregators don't accidentally capture it.
        from pathlib import Path
        out_dir = Path("data")
        out_dir.mkdir(parents=True, exist_ok=True)
        key_file = out_dir / "admin_api_key.generated"
        key_file.write_text(api_key, encoding="utf-8")
        try:
            # Best effort POSIX 0600 permissions
            import os
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        logger.warning(
            "Admin API key auto-generated and written to %s. "
            "Read it once, then move/secure the file. It will not be shown again.",
            key_file,
        )
    else:
        logger.info("Admin user bootstrapped with provided ADMIN_API_KEY")
