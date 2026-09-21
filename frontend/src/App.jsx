import { useState, useEffect, useRef, useCallback, useMemo } from "react";
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

// Same origin in production (served by FastAPI); proxied by Vite in dev.
const API = import.meta.env.VITE_API_URL || "";
const WS_URL = API
  ? API.replace(/^http/, "ws") + "/ws"
  : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

// Unique marker in the page title → backend recognises this tab (Smart Pause).
const UI_TOKEN = Math.random().toString(36).slice(2, 10);
document.title = `FlexiOrder #${UI_TOKEN}`;

const MODES = [
  { value: "none", label: "Normale" },
  { value: "borderless", label: "Borderless" },
  { value: "f11", label: "F11" },
];

const STATUS = {
  stopped: { label: "● Inattivo", cls: "idle" },
  running: { label: "▶ Attivo", cls: "running" },
  paused: { label: "⏸ In pausa", cls: "paused" },
  paused_ui: { label: "⏸ Pausa (FlexiOrder in primo piano)", cls: "paused" },
  desktop_hidden: { label: "◌ In attesa (desktop non visibile)", cls: "waiting" },
  empty: { label: "⚠ Nessuna finestra disponibile", cls: "paused" },
};

const keyOf = (desktop, monitor) => `${desktop}|${monitor}`;

async function api(path, method = "GET", body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `HTTP ${res.status}`);
  }
  return res.json();
}

