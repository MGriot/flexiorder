# ⧉ FlexiOrder — Zero-Latency Window Carousel

FlexiOrder is a high-performance, lightweight Windows application designed to automate the cyclical rotation of active desktop windows. Built with a React frontend and a FastAPI backend, it interacts directly with the Windows Desktop Window Manager (DWM) to provide instantaneous, animation-free window switching.

## ✨ Key Features

- **Zero-Latency Switching**: Bypasses Windows OS animations (DWM transitions) for instantaneous "hard-cut" window swapping.
- **Adaptive Full-Screen**: Intelligently handles full-screen modes. Sends OS-level Maximize commands to native apps (like Docker, Word) and simulates `F11` keystrokes for browsers to achieve true full-screen.
- **Smart Pause**: Automatically pauses the carousel loop if the user interacts with the FlexiOrder UI, resuming seamlessly when the UI loses focus.
- **Docker Bridge Architecture**: Capable of running the backend within a Docker container while delegating native Windows API calls to a lightweight Host Agent via HTTP.
- **Real-Time UI Sync**: Utilizes WebSockets to keep the frontend completely synchronized with the background carousel sequence.

---

## 🚀 Getting Started (Tutorial)

### Prerequisites
- Windows 10/11 (Required for `pywin32` window manipulation)
- Python 3.11+
- Node.js 18+

### 1. Native Setup (Recommended)
Running natively provides the lowest latency and most stable access to the Windows API.

**Start the Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```
*The FastAPI server will start on `http://localhost:8000`.*

**Start the Frontend:**
```bash
cd frontend
npm install
npm run dev
```
*The Vite development server will start on `http://localhost:5174` (or 5173).*

### 2. Docker Setup (Host Agent Bridge)
If you prefer running the stack via Docker, you must run the Host Agent natively on your Windows machine to proxy the `win32` API calls.

1. Run `start_host_agent.bat` in the root directory (starts on port 8001).
2. Run `docker-compose up -d`.

---

## 🛠️ How-To Guide: Using the Carousel

1. **Select Windows**: Open `http://localhost:5174`. The app will query the OS and list all visible windows.
2. **Build Sequence**: Drag and drop windows into your desired rotation sequence.
3. **Configure Options**:
   - **Timer**: Set how long (in seconds) the window should remain in focus.
   - **F11 Toggle**: Check this to force the window to expand (adaptive maximize/full-screen).
4. **Start**: Click "Start Carousel". The app will instantly snap the first window to the front. To edit the sequence, simply bring the FlexiOrder browser window back into focus to trigger the Smart Pause.

---

## 📖 Reference: API & Architecture

### Architecture Map
```text
flexiorder/
├── backend/
│   ├── main.py            # FastAPI + pywin32 + WebSocket + DWM logic
│   ├── requirements.txt
│   └── test_focus.py      # Standalone focus-stealing debug script
├── frontend/
│   ├── src/
│   │   ├── App.jsx        # React UI + dnd-kit
│   │   └── index.css      # Dark-industrial UI tokens
├── docker-compose.yml     # Container orchestration
├── host_agent.py          # Native win32 proxy for Docker bridging
└── start_host_agent.bat
```

### REST API Endpoints
| Method | Path                   | Description                              |
|--------|------------------------|------------------------------------------|
| `GET`  | `/api/windows`         | Retrieve all visible system windows      |
| `PUT`  | `/api/sequence`        | Update rotation sequence and settings    |
| `GET`  | `/api/self-hwnd`       | Identify the browser's current HWND      |
| `POST` | `/api/carousel/start`  | Initiate the background loop             |
| `POST` | `/api/carousel/stop`   | Terminate the background loop            |

---

## 🧠 Explanation: Deep System Integrations

### Bypassing Windows Anti-Focus-Stealing
Windows actively prevents background applications from stealing focus to avoid interrupting the user. FlexiOrder bypasses this using the **ALT-Key Hack** and Thread Attachment:
1. Simulates an `ALT` key press/release (`VK_MENU`) to trick the OS into registering recent user input.
2. Temporarily attaches the backend's thread input queue to the current foreground window's thread (`AttachThreadInput`).
3. Executes `SetForegroundWindow()`.

### Zero-Latency DWM Manipulation
Standard OS window switching triggers a ~200ms fade/slide animation managed by the Desktop Window Manager (DWM). FlexiOrder uses `ctypes.windll.dwmapi.DwmSetWindowAttribute` to forcefully inject the `DWMWA_TRANSITIONS_FORCEDISABLE` (value `3`) flag into the target window immediately prior to sizing it. This results in an instantaneous, zero-latency camera-cut style switch, after which animations are seamlessly re-enabled.
