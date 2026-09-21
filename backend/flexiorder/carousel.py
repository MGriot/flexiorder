"""
Carousel scheduling.

One `Carousel` per (virtual desktop, monitor) key, each with its own thread,
sequence and timers, so every screen on every desktop rotates independently.
`CarouselManager` owns them all plus the shared, cached OS state (current
desktop, management-UI window).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Protocol

from .vdesktop import DEFAULT_DESKTOP

POLL = 0.2  # seconds between pause/stop checks while a window is shown


class WindowBackend(Protocol):
    def is_window(self, hwnd: int) -> bool: ...
    def foreground(self) -> int: ...
    def title_of(self, hwnd: int) -> str: ...
    def monitor_of(self, hwnd: int) -> str | None: ...
    def is_on_current_desktop(self, hwnd: int) -> bool: ...
    def current_desktop(self) -> str | None: ...
    def show(self, hwnd: int, monitor_id: str, mode: str, focus: bool) -> bool: ...
    def restore_window(self, hwnd: int) -> None: ...


def make_key(desktop: str, monitor: str) -> str:
    return f"{desktop}|{monitor}"


def normalize_item(raw: dict) -> dict:
    mode = raw.get("mode") or ("f11" if raw.get("force_f11") else "none")
    try:
        timer = float(raw.get("timer") or 5)
    except (TypeError, ValueError):
        timer = 5.0
    return {
        "id": raw.get("id") or uuid.uuid4().hex[:12],
        "hwnd": int(raw.get("hwnd") or 0),
        "title": str(raw.get("title") or ""),
        "exe": str(raw.get("exe") or ""),
        "timer": max(timer, 0.01),
        "mode": mode if mode in ("none", "borderless", "f11") else "none",
        "missing": bool(raw.get("missing", False)),
    }


class Carousel:
    def __init__(self, manager: "CarouselManager", desktop: str, monitor: str):
        self.manager = manager
        self.desktop = desktop
        self.monitor = monitor
        self.key = make_key(desktop, monitor)
        self.items: list[dict] = []
        self.index = 0
        self.active_id: str | None = None
        self.status = "stopped"  # stopped|running|paused|paused_ui|desktop_hidden|empty
        self.manual_pause = False
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop: threading.Event | None = None
        self._wake = threading.Event()  # interrupts the timer (sequence edits, resume)

    # ── public API ──────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_items(self, items: list[dict], trust_flags: bool = False) -> None:
        """Replace the sequence. `missing` is backend-owned unless trust_flags."""
        with self._lock:
            old = {i["id"]: i for i in self.items}
            new = [normalize_item(i) for i in items]
            for it in new:
                if not trust_flags and it["id"] in old and old[it["id"]]["hwnd"] == it["hwnd"]:
                    it["missing"] = old[it["id"]]["missing"]
            removed = set(old) - {i["id"] for i in new}
            changed_mode = [i for i in new if i["id"] in old and old[i["id"]]["mode"] == "borderless"
                            and i["mode"] != "borderless"]
            self.items = new
            if self.active_id and self.active_id not in {i["id"] for i in new}:
                self.active_id = None
            if self.items:
                self.index %= len(self.items)
            else:
                self.index = 0
        for rid in removed:
            self.manager.backend.restore_window(old[rid]["hwnd"])
        for it in changed_mode:
            self.manager.backend.restore_window(it["hwnd"])
        self._wake.set()

    def start(self) -> bool:
        with self._lock:
            if self.running:
                return False
            self.manual_pause = False
            self.index = 0
            self.active_id = None
            # A fresh Event per run: a lingering old thread keeps its own
            # (already set) event and can never be revived by a new start.
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,), daemon=True,
                                            name=f"carousel-{self.key}")
            self._set_status("running")
            self._thread.start()
            return True

    def stop(self, restore: bool = True) -> None:
        with self._lock:
            stop, thread = self._stop, self._thread
            self._thread = None
            self._stop = None
        if stop:
            stop.set()
            self._wake.set()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        if restore:
            for it in list(self.items):
                self.manager.backend.restore_window(it["hwnd"])
        with self._lock:
            self.active_id = None
            self.manual_pause = False
            self._set_status("stopped")

    def pause(self) -> None:
        self.manual_pause = True
        self._wake.set()

    def resume(self) -> None:
        self.manual_pause = False
        self._wake.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "key": self.key,
                "desktop": self.desktop,
                "monitor": self.monitor,
                "items": [dict(i) for i in self.items],
                "index": self.index,
                "active_id": self.active_id,
                "status": self.status,
                "running": self.running,
            }

    # ── loop ────────────────────────────────────────────────
    def _set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.manager.notify()

    def _hold_reason(self) -> str | None:
        """Why the carousel should not rotate right now (None = go)."""
        if self.manual_pause:
            return "paused"
        if not self.manager.desktop_visible(self.desktop):
            return "desktop_hidden"
        if self.manager.ui_focused_on(self.monitor):
            return "paused_ui"
        return None

    def _next_item(self) -> dict | None:
        """Next showable item starting at self.index; marks closed windows missing."""
        be = self.manager.backend
        changed = False
        with self._lock:
            n = len(self.items)
            for step in range(n):
                idx = (self.index + step) % n
                it = self.items[idx]
                if not be.is_window(it["hwnd"]):
                    if not it["missing"]:
                        it["missing"] = True
                        changed = True
                    continue
                if it["missing"]:
                    it["missing"] = False
                    changed = True
                # Never show a window that lives on another virtual desktop:
                # activating it would make Windows switch desktops.
                if self.desktop != DEFAULT_DESKTOP and not be.is_on_current_desktop(it["hwnd"]):
                    continue
                self.index = idx
                if changed:
                    self.manager.notify()
                return it
        if changed:
            self.manager.notify()
        return None

    def _run(self, stop: threading.Event) -> None:
        be = self.manager.backend
        try:
            while not stop.is_set():
                self._wake.clear()
                reason = self._hold_reason()
                if reason:
                    self._set_status(reason)
                    self._wake.wait(0.3)
                    continue

                item = self._next_item() if self.items else None
                if item is None:
                    with self._lock:
                        self.active_id = None
                    self._set_status("empty")
                    self._wake.wait(0.5)
                    continue

                # Take focus only where the user already is (the foreground
                # window is on this monitor) or when F11 needs it; otherwise
                # raise silently so other screens keep their focus.
                focus = be.monitor_of(be.foreground()) == self.monitor
                if stop.is_set():
                    break
                be.show(item["hwnd"], self.monitor, item["mode"], focus)
                with self._lock:
                    self.active_id = item["id"]
                    self.status = "running"
                self.manager.notify()

                deadline = time.monotonic() + item["timer"]
                interrupted = False
                while not stop.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    if self._hold_reason():
                        interrupted = True
                        break
                    if self._wake.wait(min(POLL, remaining)):
                        self._wake.clear()
                        with self._lock:  # shown item removed → move on now
                            if item["id"] not in {i["id"] for i in self.items}:
                                break

                if interrupted or stop.is_set():
                    continue  # re-show the same window after the pause
                with self._lock:
                    ids = [i["id"] for i in self.items]
                    if ids:
                        pos = ids.index(item["id"]) + 1 if item["id"] in ids else self.index
                        self.index = pos % len(ids)
        except Exception as e:  # keep the process alive; surface the error
            print(f"[carousel {self.key}] crashed: {e}")
        finally:
            with self._lock:
                if self._stop is stop:  # we died on our own, not via stop()
                    self._thread = None
                    self._stop = None
                    self.active_id = None
                    self.status = "stopped"
            self.manager.notify()


class CarouselManager:
    def __init__(self, backend: WindowBackend, on_change: Callable[[], None] | None = None,
                 desktop_ttl: float = 0.5):
        self.backend = backend
        # Must be non-blocking (it is called while carousel locks are held).
        self.on_change = on_change or (lambda: None)
        self.carousels: dict[str, Carousel] = {}
        self.ui_token = ""  # unique marker the management UI puts in its page title
        self._lock = threading.Lock()
        self._desktop_ttl = desktop_ttl
        self._desktop_cache: tuple[float, str | None] = (0.0, None)

    def get(self, desktop: str, monitor: str) -> Carousel:
        key = make_key(desktop, monitor)
        with self._lock:
            if key not in self.carousels:
                self.carousels[key] = Carousel(self, desktop, monitor)
            return self.carousels[key]

    def notify(self) -> None:
        try:
            self.on_change()
        except Exception as e:
            print(f"[manager] on_change failed: {e}")

    def current_desktop(self) -> str | None:
        ts, val = self._desktop_cache
        now = time.monotonic()
        if now - ts > self._desktop_ttl:
            try:
                val = self.backend.current_desktop()
            except Exception:
                val = None
            self._desktop_cache = (now, val)
        return val

    def desktop_visible(self, desktop: str) -> bool:
        if desktop == DEFAULT_DESKTOP:
            return True
        cur = self.current_desktop()
        # Unknown (e.g. empty desktop): allow; per-window checks still protect.
        return cur is None or cur == desktop

    def ui_focused_on(self, monitor: str) -> bool:
        """Smart Pause: the FlexiOrder UI tab is focused on this monitor."""
        if not self.ui_token:
            return False
        fg = self.backend.foreground()
        return bool(fg) and self.ui_token in self.backend.title_of(fg) and self.backend.monitor_of(fg) == monitor

    def stop_all(self) -> None:
        for c in list(self.carousels.values()):
            c.stop()

    def snapshot(self) -> list[dict]:
        return [c.snapshot() for c in list(self.carousels.values())]
