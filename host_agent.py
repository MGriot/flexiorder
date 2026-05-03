import uvicorn
from fastapi import FastAPI
import win32gui
import win32con
import win32api
import win32process
import ctypes
import time
from pydantic import BaseModel

app = FastAPI(title="FlexiOrder Host Agent")

class ActivateRequest(BaseModel):
    hwnd: int
    force_f11: bool = False

def _is_visible_app_window(hwnd: int) -> bool:
    if not win32gui.IsWindowVisible(hwnd): return False
    title = win32gui.GetWindowText(hwnd).strip()
    if not title or len(title) < 2: return False
    cls = win32gui.GetClassName(hwnd)
    if cls in ["Shell_TrayWnd", "Progman", "WorkerW"]: return False
    if "FlexiOrder" in title: return False
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] == win32con.SW_SHOWMINIMIZED: return False
    return True

@app.get("/windows")
def list_windows():
    windows = []
    def _cb(hwnd, _):
        if _is_visible_app_window(hwnd):
            windows.append({"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd)})
    win32gui.EnumWindows(_cb, None)
    return {"windows": windows}

@app.get("/foreground")
def get_foreground():
    return {"hwnd": win32gui.GetForegroundWindow()}

@app.post("/activate")
def activate_window(req: ActivateRequest):
    hwnd = req.hwnd
    try:
        if not win32gui.IsWindow(hwnd): return {"ok": False}
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        
        ctypes.windll.user32.AllowSetForegroundWindow(win32con.ASFW_ANY)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        
        if req.force_f11:
            win32api.keybd_event(win32con.VK_F11, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(win32con.VK_F11, 0, win32con.KEYEVENTF_KEYUP, 0)
        return {"ok": True}
    except:
        return {"ok": False}

if __name__ == "__main__":
    print("🚀 FlexiOrder Host Agent running on http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)
