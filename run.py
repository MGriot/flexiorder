"""
FlexiOrder – start everything with one command:

    python run.py [--port 8765] [--no-browser] [--tray]

Serves the API and the prebuilt UI (backend/static) on http://127.0.0.1:<port>.
This is also the entry point of the portable FlexiOrder.exe (packaging/build.py),
which always runs in tray mode without a console.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
DEFAULT_PORT = 8765  # 8000 often falls in Hyper-V/WSL reserved port ranges
FROZEN = getattr(sys, "frozen", False)

sys.path.insert(0, str(BACKEND))


def _redirect_output() -> None:
    """A --noconsole exe has no stdout/stderr: send prints to a log beside the config."""
    from flexiorder import config

    try:
        log = open(config.default_path().with_name("flexiorder.log"), "w", encoding="utf-8", buffering=1)
    except OSError:
        log = open(os.devnull, "w")
    sys.stdout = sys.stderr = log


def _is_flexiorder(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1) as r:
            return "carousels" in json.load(r)
    except (OSError, ValueError):
        return False


def _can_bind(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        if _can_bind(port):
            return port
    with socket.socket() as s:  # let the OS choose
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    if FROZEN:
        _redirect_output()
    # Windows consoles may be cp1252; window titles can contain any character.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="FlexiOrder window carousel")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="don't open the UI automatically")
    parser.add_argument("--tray", action="store_true", help="run in the background with a system-tray icon")
    args = parser.parse_args()
    tray = args.tray or FROZEN

    if sys.platform != "win32":
        print("FlexiOrder controls Windows windows and only runs on Windows.")
        return 1
    try:
        import uvicorn  # noqa: F401
        import win32gui  # noqa: F401
        if tray:
            import pystray  # noqa: F401
    except ImportError as e:
        print(f"Missing dependency ({e.name}). Install with:\n"
              f"  pip install -r {BACKEND / 'requirements.txt'}")
        return 1

    # Two backends would fight over the same windows: reuse a running one.
    if _is_flexiorder(args.port):
        url = f"http://127.0.0.1:{args.port}"
        print(f"FlexiOrder is already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    port = _pick_port(args.port)
    if port != args.port:
        print(f"Port {args.port} is unavailable, using {port}.")

    from flexiorder.app import STATIC_DIR, app

    url = f"http://127.0.0.1:{port}"
    if not (STATIC_DIR / "index.html").exists():
        print("UI build not found. Build it once with:\n  cd frontend && npm install && npm run build\n"
              "(or run `npm run dev` for the dev server on http://localhost:5173)")

    if not args.no_browser:
        def _open_when_ready():
            for _ in range(50):
                try:
                    urllib.request.urlopen(url + "/api/state", timeout=1)
                    webbrowser.open(url)
                    return
                except OSError:
                    time.sleep(0.2)
        threading.Thread(target=_open_when_ready, daemon=True).start()

    import uvicorn

    # Localhost only: this API can move every window on the machine.
    if not tray:
        print(f"FlexiOrder running at {url}   (Ctrl+C to stop)")
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        return 0

    from flexiorder.tray import run_tray

    # log_config=None: uvicorn's default handlers need a real console.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_config=None, log_level="warning"))
    thread = threading.Thread(target=server.run, name="uvicorn")
    thread.start()
    print(f"FlexiOrder running at {url}   (tray icon → Esci to stop)")
    try:
        run_tray(url, server, thread)
    finally:
        server.should_exit = True
        thread.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
