"""cfox-server configuration via environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class ServerSettings(BaseSettings):
    """
    cfox-server configuration.

    All values can be set via environment variables (case-insensitive).
    Example: DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/cfox
    """

    database_url: str = "postgresql+asyncpg://cfox:cfox@localhost:5432/cfox"
    storage_dir: Path = Path("data/essential_data")
    host: str = "0.0.0.0"
    port: int = 8700
    lock_ttl_minutes: int = 120
    lock_cleanup_interval_seconds: int = 60
    max_versions: int = 3
    admin_api_key: str = ""  # Initial admin key, set via env var
    # Upload size cap to protect against runaway browser data dumps (default 256 MB).
    max_upload_bytes: int = 256 * 1024 * 1024

    model_config = {"env_prefix": "", "case_sensitive": False}


def get_settings() -> ServerSettings:
    """Load settings from environment."""
    return ServerSettings()
