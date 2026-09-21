"""
Win32 window manipulation for FlexiOrder.

`Win32Backend` is the only place that touches the OS; the carousel logic talks
to it through the small `WindowBackend` protocol (see carousel.py), which keeps
the scheduling logic testable without real windows.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process

from . import vdesktop

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

# Per-monitor DPI awareness: without it, coordinates on scaled monitors are
# virtualised and borderless sizing / monitor detection is wrong.
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    pass

DWMWA_TRANSITIONS_FORCEDISABLE = 3
DWMWA_CLOAKED = 14
MONITOR_DEFAULTTONEAREST = 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

BLOCKED_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW",
    "DV2ControlHost", "MsgrIMEWindowClass", "SysShadow", "Button",
    "tooltips_class32", "Windows.UI.Core.CoreWindow",
}
UI_TITLE_MARK = "FlexiOrder #"

FULLSCREEN_MODES = ("none", "borderless", "f11")


# ──────────────────────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────────────────────
def _set_transitions(hwnd: int, disabled: bool) -> None:
    val = ctypes.c_int(1 if disabled else 0)
    try:
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), DWMWA_TRANSITIONS_FORCEDISABLE,
                                     ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def _cloaked(hwnd: int) -> int:
    val = ctypes.c_int(0)
    try:
        dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                     ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        return 0
    return val.value


def _exe_name(hwnd: int) -> str:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _is_candidate(hwnd: int) -> bool:
    """Top-level, user-facing application window (on any virtual desktop)."""
    if not win32gui.IsWindowVisible(hwnd):
        return False
    title = win32gui.GetWindowText(hwnd).strip()
    if len(title) < 2 or UI_TITLE_MARK in title or title == "Program Manager":
        return False
    if win32gui.GetClassName(hwnd) in BLOCKED_CLASSES:
        return False
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return False
    if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
        return False
    # Cloaked windows on the *current* desktop are really hidden (suspended
    # UWP apps etc.). Windows on other desktops are cloaked too — keep those.
    if _cloaked(hwnd) and vdesktop.is_on_current(hwnd):
        return False
    return True


def _rect_covers(outer, inner) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


# ──────────────────────────────────────────────────────────────
# Backend
# ──────────────────────────────────────────────────────────────
class Win32Backend:
    """Real implementation of the carousel's WindowBackend protocol."""

    def __init__(self) -> None:
        # hwnd -> (style, placement) saved before going borderless
        self._saved_styles: dict[int, tuple[int, tuple]] = {}
        self._lock = threading.Lock()  # SetForegroundWindow dance is not re-entrant

    # ── Monitors ────────────────────────────────────────────
    def list_monitors(self) -> list[dict]:
        out = []
        for hmon, _, _ in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(hmon)
            out.append({
                "id": info["Device"],
                "rect": list(info["Monitor"]),
                "work": list(info["Work"]),
                "primary": bool(info["Flags"] & win32con.MONITORINFOF_PRIMARY),
            })
        out.sort(key=lambda m: (not m["primary"], m["rect"][0], m["rect"][1]))
        for i, m in enumerate(out):
            w, h = m["rect"][2] - m["rect"][0], m["rect"][3] - m["rect"][1]
            m["name"] = f"Monitor {i + 1}" + (" (principale)" if m["primary"] else "")
            m["size"] = f"{w}×{h}"
        return out

    def _monitor_info(self, monitor_id: str) -> dict | None:
        return next((m for m in self.list_monitors() if m["id"] == monitor_id), None)

    def monitor_of(self, hwnd: int) -> str | None:
        try:
            hmon = win32api.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            return win32api.GetMonitorInfo(hmon)["Device"]
        except Exception:
            return None

    # ── Windows ─────────────────────────────────────────────
    def candidate_hwnds(self) -> list[int]:
        hwnds: list[int] = []
        win32gui.EnumWindows(lambda h, _: hwnds.append(h) if _is_candidate(h) else None, None)
        return hwnds

    def list_windows(self) -> list[dict]:
        out = []
        for hwnd in self.candidate_hwnds():
            try:
                out.append({
                    "hwnd": hwnd,
                    "title": win32gui.GetWindowText(hwnd),
                    "exe": _exe_name(hwnd),
                    "monitor": self.monitor_of(hwnd),
                    "desktop": vdesktop.window_desktop_id(hwnd),
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                })
            except Exception:
                continue  # window vanished mid-enumeration
        return out

    def window_info(self, hwnd: int) -> dict | None:
        if not self.is_window(hwnd):
            return None
        return {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "exe": _exe_name(hwnd)}

    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd) and bool(win32gui.IsWindow(hwnd))

    def foreground(self) -> int:
        return win32gui.GetForegroundWindow() or 0

    def title_of(self, hwnd: int) -> str:
        try:
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    def find_title(self, fragment: str) -> int:
        found: list[int] = []

        def _cb(h, _):
            if fragment in win32gui.GetWindowText(h):
                found.append(h)
        win32gui.EnumWindows(_cb, None)
        return found[0] if found else 0

    # ── Virtual desktops ────────────────────────────────────
    def list_desktops(self) -> list[dict]:
        return vdesktop.list_desktops()

    def current_desktop(self) -> str | None:
        known = [d["id"] for d in vdesktop.list_desktops()]
        fg = self.foreground()
        hwnds = ([fg] if fg else []) + self.candidate_hwnds()
        return vdesktop.current_desktop_id(hwnds, known)

    def is_on_current_desktop(self, hwnd: int) -> bool:
        return vdesktop.is_on_current(hwnd)

    # ── Showing ─────────────────────────────────────────────
    def show(self, hwnd: int, monitor_id: str, mode: str, focus: bool) -> bool:
        """
        Bring `hwnd` to the top of `monitor_id`.
        focus=False raises it without stealing keyboard focus, so carousels on
        different monitors can run side by side. Returns False if the window
        is gone.
        """
        if not self.is_window(hwnd):
            return False
        mon = self._monitor_info(monitor_id)
        _set_transitions(hwnd, True)
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE if focus else win32con.SW_SHOWNOACTIVATE)

            if mon and mode != "borderless":
                self.restore_window(hwnd)  # mode changed away from borderless
                if self.monitor_of(hwnd) != monitor_id:
                    self._move_to_monitor(hwnd, mon)

            if mon and mode == "borderless":
                self._make_borderless(hwnd, mon)

            if focus or mode == "f11":
                self._focus(hwnd)
            else:
                self._raise_no_focus(hwnd)

            if mode == "f11" and mon:
                self._ensure_f11(hwnd, mon)
        except Exception as e:  # never let one bad window kill the carousel
            print(f"[winapi] show({hwnd}) failed: {e}")
        finally:
            _set_transitions(hwnd, False)
        return True

    def restore_window(self, hwnd: int) -> None:
        """Undo borderless mode for `hwnd`, if we applied it."""
        with self._lock:
            saved = self._saved_styles.pop(hwnd, None)
        if not saved or not self.is_window(hwnd):
            return
        style, placement = saved
        try:
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
            win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                                  | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)
            win32gui.SetWindowPlacement(hwnd, placement)
        except Exception as e:
            print(f"[winapi] restore({hwnd}) failed: {e}")

    def restore_all(self) -> None:
        for hwnd in list(self._saved_styles):
            self.restore_window(hwnd)

    # ── internals ───────────────────────────────────────────
    def _move_to_monitor(self, hwnd: int, mon: dict) -> None:
        was_max = user32.IsZoomed(hwnd)
        if was_max:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)  # un-maximise to move
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        wl, wt, wr, wb = mon["work"]
        w, h = min(r - l, wr - wl), min(b - t, wb - wt)
        win32gui.SetWindowPos(hwnd, 0, wl + (wr - wl - w) // 2, wt + (wb - wt - h) // 2, w, h,
                              win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        if was_max:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

    def _make_borderless(self, hwnd: int, mon: dict) -> None:
        l, t, r, b = mon["rect"]
        with self._lock:
            already = hwnd in self._saved_styles
        if already and tuple(win32gui.GetWindowRect(hwnd)) == (l, t, r, b):
            return
        if not already:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            placement = win32gui.GetWindowPlacement(hwnd)
            with self._lock:
                self._saved_styles[hwnd] = (style, placement)
            if user32.IsZoomed(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE,
                                   style & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME))
        win32gui.SetWindowPos(hwnd, 0, l, t, r - l, b - t,
                              win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_FRAMECHANGED)

    def _raise_no_focus(self, hwnd: int) -> None:
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW
        was_topmost = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOPMOST
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        if not was_topmost:
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    def _focus(self, hwnd: int) -> bool:
        with self._lock:
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            self._raise_no_focus(hwnd)
            fg = win32gui.GetForegroundWindow()
            me = win32api.GetCurrentThreadId()
            other = win32process.GetWindowThreadProcessId(fg)[0] if fg else me
            attached = other != me and bool(user32.AttachThreadInput(me, other, True))
            try:
                user32.AllowSetForegroundWindow(-1)
                user32.SetForegroundWindow(hwnd)
                if win32gui.GetForegroundWindow() != hwnd:
                    # Anti-focus-stealing fallback: a synthetic ALT tap counts
                    # as user input. Tapped twice so no app is left in menu mode.
                    for _ in range(2):
                        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                    user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(me, other, False)
            return win32gui.GetForegroundWindow() == hwnd

    def _ensure_f11(self, hwnd: int, mon: dict) -> None:
        """Press F11 only if the window is not already fullscreen (F11 toggles)."""
        if _rect_covers(win32gui.GetWindowRect(hwnd), mon["rect"]):
            return
        # Never send F11 to whatever else happens to have focus.
        if win32gui.GetForegroundWindow() != hwnd:
            return
        win32api.keybd_event(win32con.VK_F11, 0, 0, 0)
        time.sleep(0.01)
        win32api.keybd_event(win32con.VK_F11, 0, win32con.KEYEVENTF_KEYUP, 0)
