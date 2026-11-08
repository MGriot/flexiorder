"""
Browser tab discovery/selection through Windows UI Automation.

A browser window is a single hwnd, so individual tabs can only be reached
through the accessibility tree: every tab is a `TabItem` control that supports
`SelectionItemPattern`. Works with Chromium browsers and Firefox.
"""

from __future__ import annotations

import re
import threading
import time

BROWSER_EXES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "vivaldi.exe", "chromium.exe", "arc.exe",
}
UIA_TABITEM = 50019
UIA_SELECTIONITEM_PATTERN = 10010
TREE_DESCENDANTS = 4
PREFIX = 20

_tls = threading.local()
_uia_module = None


# Chromium appends live status to tab names ("… - Memory usage - 418 MB").
_STATUS = re.compile(r"\s+[-–—]\s+(?:High memory usage|Memory usage|Inactive tab|Sleeping tab|"
                     r"Discarded tab|Tab sleeping|Audio playing|Camera|Microphone).*$", re.I)


def clean(name: str) -> str:
    return _STATUS.sub("", name or "").strip()


def is_browser(exe: str) -> bool:
    return exe.lower() in BROWSER_EXES


def _uia():
    """One IUIAutomation per thread (COM objects are apartment-bound)."""
    global _uia_module
    import comtypes
    import comtypes.client

    if getattr(_tls, "uia", None) is None:
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        if _uia_module is None:
            _uia_module = comtypes.client.GetModule("UIAutomationCore.dll")
        _tls.uia = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=_uia_module.IUIAutomation)
    return _uia_module, _tls.uia


def _tab_elements(hwnd: int):
    mod, uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    cond = uia.CreatePropertyCondition(30003, UIA_TABITEM)  # UIA_ControlTypePropertyId
    found = root.FindAll(TREE_DESCENDANTS, cond)
    return mod, [found.GetElement(i) for i in range(found.Length)]


def _find(hwnd: int):
    # Chromium builds its accessibility tree lazily on the first UIA request.
    for attempt in range(3):
        mod, elems = _tab_elements(hwnd)
        if elems:
            return mod, elems
        time.sleep(0.3)
    return None, []


def list_tabs(hwnd: int, hide_mark: str = "") -> list[str]:
    """Names of the tabs of browser window `hwnd` (tabs containing `hide_mark` skipped)."""
    try:
        _, elems = _find(hwnd)
        names = [clean(e.CurrentName) for e in elems]
    except Exception as e:
        print(f"[tabs] list({hwnd}) failed: {e}")
        return []
    return [n for n in names if n and not (hide_mark and hide_mark in n)]


def match_tab(names: list[str], wanted: str) -> int:
    """Index of the tab best matching `wanted` (exact, then shared prefix), or -1."""
    for i, n in enumerate(names):
        if n == wanted:
            return i
    p = wanted[:PREFIX]
    if p:
        for i, n in enumerate(names):
            if n[:PREFIX] == p:
                return i
    return -1


def select_tab(hwnd: int, wanted: str) -> bool:
    """Make the tab named `wanted` the active one. True when it is (or already was) selected."""
    try:
        mod, elems = _find(hwnd)
        idx = match_tab([clean(e.CurrentName) for e in elems], clean(wanted))
        if idx < 0:
            return False
        pattern = elems[idx].GetCurrentPattern(UIA_SELECTIONITEM_PATTERN)
        pattern.QueryInterface(mod.IUIAutomationSelectionItemPattern).Select()
        return True
    except Exception as e:
        print(f"[tabs] select({hwnd}, {wanted!r}) failed: {e}")
        return False
