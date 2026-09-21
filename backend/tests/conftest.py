import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flexiorder.carousel import CarouselManager  # noqa: E402


class FakeBackend:
    """In-memory WindowBackend: windows live on monitors and desktops."""

    def __init__(self):
        self.windows: dict[int, dict] = {}  # hwnd -> {monitor, desktop, title}
        self.fg = 0
        self.desktop = "d1"
        self.shown: list[tuple[int, str, str, bool]] = []
        self.restored: list[int] = []
        self.fullscreen: set[int] = set()
        self.f11_presses: list[int] = []
        self.lock = threading.Lock()

    def add(self, hwnd, monitor="M1", desktop="d1", title=None):
        self.windows[hwnd] = {"monitor": monitor, "desktop": desktop, "title": title or f"win{hwnd}"}

    # ── protocol ──
    def is_window(self, hwnd):
        return hwnd in self.windows

    def foreground(self):
        return self.fg

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
        with self.lock:
            self.windows[hwnd]["monitor"] = monitor_id
            self.shown.append((hwnd, monitor_id, mode, focus))
            if focus or mode == "f11":
                self.fg = hwnd
            if mode == "f11" and hwnd not in self.fullscreen:  # mirrors Win32Backend._ensure_f11
                self.f11_presses.append(hwnd)
                self.fullscreen.add(hwnd)
        return True

    def restore_window(self, hwnd):
        self.restored.append(hwnd)

    # ── helpers ──
    def shown_hwnds(self, monitor=None):
        with self.lock:
            return [s[0] for s in self.shown if monitor is None or s[1] == monitor]


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def manager(backend):
    m = CarouselManager(backend, desktop_ttl=0)
    yield m
    m.stop_all()


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def items(*hwnds, timer=0.1, mode="none"):
    return [{"id": f"i{h}", "hwnd": h, "title": f"win{h}", "timer": timer, "mode": mode} for h in hwnds]
