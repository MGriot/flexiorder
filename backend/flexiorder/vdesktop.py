"""
Virtual desktop detection using only documented / read-only interfaces:

* IVirtualDesktopManager (public COM) – which desktop a window lives on.
* Registry (read-only) – ordered desktop list, names and, on builds that write
  it, the current desktop.

Switching or moving windows across desktops is deliberately NOT done: the only
public API for that (MoveWindowToDesktop) works for the caller's own windows.
If anything fails, callers get the single fallback desktop DEFAULT_DESKTOP.
"""

from __future__ import annotations

import ctypes
import threading
import uuid
import winreg
from ctypes import wintypes

DEFAULT_DESKTOP = "default"
_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Explorer"

_tls = threading.local()


def _norm(guid) -> str:
    return str(guid).strip("{}").lower()


# ── COM ──────────────────────────────────────────────────────────
try:
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class IVirtualDesktopManager(IUnknown):
        _iid_ = GUID("{a5cd92ff-29be-454c-8d04-d82879fb3f1b}")
        _methods_ = [
            COMMETHOD([], HRESULT, "IsWindowOnCurrentVirtualDesktop",
                      (["in"], wintypes.HWND, "topLevelWindow"),
                      (["out", "retval"], ctypes.POINTER(wintypes.BOOL), "onCurrentDesktop")),
            COMMETHOD([], HRESULT, "GetWindowDesktopId",
                      (["in"], wintypes.HWND, "topLevelWindow"),
                      (["out", "retval"], ctypes.POINTER(GUID), "desktopId")),
            COMMETHOD([], HRESULT, "MoveWindowToDesktop",
                      (["in"], wintypes.HWND, "topLevelWindow"),
                      (["in"], ctypes.POINTER(GUID), "desktopId")),
        ]

    _CLSID_VDM = GUID("{aa509086-5ca9-4c25-8f95-589d3c07b48a}")
    HAS_COM = True
except Exception:  # pragma: no cover - comtypes missing
    HAS_COM = False


def _manager():
    """One IVirtualDesktopManager per thread (COM objects are apartment-bound)."""
    if not HAS_COM:
        return None
    mgr = getattr(_tls, "mgr", False)
    if mgr is False:
        try:
            comtypes.CoInitialize()
        except OSError:
            pass  # already initialised in this thread
        try:
            mgr = comtypes.CoCreateInstance(_CLSID_VDM, interface=IVirtualDesktopManager)
        except Exception:
            mgr = None
        _tls.mgr = mgr
    return mgr


def window_desktop_id(hwnd: int) -> str | None:
    mgr = _manager()
    if mgr is None:
        return None
    try:
        gid = _norm(mgr.GetWindowDesktopId(hwnd))
    except Exception:
        return None
    return None if gid == _norm(uuid.UUID(int=0)) else gid


def is_on_current(hwnd: int) -> bool:
    mgr = _manager()
    if mgr is None:
        return True
    try:
        return bool(mgr.IsWindowOnCurrentVirtualDesktop(hwnd))
    except Exception:
        return True


# ── Registry ─────────────────────────────────────────────────────
def _read_value(path: str, name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _guid_list(blob) -> list[str]:
    if not isinstance(blob, (bytes, bytearray)):
        return []
    return [_norm(uuid.UUID(bytes_le=bytes(blob[i:i + 16]))) for i in range(0, len(blob) - 15, 16)]


def list_desktops() -> list[dict]:
    """Ordered [{id, name, index}] – falls back to one DEFAULT_DESKTOP."""
    ids = _guid_list(_read_value(_ROOT + r"\VirtualDesktops", "VirtualDesktopIDs"))
    if not ids:
        return [{"id": DEFAULT_DESKTOP, "name": "Desktop 1", "index": 0}]
    out = []
    for i, gid in enumerate(ids):
        name = _read_value(_ROOT + rf"\VirtualDesktops\Desktops\{{{gid.upper()}}}", "Name")
        out.append({"id": gid, "name": name or f"Desktop {i + 1}", "index": i})
    return out


def _registry_current() -> str | None:
    for path in (_ROOT + r"\VirtualDesktops",):
        ids = _guid_list(_read_value(path, "CurrentVirtualDesktop"))
        if ids:
            return ids[0]
    # Older builds keep it per session.
    session = ctypes.c_ulong()
    try:
        ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(),
                                                    ctypes.byref(session))
        ids = _guid_list(_read_value(_ROOT + rf"\SessionInfo\{session.value}\VirtualDesktops",
                                     "CurrentVirtualDesktop"))
        if ids:
            return ids[0]
    except Exception:
        pass
    return None


def current_desktop_id(candidate_hwnds: list[int], known_ids: list[str]) -> str | None:
    """
    Current desktop GUID. Uses the registry when available, otherwise votes
    among top-level windows that report being on the current desktop.
    Returns None when it cannot be determined (e.g. an empty desktop).
    """
    if known_ids == [DEFAULT_DESKTOP]:
        return DEFAULT_DESKTOP
    reg = _registry_current()
    if reg:
        return reg
    votes: dict[str, int] = {}
    for hwnd in candidate_hwnds:
        if not is_on_current(hwnd):
            continue
        gid = window_desktop_id(hwnd)
        if gid in known_ids:
            votes[gid] = votes.get(gid, 0) + 1
    return max(votes, key=votes.get) if votes else None
