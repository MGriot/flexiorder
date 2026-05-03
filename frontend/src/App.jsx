import { useState, useEffect, useRef, useCallback } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import themes from "./theme.json";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_URL = API.replace("http", "ws") + "/ws";

// ──────────────────────────────────────────────────────────────
// Sortable card
// ──────────────────────────────────────────────────────────────
function WindowCard({ item, index, isActive, onChange, onRemove }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.hwnd });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 999 : "auto",
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`card ${isActive ? "card--active" : ""} ${isDragging ? "card--dragging" : ""}`}
    >
      {/* Drag handle */}
      <span className="drag-handle" {...attributes} {...listeners}>
        ⠿
      </span>

      {/* Index badge */}
      <span className="index-badge">{index + 1}</span>

      {/* Title */}
      <span className="win-title" title={item.title}>
        {item.title.length > 38 ? item.title.slice(0, 36) + "…" : item.title}
      </span>

      {/* Timer control */}
      <label className="field-label">
        <span>Timer</span>
        <div className="timer-input-wrap">
          <input
            type="number"
            min={1}
            max={999}
            value={item.timer}
            onChange={(e) => onChange(item.hwnd, "timer", Number(e.target.value))}
            className="timer-input"
          />
          <span className="unit">s</span>
        </div>
      </label>

      {/* Force F11 toggle */}
      <label className="toggle-wrap" title="Force fullscreen via F11">
        <span>F11</span>
        <input
          type="checkbox"
          checked={item.force_f11}
          onChange={(e) => onChange(item.hwnd, "force_f11", e.target.checked)}
          className="toggle"
        />
        <span className="toggle-slider" />
      </label>

      {/* Remove */}
      <button className="remove-btn" onClick={() => onRemove(item.hwnd)} title="Remove">
        ✕
      </button>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Window picker modal
