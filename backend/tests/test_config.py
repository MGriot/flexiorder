from flexiorder import config


def W(hwnd, title, exe="app.exe"):
    return {"hwnd": hwnd, "title": title, "exe": exe}


def test_keeps_valid_hwnd():
    out = config.rematch([{"hwnd": 5, "title": "Doc", "exe": "app.exe"}], [W(5, "Doc (edited)")])
    assert out[0]["hwnd"] == 5 and not out[0]["missing"] and out[0]["title"] == "Doc (edited)"


def test_rebinds_by_exe_and_title_after_restart():
    saved = [{"hwnd": 1, "title": "Dashboard - Grafana", "exe": "chrome.exe"},
             {"hwnd": 2, "title": "Notes.txt - Notepad", "exe": "notepad.exe"}]
    live = [W(70, "Notes.txt - Notepad", "notepad.exe"), W(80, "Dashboard - Grafana", "chrome.exe")]
    out = config.rematch(saved, live)
    assert [i["hwnd"] for i in out] == [80, 70]


def test_does_not_steal_window_owned_by_later_item():
    saved = [{"id": "a", "hwnd": 1, "title": "Same", "exe": "app.exe"},   # dead handle
             {"id": "b", "hwnd": 9, "title": "Same", "exe": "app.exe"}]   # still valid
    out = config.rematch(saved, [W(9, "Same")])
    assert out[1]["hwnd"] == 9 and not out[1]["missing"]
    assert out[0]["missing"]


def test_exe_mismatch_is_missing():
    out = config.rematch([{"hwnd": 1, "title": "X", "exe": "a.exe"}], [W(2, "X", "b.exe")])
    assert out[0]["missing"]


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "cfg" / "config.json"
    config.save(p, [{"desktop": "d1", "monitor": "M1",
                     "items": [{"id": "x", "hwnd": 1, "title": "t", "exe": "e", "timer": 3, "mode": "f11",
                                "missing": False}]},
                    {"desktop": "d2", "monitor": "M1", "items": []}])
    data = config.load(p)
    assert len(data["carousels"]) == 1
    assert data["carousels"][0]["items"][0]["mode"] == "f11"
    assert config.load(tmp_path / "nope.json") == {}


def test_tab_and_refresh_roundtrip_and_shared_window(tmp_path):
    from flexiorder import config
    items = [
        {"id": "a", "hwnd": 10, "title": "Inbox", "exe": "chrome.exe", "timer": 5, "tab": "Inbox", "refresh": "mid"},
        {"id": "b", "hwnd": 10, "title": "Cal", "exe": "chrome.exe", "timer": 5, "tab": "Cal", "refresh": "off"},
    ]
    p = tmp_path / "c.json"
    config.save(p, [{"desktop": "d", "monitor": "M", "items": items}])
    saved = config.load(p)["carousels"][0]["items"]
    assert [(i["tab"], i["refresh"]) for i in saved] == [("Inbox", "mid"), ("Cal", "off")]

    # window handle changed after restart: both tabs re-bind to the one live browser window
    live = [{"hwnd": 99, "title": "Whatever - Google Chrome", "exe": "chrome.exe", "browser": True}]
    out = config.rematch(saved, live)
    assert [(i["hwnd"], i["missing"]) for i in out] == [(99, False), (99, False)]
