"""System tray icon for cfox-local."""

from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _create_default_icon() -> Any:
    """Create a simple icon (green circle) without requiring an icon file."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Green circle with dark border
        draw.ellipse([4, 4, 60, 60], fill=(34, 197, 94, 255), outline=(20, 120, 60, 255), width=2)
        # "C" letter in white
        draw.text((22, 14), "C", fill=(255, 255, 255, 255))
        return img
    except Exception:
        # Fallback: solid color square
        from PIL import Image
        return Image.new("RGB", (64, 64), (34, 197, 94))


def run_tray(
    port: int = 7600,
    on_quit: Optional[Callable] = None,
) -> None:
    """
    Run the system tray icon (blocks the calling thread).

    Args:
        port: cfox-local port for "Open UI" action.
        on_quit: Callback when user clicks "Quit".
    """
    try:
        import pystray
    except ImportError:
        logger.warning("pystray not installed — running without system tray")
        return

    def open_ui(icon: Any, item: Any) -> None:
        webbrowser.open(f"http://localhost:{port}")

    def quit_app(icon: Any, item: Any) -> None:
        icon.stop()
        if on_quit:
            on_quit()

    icon = pystray.Icon(
        name="cfox-local",
        icon=_create_default_icon(),
        title="Camoufox Launcher",
        menu=pystray.Menu(
            pystray.MenuItem("Open UI", open_ui, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        ),
    )

    logger.info("System tray started")
    icon.run()
