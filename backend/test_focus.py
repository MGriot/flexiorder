import time
import win32gui
import win32con
import win32api
import win32process
import ctypes

def bring_to_front(hwnd):
    print(f"Attempting to bring HWND {hwnd} to front...")
    try:
        # ALT-key hack: simulate user input to bypass Windows anti-focus-stealing protection
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0) # Press ALT
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0) # Release ALT

        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        
        current_hwnd = win32gui.GetForegroundWindow()
        if current_hwnd != hwnd:
            current_thread = win32api.GetCurrentThreadId()
            foreground_thread = win32process.GetWindowThreadProcessId(current_hwnd)[0] if current_hwnd else current_thread
            
            # Attach threads to share input state
            if current_thread != foreground_thread:
                ctypes.windll.user32.AttachThreadInput(current_thread, foreground_thread, True)
            
            # Finally, attempt to steal focus
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            
            # Detach threads
            if current_thread != foreground_thread:
                ctypes.windll.user32.AttachThreadInput(current_thread, foreground_thread, False)
                
        # Check if it worked
        time.sleep(0.5)
        new_fg = win32gui.GetForegroundWindow()
        print(f"Target HWND: {hwnd}, Current FG HWND: {new_fg}")
        return new_fg == hwnd
    except Exception as e:
        print(f"Exception: {e}")
        return False

windows = []
def _cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
        windows.append((hwnd, win32gui.GetWindowText(hwnd)))
win32gui.EnumWindows(_cb, None)

print(f"Found {len(windows)} visible windows.")
target_hwnd = None
for hwnd, title in windows:
    if "PowerShell" in title or "Code" in title or "Firefox" in title:
        target_hwnd = hwnd
        safe_title = title.encode('ascii', 'ignore').decode('ascii')
        print(f"Selected target: {safe_title} ({hwnd})")
        break

if target_hwnd:
    # Wait 2 seconds so the user/script is "idle"
    print("Waiting 2 seconds...")
    time.sleep(2)
    success = bring_to_front(target_hwnd)
    print(f"Success? {success}")
else:
    print("Could not find a suitable target window.")
