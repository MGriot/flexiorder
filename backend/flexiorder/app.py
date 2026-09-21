"""
FlexiOrder HTTP/WebSocket API.

Every carousel is addressed by (desktop, monitor). The full state is pushed to
all WebSocket clients whenever anything changes, so the UI just renders it.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__, config
from .carousel import CarouselManager
from .winapi import Win32Backend

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
WATCH_INTERVAL = 1.0      # desktop switch / monitor hot-plug detection
REMATCH_INTERVAL = 3.0    # retry binding "missing" windows (e.g. app reopened)


# ──────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────
class Item(BaseModel):
    id: str | None = None
    hwnd: int
    title: str = ""
    exe: str = ""
    timer: float = Field(5, ge=1, le=3600)
    mode: Literal["none", "borderless", "f11"] = "none"
    missing: bool = False


class Target(BaseModel):
    desktop: str
    monitor: str


class SequenceUpdate(Target):
    items: list[Item]


class SelfRegister(BaseModel):
    token: str = Field(min_length=6, max_length=64)


# ──────────────────────────────────────────────────────────────
# Runtime
# ──────────────────────────────────────────────────────────────
class Runtime:
    def __init__(self, config_path: Path | None = None):
        self.backend = Win32Backend()
        self.manager = CarouselManager(self.backend, on_change=self.notify)
        self.config_path = config_path or config.default_path()
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.env = {"desktops": [], "current_desktop": None, "monitors": []}
        self._pending = False
        self._save_timer: threading.Timer | None = None

    # ── state push ──────────────────────────────────────────
    def notify(self) -> None:
        """Thread-safe, coalesced broadcast request (never blocks the caller)."""
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._schedule_flush)

    def _schedule_flush(self) -> None:
        if not self._pending:
            self._pending = True
            asyncio.get_running_loop().call_later(0.05, lambda: asyncio.ensure_future(self._flush()))

    async def _flush(self) -> None:
        self._pending = False
        payload = json.dumps({"type": "state", **self.state()})
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def state(self) -> dict:
        return {**self.env, "carousels": self.manager.snapshot(), "version": __version__}

    # ── environment (desktops / monitors) ───────────────────
    def refresh_env(self) -> bool:
        env = {
            "desktops": self.backend.list_desktops(),
            "current_desktop": self.manager.current_desktop(),
            "monitors": self.backend.list_monitors(),
        }
        changed = env != self.env
        self.env = env
        return changed

    def rematch_missing(self) -> None:
        carousels = [c for c in self.manager.carousels.values() if any(i["missing"] for i in c.items)]
        if not carousels:
            return
        windows = self.backend.list_windows()
        for c in carousels:
            items = c.snapshot()["items"]
            fixed = config.rematch(items, windows)
            if [i["hwnd"] for i in fixed] != [i["hwnd"] for i in items] or \
                    [i["missing"] for i in fixed] != [i["missing"] for i in items]:
                c.set_items(fixed, trust_flags=True)
                self.notify()
                self.save_soon()

    # ── persistence ─────────────────────────────────────────
    def load(self) -> None:
        data = config.load(self.config_path)
        saved = data.get("carousels") or []
        if not saved:
            return
        windows = self.backend.list_windows()
        for c in saved:
            if c.get("desktop") and c.get("monitor"):
                self.manager.get(c["desktop"], c["monitor"]).set_items(
                    config.rematch(c.get("items") or [], windows), trust_flags=True)

    def save_soon(self) -> None:
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.5, self.save_now)
        self._save_timer.daemon = True
        self._save_timer.start()

    def save_now(self) -> None:
        try:
            config.save(self.config_path, self.manager.snapshot())
        except OSError as e:
            print(f"[config] save failed: {e}")


rt = Runtime()


async def _watcher() -> None:
    ticks = 0
    while True:
        await asyncio.sleep(WATCH_INTERVAL)
        ticks += 1
        try:
            if await asyncio.to_thread(rt.refresh_env):
                rt.notify()
            if ticks % int(REMATCH_INTERVAL / WATCH_INTERVAL) == 0:
                await asyncio.to_thread(rt.rematch_missing)
        except Exception as e:
            print(f"[watcher] {e}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    rt.loop = asyncio.get_running_loop()
    await asyncio.to_thread(rt.load)
    await asyncio.to_thread(rt.refresh_env)
    task = asyncio.create_task(_watcher())
    try:
        yield
    finally:
        task.cancel()
        rt.save_now()
        await asyncio.to_thread(rt.manager.stop_all)  # also restores borderless windows


app = FastAPI(title="FlexiOrder", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_ORIGIN.pattern,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# REST
# ──────────────────────────────────────────────────────────────
@app.get("/api/state")
def get_state():
    return rt.state()


@app.get("/api/windows")
def list_windows():
    return {"windows": rt.backend.list_windows()}


@app.put("/api/carousel/sequence")
def update_sequence(body: SequenceUpdate):
    c = rt.manager.get(body.desktop, body.monitor)
    c.set_items([i.model_dump() for i in body.items])
    rt.notify()
    rt.save_soon()
    return {"ok": True, "count": len(c.items)}


@app.post("/api/carousel/{action}")
def carousel_action(action: Literal["start", "stop", "pause", "resume"], body: Target):
    c = rt.manager.get(body.desktop, body.monitor)
    if action == "start":
        if not c.items:
            raise HTTPException(400, "La sequenza è vuota")
        ok = c.start()
    else:
        getattr(c, action)()
        ok = True
    rt.notify()
    return {"ok": ok}


@app.post("/api/stop-all")
def stop_all():
    rt.manager.stop_all()
    rt.notify()
    return {"ok": True}


@app.post("/api/self")
def register_self(body: SelfRegister):
    """The UI puts `FlexiOrder #<token>` in its title; used for Smart Pause."""
    rt.manager.ui_token = f"#{body.token}"
    hwnd = rt.backend.find_title(rt.manager.ui_token)
    return {"ok": True, "found": bool(hwnd), "monitor": rt.backend.monitor_of(hwnd) if hwnd else None}


# ──────────────────────────────────────────────────────────────
# WebSocket
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    origin = ws.headers.get("origin")
    if origin and not LOCAL_ORIGIN.match(origin):
        await ws.close(code=1008)
        return
    await ws.accept()
    rt.clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "state", **rt.state()}))
        while True:
            await ws.receive_text()  # keep-alive; client messages are ignored
    except WebSocketDisconnect:
        pass
    finally:
        rt.clients.discard(ws)


# ──────────────────────────────────────────────────────────────
# Built UI (npm run build → backend/static)
# ──────────────────────────────────────────────────────────────
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
