"""
System-tray icon for the portable build: open the UI in the browser, or quit.

pystray needs the main thread, so the server runs in a background thread and
"Esci" asks it to shut down (the lifespan then restores windows and saves).
"""

from __future__ import annotations

import threading
import webbrowser

from PIL import Image, ImageDraw

ACCENT = (79, 140, 255, 255)


def make_icon(size: int = 64) -> Image.Image:
    """Two overlapping rounded squares (the ⧉ glyph), drawn so no asset is needed."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    w = max(2, round(5 * s))
    r = round(8 * s)
    d.rounded_rectangle((22 * s, 4 * s, 60 * s, 42 * s), radius=r, outline=ACCENT, width=w)
    d.rounded_rectangle((4 * s, 22 * s, 42 * s, 60 * s), radius=r, fill=ACCENT)
    return img


def run_tray(url: str, server, server_thread: threading.Thread) -> None:
    """Blocks until "Esci" is chosen or the server thread ends (e.g. it failed to start)."""
    import pystray

    def _open(icon=None, item=None):
        webbrowser.open(url)

    def _quit(icon, item=None):
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        "FlexiOrder",
        make_icon(),
        f"FlexiOrder – {url}",
        menu=pystray.Menu(
            pystray.MenuItem("Apri FlexiOrder", _open, default=True),
            pystray.MenuItem("Esci", _quit),
        ),
    )

    def _setup(icon):
        icon.visible = True
        server_thread.join()
        icon.stop()

    icon.run(setup=_setup)