// ──────────────────────────────────────────────────────────────
// Sortable card
// ──────────────────────────────────────────────────────────────
function WindowCard({ item, index, isActive, onChange, onRemove }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id });
  const [timer, setTimer] = useState(String(item.timer));
  useEffect(() => setTimer(String(item.timer)), [item.timer]);

  const commitTimer = () => {
    const n = Math.round(Number(timer));
    const valid = Number.isFinite(n) ? Math.min(3600, Math.max(1, n)) : item.timer;
    setTimer(String(valid));
    if (valid !== item.timer) onChange(item.id, "timer", valid);
  };

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, zIndex: isDragging ? 999 : "auto" }}
      className={`card ${isActive ? "card--active" : ""} ${isDragging ? "card--dragging" : ""} ${item.missing ? "card--missing" : ""}`}
    >
      <div className="card-row">
        <span className="drag-handle" {...attributes} {...listeners}>⠿</span>
        <span className="index-badge">{index + 1}</span>
        <span className="win-title" title={`${item.title}${item.exe ? ` (${item.exe})` : ""}`}>
          {item.title}
        </span>
        {item.missing && <span className="badge badge--warn" title="Finestra chiusa o non trovata: verrà ricollegata quando riappare">mancante</span>}
        <button className="remove-btn" onClick={() => onRemove(item.id)} title="Rimuovi">✕</button>
      </div>
      <div className="card-row card-row--controls">
        <label className="field-inline">
          <span>Timer</span>
          <input
            type="number"
            min={1}
            max={3600}
            value={timer}
            onChange={(e) => setTimer(e.target.value)}
            onBlur={commitTimer}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            className="timer-input"
          />
          <span className="unit">s</span>
        </label>
        <label className="field-inline">
          <span>Schermo</span>
          <select
            className="mode-select"
            value={item.mode}
            onChange={(e) => onChange(item.id, "mode", e.target.value)}
            title="Borderless: riempie il monitor senza bordi (non ruba il focus). F11: fullscreen del programma (richiede il focus)."
          >
            {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Window picker
// ──────────────────────────────────────────────────────────────
function PickerModal({ desktop, monitor, desktops, monitors, usedBy, exclude, onAdd, onClose }) {
  const [windows, setWindows] = useState(null);
  const [filter, setFilter] = useState("");
  const [onlyHere, setOnlyHere] = useState(true);

  useEffect(() => {
    api("/api/windows").then((d) => setWindows(d.windows)).catch(() => setWindows([]));
  }, []);

  const deskName = (id) => desktops.find((d) => d.id === id)?.name ?? "—";
  const monName = (id) => monitors.find((m) => m.id === id)?.name ?? "—";
  const multiDesk = desktops.length > 1;

  const list = (windows ?? []).filter(
    (w) =>
      !exclude.has(w.hwnd) &&
      (!onlyHere || !multiDesk || w.desktop === desktop.id || !w.desktop) &&
      `${w.title} ${w.exe}`.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2 className="modal-title">
          Aggiungi a {monitor.name} · {desktop.name}
        </h2>
        <input className="modal-search" placeholder="Filtra…" value={filter}
          onChange={(e) => setFilter(e.target.value)} autoFocus />
        {multiDesk && (
          <label className="check">
            <input type="checkbox" checked={onlyHere} onChange={(e) => setOnlyHere(e.target.checked)} />
            Solo finestre su {desktop.name}
          </label>
        )}
        <ul className="picker-list">
          {windows === null && <li className="picker-empty">Caricamento…</li>}
          {list.map((w) => (
            <li key={w.hwnd} className="picker-item" onClick={() => onAdd(w)}>
              <div className="picker-main">
                <span className="picker-title">{w.title}</span>
                <span className="picker-meta">
                  {w.exe || "?"} · {monName(w.monitor)}
                  {multiDesk && ` · ${deskName(w.desktop)}`}
                  {w.minimized && " · ridotta a icona"}
                  {usedBy.get(w.hwnd) && <span className="badge">in uso: {usedBy.get(w.hwnd)}</span>}
                </span>
              </div>
              <span className="picker-add">+</span>
            </li>
          ))}
          {windows !== null && list.length === 0 && <li className="picker-empty">Nessuna finestra trovata</li>}
        </ul>
        {multiDesk && (
          <p className="hint">
            Windows non permette di spostare finestre di altri programmi tra desktop virtuali:
            aggiungi finestre che si trovano già su {desktop.name}.
          </p>
        )}
        <button className="modal-close" onClick={onClose}>Chiudi</button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// One monitor = one independent carousel
// ──────────────────────────────────────────────────────────────
function MonitorColumn({ desktop, monitor, carousel, onItems, onAction, onPick, disconnected }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const items = carousel?.items ?? [];
  const status = carousel?.running ? carousel.status : "stopped";
  const st = STATUS[status] ?? STATUS.stopped;
  const activeIdx = items.findIndex((i) => i.id === carousel?.active_id);

  const handleDragEnd = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const from = items.findIndex((s) => s.id === active.id);
    const to = items.findIndex((s) => s.id === over.id);
    onItems(arrayMove(items, from, to));
  };
  const change = (id, field, value) => onItems(items.map((s) => (s.id === id ? { ...s, [field]: value } : s)));
  const remove = (id) => onItems(items.filter((s) => s.id !== id));
  const hasF11 = items.some((i) => i.mode === "f11");

  return (
    <section className={`column ${disconnected ? "column--off" : ""}`}>
      <header className="column-header">
        <div>
          <h2>{monitor.name}</h2>
          <span className="column-sub">{disconnected ? "non collegato" : `${monitor.size} · ${monitor.id}`}</span>
        </div>
        <span className="seq-count">{items.length} finestre</span>
      </header>

      <div className={`status status--${st.cls}`}>
        {st.label}
        {status === "running" && activeIdx >= 0 && ` — ${activeIdx + 1} / ${items.length}`}
      </div>

      <div className="column-actions">
        {!carousel?.running ? (
          <button className="btn btn--start" disabled={!items.length || disconnected}
            onClick={() => onAction("start")}>▶ Avvia</button>
        ) : (
          <>
            <button className="btn btn--stop" onClick={() => onAction("stop")}>■ Ferma</button>
            {status === "paused" ? (
              <button className="btn btn--ghost" onClick={() => onAction("resume")}>▶ Riprendi</button>
            ) : (
              <button className="btn btn--ghost" onClick={() => onAction("pause")}>⏸ Pausa</button>
            )}
          </>
        )}
        <button className="btn btn--ghost" disabled={disconnected} onClick={onPick}>+ Aggiungi</button>
      </div>

      {hasF11 && (
        <p className="hint hint--warn">F11 richiede il focus: quando mostra quella finestra, questo monitor prende la tastiera.</p>
      )}

      {items.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">⊡</span>
          <p>Nessuna finestra per {monitor.name} su {desktop.name}.</p>
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={items.map((s) => s.id)} strategy={verticalListSortingStrategy}>
            <div className="card-list">
              {items.map((item, idx) => (
                <WindowCard key={item.id} item={item} index={idx}
                  isActive={status === "running" && carousel?.active_id === item.id}
                  onChange={change} onRemove={remove} />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      )}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────
// Main App
// ──────────────────────────────────────────────────────────────
export default function App() {
  const [state, setState] = useState(null);
  const [connected, setConnected] = useState(false);
  const [selectedDesktop, setSelectedDesktop] = useState(null);
  const [picker, setPicker] = useState(null); // monitor object
  const [error, setError] = useState("");
  const [theme, setTheme] = useState(() => {
    try {
      const saved = window.localStorage.getItem("theme");
      return saved && themes[saved] ? saved : "dark";
    } catch {
      return "dark";
    }
  });
  const wsRef = useRef(null);

  useEffect(() => {
    Object.entries(themes[theme] ?? themes.dark).forEach(([k, v]) =>
      document.documentElement.style.setProperty(`--${k}`, v));
    try { window.localStorage.setItem("theme", theme); } catch { /* private mode */ }
  }, [theme]);

  // ── WebSocket: the backend pushes the full state on every change ──
  useEffect(() => {
    let closed = false;
    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        api("/api/self", "POST", { token: UI_TOKEN }).catch(() => {});
      };
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "state") setState(msg);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) setTimeout(connect, 1500);
      };
    }
    connect();
    return () => { closed = true; wsRef.current?.close(); };
  }, []);

  const desktops = state?.desktops ?? [];
  const desktopId = selectedDesktop ?? state?.current_desktop ?? desktops[0]?.id;
  const desktop = desktops.find((d) => d.id === desktopId) ?? desktops[0];

  const carousels = useMemo(() => {
    const m = new Map();
    (state?.carousels ?? []).forEach((c) => m.set(c.key, c));
    return m;
  }, [state]);

  // Monitors to show: connected ones + disconnected ones that still hold a sequence.
  const columns = useMemo(() => {
    if (!state || !desktop) return [];
    const cols = state.monitors.map((m) => ({ monitor: m, disconnected: false }));
    state.carousels
      .filter((c) => c.desktop === desktop.id && c.items.length && !state.monitors.some((m) => m.id === c.monitor))
      .forEach((c) => cols.push({ monitor: { id: c.monitor, name: c.monitor, size: "" }, disconnected: true }));
    return cols;
  }, [state, desktop]);

  const usedBy = useMemo(() => {
    const m = new Map();
    (state?.carousels ?? []).forEach((c) => {
      const mon = state.monitors.find((x) => x.id === c.monitor)?.name ?? c.monitor;
      const desk = state.desktops.find((x) => x.id === c.desktop)?.name ?? "";
      c.items.forEach((i) => m.set(i.hwnd, state.desktops.length > 1 ? `${mon} · ${desk}` : mon));
    });
    return m;
  }, [state]);

  const run = useCallback(async (fn) => {
    try { setError(""); await fn(); } catch (e) { setError(e.message); }
  }, []);

  // Optimistic local update, then persist; the WS echo confirms.
  const setItems = (monitorId, items) => {
    const key = keyOf(desktop.id, monitorId);
    setState((s) => {
      const exists = s.carousels.some((c) => c.key === key);
      const carousels = exists
        ? s.carousels.map((c) => (c.key === key ? { ...c, items } : c))
        : [...s.carousels, { key, desktop: desktop.id, monitor: monitorId, items, running: false, status: "stopped" }];
      return { ...s, carousels };
    });
    run(() => api("/api/carousel/sequence", "PUT", { desktop: desktop.id, monitor: monitorId, items }));
  };

  const action = (monitorId, name) =>
    run(() => api(`/api/carousel/${name}`, "POST", { desktop: desktop.id, monitor: monitorId }));

  const addWindow = (monitorId, w) => {
    const cur = carousels.get(keyOf(desktop.id, monitorId))?.items ?? [];
    if (cur.some((i) => i.hwnd === w.hwnd)) return;
    setItems(monitorId, [...cur, { id: Math.random().toString(36).slice(2, 14), hwnd: w.hwnd, title: w.title, exe: w.exe, timer: 5, mode: "none" }]);
  };

  const runningCount = (state?.carousels ?? []).filter((c) => c.running).length;

  // ──────────────────────────────────────────────────────────
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-icon">⧉</span>
          <span className="logo-text">FlexiOrder</span>
        </div>

        <div className={`conn ${connected ? "conn--ok" : ""}`}>
          {connected ? "● Backend connesso" : "○ Backend non raggiungibile…"}
        </div>

        <nav className="desk-list">
          <span className="section-label">Desktop virtuali</span>
          {desktops.map((d) => {
            const active = (state?.carousels ?? []).filter((c) => c.desktop === d.id && c.running).length;
            return (
              <button key={d.id}
                className={`desk-btn ${d.id === desktop?.id ? "desk-btn--sel" : ""}`}
                onClick={() => setSelectedDesktop(d.id)}>
                <span>{d.name}</span>
                <span className="desk-tags">
                  {d.id === state?.current_desktop && <span className="badge badge--accent">attuale</span>}
                  {active > 0 && <span className="badge">{active} ▶</span>}
                </span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-actions">
          <button className="btn btn--stop" disabled={!runningCount}
            onClick={() => run(() => api("/api/stop-all", "POST"))}>■ Ferma tutto ({runningCount})</button>
          <button className="btn btn--ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "Tema chiaro" : "Tema scuro"}
          </button>
        </div>

        <div className="sidebar-info">
          <p><strong>Ogni monitor</strong> ha il suo carosello, con finestre e tempi indipendenti.</p>
          <p><strong>Ogni desktop virtuale</strong> ha i suoi caroselli: ruotano solo quando quel desktop è visibile (Win+Ctrl+←/→).</p>
          <p><strong>Smart Pause:</strong> il monitor dove si trova questa pagina si ferma mentre la usi.</p>
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          <h1>{desktop?.name ?? "…"}</h1>
          {desktop && desktop.id !== state?.current_desktop && state?.current_desktop && (
            <span className="hint">Non è il desktop attuale: questi caroselli ripartono quando ci passi.</span>
          )}
        </header>

        {error && <div className="error" onClick={() => setError("")}>{error} ✕</div>}

        {!state ? (
          <div className="empty-state"><p>Connessione al backend…</p></div>
        ) : (
          <div className="columns">
            {columns.map(({ monitor, disconnected }) => (
              <MonitorColumn key={monitor.id}
                desktop={desktop} monitor={monitor} disconnected={disconnected}
                carousel={carousels.get(keyOf(desktop.id, monitor.id))}
                onItems={(items) => setItems(monitor.id, items)}
                onAction={(name) => action(monitor.id, name)}
                onPick={() => setPicker(monitor)} />
            ))}
          </div>
        )}
      </main>

      {picker && desktop && (
        <PickerModal
          desktop={desktop} monitor={picker} desktops={desktops} monitors={state.monitors}
          usedBy={usedBy}
          exclude={new Set((carousels.get(keyOf(desktop.id, picker.id))?.items ?? []).map((i) => i.hwnd))}
          onAdd={(w) => { addWindow(picker.id, w); setPicker(null); }}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}
