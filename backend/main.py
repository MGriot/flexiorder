"""
FlexiOrder – Window Carousel Backend
FastAPI + pywin32 + WebSockets
Smart-Pause: carousel halts whenever the management UI window is in foreground.
"""

import asyncio
import ctypes
import json
import threading
import time
from typing import Optional

import httpx
try:
    import win32api
    import win32con
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False
    # Mocking for non-windows platforms (Docker Linux)
    class MockWin32:
        def __getattr__(self, name): return lambda *args, **kwargs: None
    win32api = win32con = win32gui = win32process = MockWin32()

HOST_AGENT_URL = "http://host.docker.internal:8001"


from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ──────────────────────────────────────────────────────────────
# App bootstrap
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="FlexiOrder", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────
class CarouselState:
    def __init__(self):
        self.sequence: list[dict] = []  # [{hwnd, title, timer, force_f11}, …]
        self.running: bool = False
        self.paused_by_app: bool = False
        self.current_index: int = 0
        self.app_hwnd: Optional[int] = None  # HWND of the management browser tab
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()


state = CarouselState()
connected_clients: list[WebSocket] = []


# ──────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────
class WindowItem(BaseModel):
    hwnd: int
    title: str
    timer: int = 5  # seconds
    force_f11: bool = False


class SequenceUpdate(BaseModel):
    items: list[WindowItem]


class StartRequest(BaseModel):
    app_hwnd: int  # Sent by the UI: its own browser HWND


# ──────────────────────────────────────────────────────────────
# Window discovery helpers
# ──────────────────────────────────────────────────────────────
BLOCKED_CLASSES = {
    "Shell_TrayWnd",
    "Progman",
    "WorkerW",
    "DV2ControlHost",
    "MsgrIMEWindowClass",
    "SysShadow",
    "Button",
    "tooltips_class32",
}
BLOCKED_TITLE_FRAGMENTS = {"Program Manager", "FlexiOrder"}


def _is_visible_app_window(hwnd: int) -> bool:
    if not win32gui.IsWindowVisible(hwnd):
        return False
    title = win32gui.GetWindowText(hwnd).strip()
    if not title or len(title) < 2:
        return False
    cls = win32gui.GetClassName(hwnd)
    if cls in BLOCKED_CLASSES:
        return False
    if any(f.lower() in title.lower() for f in BLOCKED_TITLE_FRAGMENTS):
        return False
    # Skip windows without visible, non-iconic placement
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] == win32con.SW_SHOWMINIMIZED:
        return False
    return True


