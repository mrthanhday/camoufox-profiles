"""cfox-server entry point for uvicorn."""

import uvicorn

from .app import create_app
from .config import get_settings


def main():
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
