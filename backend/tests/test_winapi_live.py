"""
Live tests against real windows (they briefly pop up Tk windows).

    set FLEXIORDER_LIVE=1 && python -m pytest tests/test_winapi_live.py -v

The multi-monitor test runs only when 2+ monitors are connected.
"""

import os
import subprocess
import sys
import textwrap
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("FLEXIORDER_LIVE") != "1", reason="set FLEXIORDER_LIVE=1")

TK = textwrap.dedent("""
    import sys, tkinter as tk
    r = tk.Tk(); r.title(sys.argv[1]); r.geometry("480x280+150+150")
    tk.Label(r, text=sys.argv[1], font=("Segoe UI", 24)).pack(expand=True)
    r.after(30000, r.destroy); r.mainloop()
""")


@pytest.fixture
def be():
    from flexiorder.winapi import Win32Backend
    return Win32Backend()


@pytest.fixture
def spawn(tmp_path, be):
    script = tmp_path / "tkwin.py"
    script.write_text(TK)
    procs = []

    def _spawn(title):
        procs.append(subprocess.Popen([sys.executable, str(script), title]))
        for _ in range(50):
            hwnd = be.find_title(title)
            if hwnd:
                time.sleep(0.3)
                return hwnd
            time.sleep(0.1)
        raise RuntimeError("test window did not appear")

    yield _spawn
    be.restore_all()
    for p in procs:
        p.kill()


def test_window_listing_has_metadata(be, spawn):
    hwnd = spawn("FO-Live-List")
    w = next(w for w in be.list_windows() if w["hwnd"] == hwnd)
    assert w["exe"].startswith("python") and w["monitor"] and not w["minimized"]


def test_focus_switching(be, spawn):
    a, b = spawn("FO-Live-A"), spawn("FO-Live-B")
    mon = be.monitor_of(a)
    for target in (a, b, a):
        be.show(target, mon, "none", focus=True)
        time.sleep(0.2)
        assert be.foreground() == target


def test_minimized_window_is_restored(be, spawn):
    import win32con
    import win32gui
    a = spawn("FO-Live-Min")
    win32gui.ShowWindow(a, win32con.SW_MINIMIZE)
    time.sleep(0.3)
    be.show(a, be.monitor_of(a), "none", focus=False)
    time.sleep(0.3)
    assert not win32gui.IsIconic(a)


def test_borderless_and_restore(be, spawn):
    import win32con
    import win32gui
    a = spawn("FO-Live-Border")
    mon_id = be.monitor_of(a)
    mon = next(m for m in be.list_monitors() if m["id"] == mon_id)
    style0, rect0 = win32gui.GetWindowLong(a, win32con.GWL_STYLE), win32gui.GetWindowRect(a)

    be.show(a, mon_id, "borderless", focus=False)
    time.sleep(0.3)
    assert list(win32gui.GetWindowRect(a)) == mon["rect"]
    assert not win32gui.GetWindowLong(a, win32con.GWL_STYLE) & win32con.WS_CAPTION

    be.restore_window(a)
    time.sleep(0.3)
    assert win32gui.GetWindowLong(a, win32con.GWL_STYLE) == style0
    assert win32gui.GetWindowRect(a) == rect0


def test_move_to_other_monitor(be, spawn):
    mons = be.list_monitors()
    if len(mons) < 2:
        pytest.skip("needs 2+ monitors")
    a = spawn("FO-Live-Move")
    src = be.monitor_of(a)
    dst = next(m["id"] for m in mons if m["id"] != src)
    be.show(a, dst, "none", focus=False)
    time.sleep(0.3)
    assert be.monitor_of(a) == dst
