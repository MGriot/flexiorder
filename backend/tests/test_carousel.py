import threading
import time

from conftest import items, wait_until


def test_rotates_and_wraps(manager, backend):
    for h in (1, 2, 3):
        backend.add(h)
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2, 3))
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 5)
    assert backend.shown_hwnds()[:5] == [1, 2, 3, 1, 2]


def test_closed_window_marked_missing_and_skipped(manager, backend):
    for h in (1, 2, 3):
        backend.add(h)
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2, 3))
    del backend.windows[2]
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 4)
    assert 2 not in backend.shown_hwnds()
    assert next(i for i in c.snapshot()["items"] if i["hwnd"] == 2)["missing"] is True
    assert c.running


def test_all_windows_gone_goes_empty_not_crash(manager, backend):
    c = manager.get("d1", "M1")
    c.set_items(items(9))
    c.start()
    assert wait_until(lambda: c.status == "empty")
    assert c.running


def test_shrinking_sequence_while_running(manager, backend):
    for h in range(1, 6):
        backend.add(h)
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2, 3, 4, 5, timer=0.05))
    c.start()
    for _ in range(30):  # hammer edits from another thread
        c.set_items(items(1))
        c.set_items(items(1, 2, 3, 4, 5, timer=0.05))
        time.sleep(0.01)
    c.set_items(items(1))
    assert c.running
    n = len(backend.shown)
    assert wait_until(lambda: len(backend.shown) > n + 2)
    assert set(backend.shown_hwnds()[n + 1:]) == {1}


def test_removing_active_item_moves_on_immediately(manager, backend):
    backend.add(1)
    backend.add(2)
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2, timer=30))
    c.start()
    assert wait_until(lambda: backend.shown_hwnds() == [1])
    c.set_items(items(2, timer=30))
    assert wait_until(lambda: backend.shown_hwnds() == [1, 2], timeout=1)
    assert 1 in backend.restored


def test_stop_then_start_leaves_single_thread(manager, backend):
    backend.add(1)
    c = manager.get("d1", "M1")
    c.set_items(items(1))
    for _ in range(5):
        c.start()
        c.stop()
    c.start()
    time.sleep(0.2)
    threads = [t for t in threading.enumerate() if t.name == f"carousel-{c.key}"]
    assert len(threads) == 1
    assert c.start() is False  # already running


def test_monitors_rotate_independently(manager, backend):
    for h in (1, 2):
        backend.add(h, "M1")
    for h in (11, 12):
        backend.add(h, "M2")
    a, b = manager.get("d1", "M1"), manager.get("d1", "M2")
    a.set_items(items(1, 2, timer=0.05))
    b.set_items(items(11, 12, timer=0.4))
    a.start()
    b.start()
    time.sleep(0.9)
    on1, on2 = backend.shown_hwnds("M1"), backend.shown_hwnds("M2")
    assert set(on1) == {1, 2} and set(on2) == {11, 12}
    assert len(on1) > 2 * len(on2)  # faster timer, own schedule
    a.pause()
    assert wait_until(lambda: a.status == "paused")
    n2 = len(backend.shown_hwnds("M2"))
    assert wait_until(lambda: len(backend.shown_hwnds("M2")) > n2 + 1)  # M2 unaffected


def test_no_focus_stealing_from_other_monitor(manager, backend):
    backend.add(1, "M1")
    backend.add(2, "M1")
    backend.add(50, "M2", title="Editor")  # user is working on monitor 2
    backend.fg = 50
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2))
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 3)
    assert all(focus is False for *_, focus in backend.shown)
    assert backend.fg == 50


def test_takes_focus_when_user_is_on_same_monitor(manager, backend):
    backend.add(1, "M1")
    backend.add(2, "M1")
    backend.fg = 1
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2))
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 2)
    assert backend.shown[0][3] is True


def test_hidden_desktop_idles_and_resumes(manager, backend):
    backend.add(1, desktop="d1")
    backend.add(2, desktop="d2")
    c1, c2 = manager.get("d1", "M1"), manager.get("d2", "M1")
    c1.set_items(items(1))
    c2.set_items(items(2))
    c1.start()
    c2.start()
    assert wait_until(lambda: c2.status == "desktop_hidden")
    assert wait_until(lambda: 1 in backend.shown_hwnds())
    assert 2 not in backend.shown_hwnds()
    backend.desktop = "d2"
    assert wait_until(lambda: c1.status == "desktop_hidden")
    assert wait_until(lambda: 2 in backend.shown_hwnds())


def test_never_shows_window_from_other_desktop(manager, backend):
    backend.add(1, desktop="d1")
    backend.add(2, desktop="d2")  # wrongly added to d1's carousel
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2))
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 3)
    assert 2 not in backend.shown_hwnds()


def test_smart_pause_only_on_ui_monitor(manager, backend):
    backend.add(1, "M1")
    backend.add(2, "M1")
    backend.add(11, "M2")
    backend.add(12, "M2")
    backend.add(99, "M1", title="FlexiOrder #abc123 - Browser")
    manager.ui_token = "#abc123"
    a, b = manager.get("d1", "M1"), manager.get("d1", "M2")
    a.set_items(items(1, 2))
    b.set_items(items(11, 12))
    backend.fg = 99
    a.start()
    b.start()
    assert wait_until(lambda: a.status == "paused_ui")
    assert wait_until(lambda: len(backend.shown_hwnds("M2")) >= 3)
    assert backend.shown_hwnds("M1") == []
    backend.fg = 11  # user leaves the UI
    assert wait_until(lambda: len(backend.shown_hwnds("M1")) >= 1)


def test_f11_not_repressed_when_already_fullscreen(manager, backend):
    backend.add(1)
    backend.add(2)
    c = manager.get("d1", "M1")
    c.set_items(items(1, 2, mode="f11"))
    c.start()
    assert wait_until(lambda: len(backend.shown) >= 6)
    assert sorted(backend.f11_presses) == [1, 2]


def test_stop_restores_windows(manager, backend):
    backend.add(1)
    c = manager.get("d1", "M1")
    c.set_items(items(1, mode="borderless"))
    c.start()
    assert wait_until(lambda: backend.shown)
    c.stop()
    assert 1 in backend.restored
    assert c.status == "stopped" and not c.running


def test_switching_away_from_borderless_restores(manager, backend):
    backend.add(1)
    c = manager.get("d1", "M1")
    c.set_items(items(1, mode="borderless"))
    c.set_items(items(1, mode="none"))
    assert backend.restored == [1]


def test_timer_and_mode_are_sanitised(manager):
    c = manager.get("d1", "M1")
    c.set_items([{"hwnd": 1, "timer": "abc", "mode": "weird"}, {"hwnd": 2, "force_f11": True}])
    snap = c.snapshot()["items"]
    assert snap[0]["timer"] == 5 and snap[0]["mode"] == "none" and snap[0]["id"]
    assert snap[1]["mode"] == "f11"
