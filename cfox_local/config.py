"""Configuration for cfox-local server."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _default_base_dir() -> Path:
    """Default profile storage directory."""
    return Path.home() / ".cfox" / "profiles"


def _default_config_dir() -> Path:
    """Default config directory."""
    return Path.home() / ".cfox"


@dataclass
class Settings:
    """cfox-local server settings."""

    # Server
    host: str = "127.0.0.1"
    port: int = 7600

    # Profile storage
    base_dir: Path = field(default_factory=_default_base_dir)

    # Machine identity (auto-generated, persisted)
    machine_id: str = ""

    # Cloud server (Phase 3)
    server_url: Optional[str] = None
    server_api_key: Optional[str] = None

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        if not self.machine_id:
            self.machine_id = _load_or_create_machine_id()

    @classmethod
    def load(cls) -> Settings:
        """Load settings from config file and env vars."""
        import os

        config_path = _default_config_dir() / "config.json"
        data: dict = {}

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        # Env vars override file config
        if env_host := os.environ.get("CFOX_HOST"):
            data["host"] = env_host
        if env_port := os.environ.get("CFOX_PORT"):
            data["port"] = int(env_port)
        if env_dir := os.environ.get("CFOX_BASE_DIR"):
            data["base_dir"] = env_dir
        if env_url := os.environ.get("CFOX_SERVER_URL"):
            data["server_url"] = env_url
        if env_key := os.environ.get("CFOX_SERVER_API_KEY"):
            data["server_api_key"] = env_key

        return cls(**data)

    def save(self) -> None:
        """Persist settings to config file."""
        config_dir = _default_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"

        data = {
            "host": self.host,
            "port": self.port,
            "base_dir": str(self.base_dir),
        }
        if self.server_url:
            data["server_url"] = self.server_url
        if self.server_api_key:
            data["server_api_key"] = self.server_api_key

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def _load_or_create_machine_id() -> str:
    """Load machine_id from disk or create a new one."""
    config_dir = _default_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    id_path = config_dir / "machine_id"

    if id_path.exists():
        return id_path.read_text(encoding="utf-8").strip()

    machine_id = str(uuid.uuid4())
    id_path.write_text(machine_id, encoding="utf-8")
    return machine_id