def get_visible_windows() -> list[dict]:
    if not HAS_WIN32:
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.get(f"{HOST_AGENT_URL}/windows")
                return res.json().get("windows", [])
        except Exception as e:
            print(f"Error connecting to Host Agent: {e}")
            return []

    windows = []
    def _cb(hwnd, _):
        if _is_visible_app_window(hwnd):
            windows.append({"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd)})

    win32gui.EnumWindows(_cb, None)
    return windows



def bring_to_front(hwnd: int, force_f11: bool = False) -> bool:
    """Activate a window; returns False if the window no longer exists."""
    if not HAS_WIN32:
        try:
            with httpx.Client(timeout=2.0) as client:
                res = client.post(f"{HOST_AGENT_URL}/activate", json={"hwnd": hwnd, "force_f11": force_f11})
                return res.json().get("ok", False)
        except:
            return False

    try:
        if not win32gui.IsWindow(hwnd):
            return False

        # --- Disable Window Animations (Zero Latency) ---
        try:
            DWMWA_TRANSITIONS_FORCEDISABLE = 3
            disable_anim = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_TRANSITIONS_FORCEDISABLE, ctypes.byref(disable_anim), ctypes.sizeof(disable_anim)
            )
        except Exception:
            pass

        import win32con as wc
        try:
            # Consolidate sizing: Maximize if F11, else Restore
            show_cmd = wc.SW_MAXIMIZE if force_f11 else wc.SW_RESTORE
            win32gui.ShowWindow(hwnd, show_cmd)
            
            # Snap it to top instantly
            win32gui.SetWindowPos(
                hwnd, wc.HWND_TOP, 0, 0, 0, 0,
                wc.SWP_NOMOVE | wc.SWP_NOSIZE | wc.SWP_SHOWWINDOW | wc.SWP_NOACTIVATE
            )
        except Exception as e:
            print(f"Warning: Sizing failed: {e}")

        try:
            # ALT-key hack: bypass Windows anti-focus-stealing
            win32api.keybd_event(wc.VK_MENU, 0, 0, 0)
            win32api.keybd_event(wc.VK_MENU, 0, wc.KEYEVENTF_KEYUP, 0)

            ctypes.windll.user32.AllowSetForegroundWindow(-1)
            current_hwnd = win32gui.GetForegroundWindow()
            if current_hwnd != hwnd:
                current_thread = win32api.GetCurrentThreadId()
                foreground_thread = (
                    win32process.GetWindowThreadProcessId(current_hwnd)[0] if current_hwnd else current_thread
                )
                
                if current_thread != foreground_thread:
                    ctypes.windll.user32.AttachThreadInput(current_thread, foreground_thread, True)
                
                win32gui.SetForegroundWindow(hwnd)
                
                if current_thread != foreground_thread:
                    ctypes.windll.user32.AttachThreadInput(current_thread, foreground_thread, False)
        except Exception as e:
            print(f"Warning: Foreground manipulation failed: {e}")

        if force_f11:
            try:
                # Minimal latency F11 simulation
                win32api.keybd_event(wc.VK_F11, 0, 0, 0)
                time.sleep(0.01) # 10ms instead of 50ms
                win32api.keybd_event(wc.VK_F11, 0, wc.KEYEVENTF_KEYUP, 0)
            except:
                pass

        # --- Re-enable Window Animations ---
        try:
            enable_anim = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_TRANSITIONS_FORCEDISABLE, ctypes.byref(enable_anim), ctypes.sizeof(enable_anim)
            )
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Critical error in bring_to_front: {e}")
        return True # Return True to avoid dropping the window from sequence unexpectedly


# ──────────────────────────────────────────────────────────────
# WebSocket broadcast
# ──────────────────────────────────────────────────────────────
async def _broadcast(payload: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


broadcast_loop = None


@app.on_event("startup")
async def setup_broadcast_loop():
    global broadcast_loop
    broadcast_loop = asyncio.get_running_loop()


def broadcast_sync(payload: dict):
    """Thread-safe fire-and-forget broadcast."""
    if broadcast_loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(payload), broadcast_loop)


