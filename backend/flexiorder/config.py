"""
Persist sequences to %APPDATA%\\FlexiOrder\\config.json, or next to the exe in
the portable build (when that folder is writable).

Window handles do not survive an app/PC restart, so each item also stores the
process exe and title. On load an item is matched by hwnd first (still valid
and same exe), then by exe + exact title, then by exe + title prefix.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .carousel import normalize_item


def _writable(folder: Path) -> bool:
    try:
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def default_path() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if _writable(exe_dir):
            return exe_dir / "config.json"
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "FlexiOrder" / "config.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, carousels: list[dict]) -> None:
    data = {
        "version": 2,
        "carousels": [
            {"desktop": c["desktop"], "monitor": c["monitor"],
             "items": [{k: i[k] for k in ("id", "hwnd", "title", "exe", "timer", "mode")} for i in c["items"]]}
            for c in carousels if c["items"]
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def rematch(items: list[dict], windows: list[dict]) -> list[dict]:
    """Re-bind saved items to live windows. Unmatched items are flagged missing."""
    live = {w["hwnd"]: w for w in windows}
    out = [normalize_item(raw) for raw in items]

    def _same_app(it: dict, w: dict) -> bool:
        return not it["exe"] or not w["exe"] or w["exe"] == it["exe"]

    # Pass 1: handles that are still valid keep their window.
    taken: set[int] = set()
    pending = []
    for it in out:
        w = live.get(it["hwnd"])
        if w and w["hwnd"] not in taken and _same_app(it, w):
            taken.add(w["hwnd"])
            it.update(title=w["title"], exe=w["exe"] or it["exe"], missing=False)
        else:
            pending.append(it)

    # Pass 2: exact title, then a shared 20-char title prefix, same exe.
    for it in pending:
        pool = [w for w in windows if w["hwnd"] not in taken and _same_app(it, w)]
        p = it["title"][:20]
        match = (next((w for w in pool if w["title"] == it["title"]), None)
                 or next((w for w in pool if p and w["title"][:20] == p), None))
        if match:
            taken.add(match["hwnd"])
            it.update(hwnd=match["hwnd"], title=match["title"], exe=match["exe"] or it["exe"], missing=False)
        else:
            it["missing"] = True
    return out
