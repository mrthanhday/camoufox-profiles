"""
cfox-local FastAPI application.

Single-process server that wraps V2 ProfileManager with REST + WebSocket API.
Serves the Web UI as static files when built.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .routes import browser, health, profiles, proxies, tags, ws
from .session_manager import BrowserSessionManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifecycle: init ProfileManager + BSM on startup, cleanup on shutdown."""
    from camoufox_profiles.manager import ProfileManager

    settings: Settings = app.state.settings

    # Initialize V2 ProfileManager
    pm = ProfileManager(settings.base_dir)
    await pm.initialize()
    app.state.profile_manager = pm

    # Initialize BrowserSessionManager
    db_path = settings.base_dir / "sessions.db"
    bsm = BrowserSessionManager(profile_manager=pm, db_path=db_path)
    app.state.session_manager = bsm

    # Recover sessions from previous crash
    await bsm.recover_on_startup()

    # Inject dependencies into routes
    profiles.init_routes(pm, bsm)
    browser.init_routes(pm, bsm)
    health.init_routes(pm)
    proxies.init_routes(pm)
    tags.init_routes(pm)

    logger.info("cfox-local started on %s:%d", settings.host, settings.port)
    logger.info("Base directory: %s", settings.base_dir)
    logger.info("Machine ID: %s", settings.machine_id)

    yield

    # Shutdown
    logger.info("Shutting down cfox-local...")
    await bsm.shutdown()
    await pm.close()
    logger.info("cfox-local stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = Settings.load()

    app = FastAPI(
        title="cfox-local",
        description="Camoufox Profile Launcher API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings

    # CORS for Vite dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",  # Vite dev
            "http://127.0.0.1:5173",
            f"http://localhost:{settings.port}",
            f"http://127.0.0.1:{settings.port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # System info endpoint
    @app.get("/api/info", tags=["system"])
    async def system_info():
        """Return machine identity and system info for the UI."""
        import platform
        return {
            "machine_id": settings.machine_id,
            "hostname": platform.node(),
            "version": "0.3.0",
            "platform": platform.system().lower(),
            "max_tags_per_profile": settings.max_tags_per_profile,
        }

    # Include route modules
    app.include_router(profiles.router)
    app.include_router(browser.router)
    app.include_router(health.router)
    app.include_router(proxies.router)
    app.include_router(tags.router)
    app.include_router(ws.router)

    # Serve built Web UI if available
    ui_dist = Path(__file__).parent.parent / "cfox_ui" / "dist"
    if ui_dist.exists():
        app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
    else:
        @app.get("/")
        async def root():
            return {
                "service": "cfox-local",
                "version": "0.1.0",
                "docs": "/docs",
                "note": "Web UI not built. Run 'npm run build' in cfox_ui/",
            }

    return app