// ──────────────────────────────────────────────────────────────
function PickerModal({ available, onAdd, onClose }) {
  const [filter, setFilter] = useState("");
  const filtered = available.filter((w) =>
    w.title.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">Add Windows</h2>
        <input
          className="modal-search"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          autoFocus
        />
        <ul className="picker-list">
          {filtered.map((w) => (
            <li key={w.hwnd} className="picker-item" onClick={() => onAdd(w)}>
              <span className="picker-title">{w.title}</span>
              <span className="picker-add">+</span>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="picker-empty">Nessuna finestra trovata</li>
          )}
        </ul>
        <button className="modal-close" onClick={onClose}>
          Chiudi
        </button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Status bar
// ──────────────────────────────────────────────────────────────
function StatusBar({ running, paused, index, seqLen }) {
  let label = "● Inattivo";
  let cls = "status status--idle";

  if (running && paused) {
    label = "⏸ Pausa (app in focus)";
    cls = "status status--paused";
  } else if (running) {
    label = `▶ Attivo — finestra ${index + 1} / ${seqLen}`;
    cls = "status status--running";
  }

  return <div className={cls}>{label}</div>;
}

// ──────────────────────────────────────────────────────────────
// Main App
// ──────────────────────────────────────────────────────────────
export default function App() {
  const [sequence, setSequence] = useState([]);
  const [available, setAvailable] = useState([]);
  const [showPicker, setShowPicker] = useState(false);
  const [theme, setTheme] = useState(() => {
    const saved = window.localStorage.getItem("theme");
    return saved && themes[saved] ? saved : "dark";
  });
  const [carouselStatus, setCarouselStatus] = useState({
    running: false,
    paused: false,
    index: 0,
    active_hwnd: null,
  });
  const wsRef = useRef(null);

  useEffect(() => {
    const selected = themes[theme] ?? themes.dark;
    Object.entries(selected).forEach(([key, value]) => {
      document.documentElement.style.setProperty(`--${key}`, value);
    });
    window.localStorage.setItem("theme", theme);
  }, [theme]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  // ── WebSocket ──────────────────────────────────────────────
  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "status") {
          setCarouselStatus((prev) => ({ ...prev, ...msg }));
        } else if (msg.type === "window_closed") {
          setSequence(msg.sequence);
        }
      };

      ws.onclose = () => setTimeout(connect, 2000);
    }
    connect();
    return () => wsRef.current?.close();
  }, []);

  // ── Sync sequence to backend whenever it changes ──────────
  const syncSequence = useCallback(async (seq) => {
    await fetch(`${API}/api/sequence`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: seq }),
    });
  }, []);

  const updateSequence = (newSeq) => {
    setSequence(newSeq);
    syncSequence(newSeq);
  };

  // ── Load available windows ─────────────────────────────────
  const refreshWindows = async () => {
    const res = await fetch(`${API}/api/windows`);
    const data = await res.json();
    setAvailable(data.windows);
  };

  // ── Drag & drop ────────────────────────────────────────────
  const handleDragEnd = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const oldIdx = sequence.findIndex((s) => s.hwnd === active.id);
    const newIdx = sequence.findIndex((s) => s.hwnd === over.id);
    const reordered = arrayMove(sequence, oldIdx, newIdx);
    updateSequence(reordered);
  };

  // ── Card mutations ─────────────────────────────────────────
  const handleChange = (hwnd, field, value) => {
    const updated = sequence.map((s) => (s.hwnd === hwnd ? { ...s, [field]: value } : s));
    updateSequence(updated);
  };

  const handleRemove = (hwnd) => {
    const updated = sequence.filter((s) => s.hwnd !== hwnd);
    updateSequence(updated);
  };

  const handleAdd = (win) => {
    if (sequence.find((s) => s.hwnd === win.hwnd)) return;
    const updated = [...sequence, { ...win, timer: 5, force_f11: false }];
    updateSequence(updated);
  };

  // ── Carousel controls ──────────────────────────────────────
  const startCarousel = async () => {
    const selfRes = await fetch(`${API}/api/self-hwnd`);
    const selfData = await selfRes.json();
    const appHwnd =
      selfData.candidates?.find((c) => c.title.includes("FlexiOrder"))?.hwnd ||
      selfData.candidates?.find((c) => c.title.includes("localhost"))?.hwnd ||
      selfData.candidates?.[0]?.hwnd ||
      0;

    if (!appHwnd) {
      alert("Non ho trovato la finestra di FlexiOrder. Ricarica la pagina e riprova.");
      return;
    }

    const res = await fetch(`${API}/api/carousel/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_hwnd: appHwnd }),
    });
    const data = await res.json();
    if (data.ok) {
      setCarouselStatus((prev) => ({
        ...prev,
        running: true,
        paused: false,
        index: 0,
        active_hwnd: null,
      }));
    }
  };

  const stopCarousel = async () => {
    const res = await fetch(`${API}/api/carousel/stop`, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      setCarouselStatus({
        running: false,
        paused: false,
        index: 0,
        active_hwnd: null,
      });
    }
  };

  // ──────────────────────────────────────────────────────────
  return (
    <div className="shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-icon">⧉</span>
          <span className="logo-text">FlexiOrder</span>
        </div>

        <StatusBar
          running={carouselStatus.running}
          paused={carouselStatus.paused}
          index={carouselStatus.index}
          seqLen={sequence.length}
        />

        <div className="sidebar-actions">
          {!carouselStatus.running ? (
            <button
              className="btn btn--start"
              onClick={startCarousel}
              disabled={sequence.length < 1}
            >
              ▶ Avvia Carosello
            </button>
          ) : (
            <button className="btn btn--stop" onClick={stopCarousel}>
              ■ Ferma
            </button>
          )}

          <button
            className="btn btn--theme"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? "Attiva tema chiaro" : "Attiva tema scuro"}
          </button>

          <button
            className="btn btn--add"
            onClick={() => {
              refreshWindows();
              setShowPicker(true);
            }}
          >
            + Aggiungi Finestra
          </button>
        </div>

        <div className="sidebar-info">
          <p>
            <strong>Smart Pause:</strong> il carosello si mette in pausa
            automaticamente quando questa finestra è in primo piano.
          </p>
          <p>
            <strong>Drag</strong> le card per cambiare l'ordine.
          </p>
        </div>
      </aside>

      {/* Main content */}
      <main className="main">
        <header className="main-header">
          <h1>Sequenza Attiva</h1>
          <span className="seq-count">{sequence.length} finestre</span>
        </header>

        {sequence.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">⊡</span>
            <p>Nessuna finestra in sequenza.</p>
            <p>Clicca <em>Aggiungi Finestra</em> per iniziare.</p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={sequence.map((s) => s.hwnd)}
              strategy={verticalListSortingStrategy}
            >
              <div className="card-list">
                {sequence.map((item, idx) => (
                  <WindowCard
                    key={item.hwnd}
                    item={item}
                    index={idx}
                    isActive={
                      carouselStatus.running &&
                      !carouselStatus.paused &&
                      carouselStatus.active_hwnd === item.hwnd
                    }
                    onChange={handleChange}
                    onRemove={handleRemove}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </main>

      {showPicker && (
        <PickerModal
          available={available.filter((w) => !sequence.find((s) => s.hwnd === w.hwnd))}
          onAdd={(w) => {
            handleAdd(w);
            setShowPicker(false);
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </div>
  );
}
