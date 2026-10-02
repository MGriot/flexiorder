"""
FlexiOrder demo server – the real API and UI on top of fake windows, monitors
and virtual desktops. Nothing on your desktop is touched; used for the README
screenshots and for trying the UI safely.

    python backend/tools/demo.py [--port 8790]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MONITORS = [
    {"id": r"\\.\DISPLAY1", "rect": [0, 0, 2560, 1440], "work": [0, 0, 2560, 1392], "primary": True,
     "name": "Monitor 1 (principale)", "size": "2560×1440"},
    {"id": r"\\.\DISPLAY2", "rect": [2560, 0, 4480, 1080], "work": [2560, 0, 4480, 1032], "primary": False,
     "name": "Monitor 2", "size": "1920×1080"},
]
DESKTOPS = [
    {"id": "d-ops", "name": "Control room", "index": 0},
    {"id": "d-dev", "name": "Sviluppo", "index": 1},
]
# hwnd, title, exe, monitor index, desktop
WINDOWS = [
    (101, "Grafana – Production overview", "chrome.exe", 0, "d-ops"),
    (102, "Kibana – Error logs (last 15 min)", "chrome.exe", 0, "d-ops"),
    (103, "Status page – All systems operational", "msedge.exe", 0, "d-ops"),
    (104, "Power BI – Sales dashboard", "PBIDesktop.exe", 1, "d-ops"),
    (105, "Jira – Sprint board", "chrome.exe", 1, "d-ops"),
    (106, "Outlook – Inbox", "olk.exe", 1, "d-ops"),
    (107, "Teams – Operations channel", "ms-teams.exe", 1, "d-ops"),
    (201, "flexiorder – Visual Studio Code", "Code.exe", 0, "d-dev"),
    (202, "Windows Terminal", "WindowsTerminal.exe", 1, "d-dev"),
]
SEQUENCES = {
    ("d-ops", 0): [(101, 20, "borderless"), (102, 15, "borderless"), (103, 10, "none")],
    ("d-ops", 1): [(104, 30, "f11"), (105, 20, "none")],
}


class DemoBackend:
    def __init__(self):
        self.windows = {h: {"title": t, "exe": e, "monitor": MONITORS[m]["id"], "desktop": d}
                        for h, t, e, m, d in WINDOWS}
        self.desktop = "d-ops"

    def is_window(self, hwnd):
        return hwnd in self.windows

    def foreground(self):
        return 0

    def title_of(self, hwnd):
        return self.windows.get(hwnd, {}).get("title", "")

    def monitor_of(self, hwnd):
        return self.windows.get(hwnd, {}).get("monitor")

    def is_on_current_desktop(self, hwnd):
        return self.windows.get(hwnd, {}).get("desktop") == self.desktop

    def current_desktop(self):
        return self.desktop

    def show(self, hwnd, monitor_id, mode, focus):
        if hwnd not in self.windows:
            return False
        self.windows[hwnd]["monitor"] = monitor_id
        return True

    def restore_window(self, hwnd):
        pass

    def find_title(self, fragment):
        return 0

    def list_monitors(self):
        return MONITORS

    def list_desktops(self):
        return DESKTOPS

    def list_windows(self):
        return [{"hwnd": h, "title": w["title"], "exe": w["exe"], "monitor": w["monitor"],
                 "desktop": w["desktop"], "minimized": False} for h, w in self.windows.items()]


def _demo_config(path: Path) -> None:
    titles = {h: (t, e) for h, t, e, _, _ in WINDOWS}
    carousels = [
        {"desktop": d, "monitor": MONITORS[m]["id"],
         "items": [{"id": f"demo{h}", "hwnd": h, "title": titles[h][0], "exe": titles[h][1],
                    "timer": timer, "mode": mode} for h, timer, mode in seq]}
        for (d, m), seq in SEQUENCES.items()
    ]
    path.write_text(json.dumps({"version": 2, "carousels": carousels}), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="FlexiOrder demo server (fake windows)")
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()

    import uvicorn

    from flexiorder import app as appmod

    fake = DemoBackend()
    appmod.rt.backend = fake
    appmod.rt.manager.backend = fake
    appmod.rt.config_path = Path(tempfile.mkdtemp()) / "config.json"
    _demo_config(appmod.rt.config_path)

    url = f"http://127.0.0.1:{args.port}"

    def _start_first_monitor():
        for _ in range(50):
            try:
                req = urllib.request.Request(
                    url + "/api/carousel/start", method="POST",
                    data=json.dumps({"desktop": "d-ops", "monitor": MONITORS[0]["id"]}).encode(),
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=1)
                return
            except OSError:
                time.sleep(0.2)
    threading.Thread(target=_start_first_monitor, daemon=True).start()

    print(f"FlexiOrder demo at {url}   (Ctrl+C to stop)")
    uvicorn.run(appmod.app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
