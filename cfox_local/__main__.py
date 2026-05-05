"""
cfox-local entry point.

Usage:
    # Development (no tray, console output):
    python -m cfox_local

    # Production (with system tray):
    python -m cfox_local --tray

    # Or via console script:
    cfox-local
    cfox-local --tray
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import threading
from typing import Optional

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Camoufox Profile Launcher")
    parser.add_argument("--host", default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    parser.add_argument("--base-dir", default=None, help="Profile storage directory")
    parser.add_argument("--tray", action="store_true", help="Show system tray icon")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser on start")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Build settings
    from .config import Settings

    settings = Settings.load()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.base_dir:
        from pathlib import Path
        settings.base_dir = Path(args.base_dir)

    # Create app
    from .app import create_app

    app = create_app(settings)

    # Server config
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        log_level=args.log_level.lower(),
        access_log=args.log_level == "DEBUG",
    )
    server = uvicorn.Server(config)

    if args.tray:
        _run_with_tray(server, settings, not args.no_browser)
    else:
        # Simple mode — just run uvicorn
        if not args.no_browser:
            import webbrowser
            threading.Timer(1.5, lambda: webbrowser.open(
                f"http://localhost:{settings.port}"
            )).start()
        server.run()


def _run_with_tray(server: uvicorn.Server, settings: Any, open_browser: bool) -> None:
    """Run uvicorn in a background thread, tray in main thread."""
    from .tray import run_tray

    shutdown_event = threading.Event()

    def run_server() -> None:
        asyncio.run(server.serve())
        shutdown_event.set()

    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Open browser after a short delay
    if open_browser:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(
            f"http://localhost:{settings.port}"
        )).start()

    # Run tray in main thread (blocks)
    def on_quit() -> None:
        server.should_exit = True
        shutdown_event.set()

    run_tray(port=settings.port, on_quit=on_quit)

    # Wait for server to finish
    shutdown_event.wait(timeout=10)


if __name__ == "__main__":
    main()
