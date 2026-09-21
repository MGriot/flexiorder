import pytest
from fastapi.testclient import TestClient

from conftest import FakeBackend


@pytest.fixture
def client(tmp_path, monkeypatch):
    from flexiorder import app as appmod

    fake = FakeBackend()
    fake.add(1, "M1", "d1", "Notepad")
    fake.list_desktops = lambda: [{"id": "d1", "name": "Desktop 1", "index": 0}]
    fake.list_monitors = lambda: [{"id": "M1", "name": "Monitor 1", "rect": [0, 0, 10, 10],
                                   "work": [0, 0, 10, 10], "primary": True, "size": "10×10"}]
    fake.list_windows = lambda: [{"hwnd": 1, "title": "Notepad", "exe": "notepad.exe",
                                  "monitor": "M1", "desktop": "d1", "minimized": False}]
    fake.find_title = lambda frag: 0
    monkeypatch.setattr(appmod.rt, "backend", fake)
    monkeypatch.setattr(appmod.rt.manager, "backend", fake)
    monkeypatch.setattr(appmod.rt, "config_path", tmp_path / "config.json")
    appmod.rt.manager.carousels.clear()
    with TestClient(appmod.app) as c:
        yield c
    appmod.rt.manager.carousels.clear()


def test_full_flow(client, tmp_path):
    st = client.get("/api/state").json()
    assert st["monitors"][0]["id"] == "M1" and st["current_desktop"] == "d1"
    assert client.get("/api/windows").json()["windows"][0]["exe"] == "notepad.exe"

    target = {"desktop": "d1", "monitor": "M1"}
    assert client.post("/api/carousel/start", json=target).status_code == 400  # empty

    r = client.put("/api/carousel/sequence",
                   json={**target, "items": [{"hwnd": 1, "title": "Notepad", "timer": 2, "mode": "borderless"}]})
    assert r.json() == {"ok": True, "count": 1}
    assert client.post("/api/carousel/start", json=target).json()["ok"] is True

    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["carousels"][0]["items"][0]["mode"] == "borderless"

    assert client.post("/api/carousel/stop", json=target).json()["ok"] is True


def test_validation(client):
    bad = {"desktop": "d1", "monitor": "M1", "items": [{"hwnd": 1, "timer": 0}]}
    assert client.put("/api/carousel/sequence", json=bad).status_code == 422
    assert client.post("/api/carousel/explode", json={"desktop": "d1", "monitor": "M1"}).status_code == 422


def test_ws_rejects_foreign_origin(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
