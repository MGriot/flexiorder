# ⧉ FlexiOrder — Window Carousel for Windows

FlexiOrder rotates windows automatically: each window stays in front for its own timer, then the next one takes over. It runs **one independent carousel per monitor, per virtual desktop**. Every screen on every desktop has its own windows, order, timers, and start/stop/pause.

It's a local Python app: a FastAPI backend drives the Win32 API, and a React UI is served from the same process.

## ✨ Features

- **Multi-monitor**: each monitor rotates on its own schedule. Windows are raised *without stealing focus*, so the screen you're working on keeps the keyboard. A window added to "Monitor 2" is moved onto Monitor 2.
- **Virtual desktops** (Win+Ctrl+D): each desktop keeps its own set of carousels. Only the desktop you're looking at rotates. The others wait and resume when you switch back.
- **Fullscreen per window**:
  - *Borderless*: removes the frame and fills the monitor. Works on any monitor, doesn't need focus. Restored when you stop or remove the window.
  - *F11*: the app's own fullscreen (browsers). Pressed only if the window isn't already fullscreen, and only when it really has focus.
- **Smart Pause**: the monitor showing the FlexiOrder page pauses while you use it. Other monitors keep going.
- **Persistent**: sequences are saved to `%APPDATA%\FlexiOrder\config.json`. After a restart, windows are re-linked by program + title. Closed windows show as "mancante" and re-link automatically when they reappear.
- **Zero-latency switching**: DWM transitions are disabled during each switch.

---

## 🚀 Getting started

Prerequisites: Windows 10/11, Python 3.11+ (tested on 3.14). Node.js 18+ is only needed to rebuild the UI.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
python run.py
```

This starts the server on <http://127.0.0.1:8765> and opens the browser. Options:

| Flag | Meaning |
|---|---|
| `--port N` | preferred port (falls back to the next free one if taken or reserved) |
| `--no-browser` | don't open the UI |

Running `python run.py` again while it's already running just opens the UI; it won't start a second backend.

The server listens on **127.0.0.1 only**, because this API can move every window on the machine.

### Rebuilding the UI (after editing `frontend/`)

```bash
cd frontend
npm install
npm run build
```

The build lands in `backend/static/`. For live-reload development, run `npm run dev` (http://localhost:5173) while `python run.py` is running. Vite proxies `/api` and `/ws` to port 8765 (override with `FLEXIORDER_PORT`).

---

## 🛠️ Using it

1. Pick a **virtual desktop** in the sidebar ("attuale" marks the one you're on).
2. Each **monitor** is a column. Click **+ Aggiungi** to add windows. By default the picker lists windows on the selected desktop and shows each window's current monitor.
3. Drag cards to reorder. Set the **Timer** (seconds) and the **Schermo** mode (Normale / Borderless / F11).
4. Press **▶ Avvia** on each monitor you want rotating. Use **⏸ Pausa** / **■ Ferma** per monitor, or **Ferma tutto**.

### Limitations (by design of Windows)

- **Switching desktops is up to you.** Windows' only public API for moving windows between virtual desktops works on the caller's own windows. So add windows that already live on that desktop. FlexiOrder never shows a window from another desktop, because activating it would make Windows jump desktops.
- **F11 needs keyboard focus.** A monitor showing an F11 window takes the keyboard at that moment. Use *Borderless* if several monitors rotate at once.
- Elevated (admin) windows can't be controlled from a non-elevated FlexiOrder.

---

## 🧪 Testing

```bash
pip install -r backend/requirements-dev.txt
cd backend
python -m pytest tests            # fast, OS-independent logic tests
python tools/diag.py              # what FlexiOrder sees: monitors, desktops, windows
```

Live Win32 tests briefly open small test windows. Enable them with an environment variable (cmd: `set FLEXIORDER_LIVE=1`, PowerShell: `$env:FLEXIORDER_LIVE="1"`), then run `python -m pytest tests` again. The multi-monitor live test runs automatically when 2+ monitors are connected.

---

## 🩺 Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Port 8765 is unavailable, using …` | Normal: the port is taken or reserved by Windows (Hyper-V/WSL reserve ranges; see `netsh interface ipv4 show excludedportrange protocol=tcp`). The UI opens on the port printed. |
| A monitor shows "Nessuna finestra disponibile" | Every window in that sequence is closed, minimized to another desktop, or on a different virtual desktop. Closed windows re-link automatically when reopened with the same program and title. |
| Smart Pause doesn't trigger | Keep the FlexiOrder tab active in its browser window: the backend recognizes it by the `FlexiOrder #…` page title. |
| A window ignores the carousel | It's probably running as administrator. Run FlexiOrder elevated too, or leave that window out. |
| Picker doesn't list a window from another desktop | Untick "Solo finestre su …", but remember that window can only rotate on its own desktop. |

---

## 📖 Architecture

```text
flexiorder/
├── run.py                     # one-command launcher
├── backend/
│   ├── main.py                # legacy entry point (python main.py)
│   ├── flexiorder/
│   │   ├── app.py             # FastAPI routes, WebSocket state push, watcher, persistence glue
│   │   ├── carousel.py        # Carousel (one thread per desktop×monitor) + CarouselManager
│   │   ├── winapi.py          # Win32Backend: enumerate, raise/focus, borderless, F11, monitors
│   │   ├── vdesktop.py        # virtual desktops (IVirtualDesktopManager + registry, read-only)
│   │   └── config.py          # %APPDATA% config + window re-matching
│   ├── static/                # built UI
│   ├── tests/                 # pytest (fake backend + opt-in live tests)
│   └── tools/diag.py
└── frontend/src/App.jsx       # React UI (one column per monitor, dnd-kit)
```

The carousel logic talks to the OS only through the small `WindowBackend` protocol in `carousel.py`. The tests swap in a fake, so scheduling, pausing and desktop gating are tested without real windows.

### API

| Method | Path | Body | Description |
|---|---|---|---|
| `GET` | `/api/state` | | desktops, current desktop, monitors, all carousels |
| `GET` | `/api/windows` | | windows with exe, monitor, desktop, minimized |
| `PUT` | `/api/carousel/sequence` | `{desktop, monitor, items[]}` | set one carousel's sequence |
| `POST` | `/api/carousel/{start\|stop\|pause\|resume}` | `{desktop, monitor}` | control one carousel |
| `POST` | `/api/stop-all` | | stop every carousel |
| `POST` | `/api/self` | `{token}` | register the UI tab (its title contains `FlexiOrder #token`) |
| `WS` | `/ws` | | full state pushed on every change |

`items[]`: `{id?, hwnd, title, exe, timer (1–3600 s), mode: "none"|"borderless"|"f11"}`.

### How switching works

- **Without focus** (default when you're working on another monitor): `SetWindowPos(HWND_TOPMOST)` then `HWND_NOTOPMOST` with `SWP_NOACTIVATE`. The window comes to the top of the z-order and nobody's keyboard focus changes.
- **With focus** (the foreground window is already on that monitor, or F11 is needed): `AttachThreadInput` to the foreground thread, then `SetForegroundWindow`. If Windows' anti-focus-stealing rule blocks it, a synthetic ALT double-tap counts as user input and the call is retried.
- **Current virtual desktop**: read from the registry when Windows writes it. Otherwise it's inferred from which desktop the windows reported by `IsWindowOnCurrentVirtualDesktop` belong to.
- The process is per-monitor DPI aware, so coordinates are correct on scaled monitors.
