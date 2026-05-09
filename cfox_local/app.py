"""
cfox-local FastAPI application.

Single-process server that wraps V2 ProfileManager with REST + WebSocket API.
Serves the Web UI as static files when built.
"""

from __future__ import annotations

import logging
import string
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings
from .routes import browser, health, profiles, proxies, tags, ws
from .session_manager import BrowserSessionManager

logger = logging.getLogger(__name__)


# ── Request models for settings ──────────────────────────────────

class UpdateSettingsRequest(BaseModel):
    base_dir: Optional[str] = None
    max_tags_per_profile: Optional[int] = None


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


def _calc_dir_size(path: Path) -> int:
    """Calculate total size of all files in a directory (recursive)."""
    try:
        return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
    except (OSError, PermissionError):
        return 0


def _count_profiles(path: Path) -> int:
    """Count profile directories (each has a meta.json)."""
    try:
        return sum(1 for f in path.glob('*/meta.json') if f.is_file())
    except (OSError, PermissionError):
        return 0


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

    # ── Settings endpoints ───────────────────────────────────────

    @app.get("/api/settings", tags=["settings"])
    async def get_settings():
        """Return current application settings with storage stats."""
        pm = app.state.profile_manager
        try:
            profiles = await pm.store.list()
            profile_count = len(profiles)
        except Exception:
            profile_count = 0
        return {
            **settings.to_dict(),
            "profile_count": profile_count,
            "storage_size_bytes": _calc_dir_size(settings.base_dir),
        }

    @app.put("/api/settings", tags=["settings"])
    async def update_settings(body: UpdateSettingsRequest):
        """Update application settings. Returns restart_required if base_dir changed."""
        changed_fields: List[str] = []

        if body.base_dir is not None:
            path = Path(body.base_dir)
            if not path.exists():
                # Try to create if parent exists
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot create directory: {e}",
                    )
            if not path.is_dir():
                raise HTTPException(
                    status_code=400,
                    detail="Path is not a directory",
                )
            settings.base_dir = path
            changed_fields.append("base_dir")

        if body.max_tags_per_profile is not None:
            if body.max_tags_per_profile < 1 or body.max_tags_per_profile > 100:
                raise HTTPException(
                    status_code=400,
                    detail="max_tags_per_profile must be between 1 and 100",
                )
            settings.max_tags_per_profile = body.max_tags_per_profile
            changed_fields.append("max_tags_per_profile")

        settings.save()

        return {
            **settings.to_dict(),
            "restart_required": "base_dir" in changed_fields,
            "changed_fields": changed_fields,
        }

    @app.get("/api/settings/browse", tags=["settings"])
    async def browse_directories(path: str = Query(..., description="Directory path to list")):
        """List subdirectories for the directory browser UI."""
        target = Path(path)
        if not target.exists():
            raise HTTPException(status_code=400, detail="Path does not exist")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        dirs: List[Dict[str, str]] = []
        try:
            for entry in sorted(target.iterdir(), key=lambda e: e.name.lower()):
                if entry.is_dir() and not entry.name.startswith('.'):
                    dirs.append({
                        "name": entry.name,
                        "path": str(entry),
                    })
        except PermissionError:
            raise HTTPException(status_code=403, detail="Permission denied")

        parent = str(target.parent) if target.parent != target else None
        return {
            "current": str(target),
            "parent": parent,
            "directories": dirs,
        }

    @app.get("/api/settings/drives", tags=["settings"])
    async def list_drives():
        """List available drives (Windows) or root (Unix)."""
        import platform as _platform
        if _platform.system() == "Windows":
            drives = []
            for letter in string.ascii_uppercase:
                p = Path(f"{letter}:\\")
                if p.exists():
                    drives.append({"name": f"{letter}:\\", "path": f"{letter}:\\"})
            return {"drives": drives}
        return {"drives": [{"name": "/", "path": "/"}]}

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
