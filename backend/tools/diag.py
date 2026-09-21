"""
FlexiOrder diagnostics – what the backend sees on this machine.

    python backend/tools/diag.py            # monitors, desktops, windows
    python backend/tools/diag.py --focus    # also try raising/focusing a window
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from flexiorder.winapi import Win32Backend  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", action="store_true", help="raise the first listed window, then focus it")
    args = ap.parse_args()

    be = Win32Backend()
    print("== Monitors ==")
    for m in be.list_monitors():
        print(f"  {m['name']:<26} {m['id']:<16} {m['size']:<11} rect={m['rect']} work={m['work']}")

    desktops = be.list_desktops()
    cur = be.current_desktop()
    names = {d["id"]: d["name"] for d in desktops}
    print("\n== Virtual desktops ==")
    for d in desktops:
        print(f"  {'*' if d['id'] == cur else ' '} {d['name']:<14} {d['id']}")
    if cur is None:
        print("  (current desktop could not be determined)")

    wins = be.list_windows()
    print(f"\n== Windows ({len(wins)}) ==")
    for w in wins:
        print(f"  {w['hwnd']:>9}  {names.get(w['desktop'], w['desktop'] or '?'):<11} {w['monitor'] or '?':<14}"
              f" {'min ' if w['minimized'] else '    '}{w['exe']:<22} {w['title'][:60]}")

    if args.focus and wins:
        target = next((w for w in wins if w["desktop"] in (cur, None)), wins[0])
        print(f"\nRaising without focus: {target['title'][:60]}")
        time.sleep(1)
        be.show(target["hwnd"], target["monitor"], "none", focus=False)
        print(f"  foreground is target? {be.foreground() == target['hwnd']} (expected False)")
        time.sleep(1)
        be.show(target["hwnd"], target["monitor"], "none", focus=True)
        time.sleep(0.3)
        print(f"  after focus: foreground is target? {be.foreground() == target['hwnd']} (expected True)")


if __name__ == "__main__":
    main()