# ──────────────────────────────────────────────────────────────
# Carousel loop (runs in a background thread)
# ──────────────────────────────────────────────────────────────
def carousel_loop():
    state._stop_event.clear()

    while not state._stop_event.is_set():
        if not state.sequence:
            if state._stop_event.wait(0.5):
                break
            continue

        # ── Smart Pause ──────────────────────────────────────
        if not HAS_WIN32:
            try:
                with httpx.Client() as client:
                    focused_hwnd = client.get(f"{HOST_AGENT_URL}/get_foreground").json().get("hwnd")
            except:
                focused_hwnd = 0
        else:
            focused_hwnd = win32gui.GetForegroundWindow()

        # If the management app window (the browser) is in focus, hold.
        if state.app_hwnd and focused_hwnd == state.app_hwnd:

            if not state.paused_by_app:
                state.paused_by_app = True
                broadcast_sync(
                    {
                        "type": "status",
                        "running": True,
                        "paused": True,
                        "index": state.current_index,
                    }
                )
            if state._stop_event.wait(0.4):
                break
            continue

        if state.paused_by_app:
            state.paused_by_app = False
            broadcast_sync(
                {
                    "type": "status",
                    "running": True,
                    "paused": False,
                    "index": state.current_index,
                }
            )

        # ── Activate current window ──────────────────────────
        item = state.sequence[state.current_index]
        hwnd, timer, ff = item["hwnd"], item["timer"], item["force_f11"]

        ok = bring_to_front(hwnd, ff)

        if not ok:
            # Window was closed – remove it and notify UI
            state.sequence.pop(state.current_index)
            if state.sequence:
                state.current_index %= len(state.sequence)
            broadcast_sync(
                {
                    "type": "window_closed",
                    "hwnd": hwnd,
                    "sequence": state.sequence,
                }
            )
            continue

        broadcast_sync(
            {
                "type": "status",
                "running": True,
                "paused": False,
                "index": state.current_index,
                "active_hwnd": hwnd,
            }
        )

        # ── Wait for timer, polling for stop/pause ───────────
        deadline = time.monotonic() + timer
        while time.monotonic() < deadline:
            if state._stop_event.is_set():
                return
            focused_now = win32gui.GetForegroundWindow()
            if state.app_hwnd and focused_now == state.app_hwnd:
                break  # management app reclaimed focus → back to top
            if state._stop_event.wait(0.2):
                return

        # ── Advance index ────────────────────────────────────
        if state.sequence:
            state.current_index = (state.current_index + 1) % len(state.sequence)

    state.running = False
    broadcast_sync({"type": "status", "running": False, "paused": False, "index": 0})


# ──────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────
@app.get("/api/windows")
def list_windows():
    return {"windows": get_visible_windows()}


@app.put("/api/sequence")
def update_sequence(body: SequenceUpdate):
    """Called every time the user re-orders or edits a card."""
    state.sequence = [item.model_dump() for item in body.items]
    return {"ok": True, "count": len(state.sequence)}


@app.post("/api/carousel/start")
def start_carousel(req: StartRequest):
    if state.running:
        return {"ok": False, "reason": "already running"}
    state._stop_event.clear()
    state.app_hwnd = req.app_hwnd
    state.running = True
    state.current_index = 0
    state._thread = threading.Thread(target=carousel_loop, daemon=True)
    state._thread.start()
    broadcast_sync(
        {
            "type": "status",
            "running": True,
            "paused": state.paused_by_app,
            "index": state.current_index,
            "active_hwnd": None,
        }
    )
    return {"ok": True}


@app.post("/api/carousel/stop")
def stop_carousel():
    state._stop_event.set()
    state.running = False
    state.paused_by_app = False
    state.app_hwnd = None
    if state._thread and state._thread.is_alive():
        state._thread.join(timeout=0.5)
    state._thread = None
    broadcast_sync(
        {
            "type": "status",
            "running": False,
            "paused": False,
            "index": 0,
            "active_hwnd": None,
        }
    )
    return {"ok": True}


@app.get("/api/status")
def get_status():
    return {
        "running": state.running,
        "paused": state.paused_by_app,
        "index": state.current_index,
        "sequence_length": len(state.sequence),
        "app_hwnd": state.app_hwnd,
    }


# ── HWND discovery for the management window itself ──────────
@app.get("/api/self-hwnd")
def find_self_hwnd():
    """
    Returns candidate HWNDs whose window title contains known browser/app strings.
    The frontend picks the right one (or the user can confirm).
    """
    candidates = []

    def _cb(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if any(
            kw in title for kw in ["FlexiOrder", "localhost:5173", "localhost:8000"]
        ):
            candidates.append({"hwnd": hwnd, "title": title})

    win32gui.EnumWindows(_cb, None)
    return {"candidates": candidates}


# ──────────────────────────────────────────────────────────────
# WebSocket
# ──────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    # Send current state immediately on connect
    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "running": state.running,
                "paused": state.paused_by_app,
                "index": state.current_index,
            }
        )
    )
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


# ──────────────────────────────────────────────────────────────
# Serve React build (production)
# ──────────────────────────────────────────────────────────────
try:
    app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="static")
except Exception:
    pass  # Dev mode: Vite serves on its own port


# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
