# Changelog

## 2.1.0 — 2026-10-02

### Added
- **Portable single-file exe** (`FlexiOrder-<version>-win64.exe`) that needs no installation and no Python. It's built with PyInstaller via `packaging/build.py`, and a GitHub Actions release workflow builds it on every `v*` tag.
- System-tray mode (`run.py --tray`, always on in the exe): Apri FlexiOrder / Esci, no console window.
- The portable exe keeps `config.json` and `flexiorder.log` next to itself, falling back to `%APPDATA%\FlexiOrder` when that folder isn't writable.

## 2.0.0 — 2026-09-21

### Added
- **Independent carousels per monitor and per virtual desktop.** Each (desktop, monitor) pair has its own sequence, timers, thread and start/stop/pause.
- Raising windows without stealing focus, so several monitors can rotate at once. A window is moved to its carousel's monitor.
- Virtual desktop support through the public `IVirtualDesktopManager` plus read-only registry keys. Carousels on hidden desktops wait, and a window from another desktop is never shown.
- Per-window fullscreen mode: `none`, `borderless` (frameless, fills the monitor, restored on stop/remove) or `f11`.
- Per-monitor Smart Pause, based on a unique token in the UI page title.
- Persistence in `%APPDATA%\FlexiOrder\config.json`, with windows re-linked by exe + title after a restart. Closed windows are flagged "mancante" and re-link automatically.
- `run.py` one-command launcher: localhost only, automatic free-port fallback, single-instance detection, opens the browser.
- Test suite: fake-backend logic tests, API tests, opt-in live Win32 tests. `backend/tools/diag.py` diagnostics.

### Fixed
- Dependencies failed to install on Python 3.13/3.14 (hard pins).
- The built UI was never served (wrong static path).
- F11 was pressed every cycle, toggling fullscreen off again.
- Every activation un-maximized maximized windows (`SW_RESTORE`).
- Stop → start could leave two carousel loops running.
- `IndexError` when the sequence shrank while the carousel was running.
- Self-window detection broke with multiple browser windows.
- The sequence was lost on UI reload. The WebSocket URL bypassed the dev proxy.
- Minimized windows were hidden from the picker. Tool, owned and cloaked windows were listed.
- Crash when printing to a cp1252 console.

### Changed
- Default port 8000 → 8765 (8000 is often inside Windows-reserved port ranges).
- Backend split into the `backend/flexiorder/` package. `backend/main.py` is kept as a shim.
- Server binds `127.0.0.1` and CORS/WebSocket accept only localhost origins.

### Removed
- Docker setup and the Win32 host agent: containers can't manipulate Windows windows, and the bridge's endpoints were broken.
- Committed `frontend/node_modules`.
