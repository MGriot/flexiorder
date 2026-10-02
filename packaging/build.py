"""
Build the portable, single-file FlexiOrder.exe (Windows only):

    pip install -r backend/requirements-build.txt
    python packaging/build.py [--ui]

--ui rebuilds the React UI first (needs Node.js); by default the committed
backend/static is bundled. Output: dist/FlexiOrder-<version>-win64.exe
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable FlexiOrder.exe")
    parser.add_argument("--ui", action="store_true", help="rebuild the UI with npm first")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("FlexiOrder only runs on Windows; build the exe on Windows.")
        return 1

    if args.ui:
        npm = "npm.cmd"
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    if not (BACKEND / "static" / "index.html").exists():
        print("backend/static is missing: run with --ui")
        return 1

    from flexiorder import __version__
    from flexiorder.tray import make_icon

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    ico = build / "flexiorder.ico"
    make_icon(256).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    import PyInstaller.__main__

    name = f"FlexiOrder-{__version__}-win64"
    PyInstaller.__main__.run([
        str(ROOT / "run.py"),
        "--onefile", "--noconsole", "--noconfirm", "--clean",
        "--name", name,
        "--icon", str(ico),
        "--paths", str(BACKEND),
        "--add-data", f"{BACKEND / 'static'}{os.pathsep}static",
        "--collect-submodules", "uvicorn",
        "--hidden-import", "flexiorder.app",
        "--hidden-import", "flexiorder.tray",
        "--hidden-import", "comtypes",
        "--hidden-import", "pystray._win32",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(build / "pyinstaller"),
        "--specpath", str(build),
    ])
    print(f"\nBuilt {ROOT / 'dist' / (name + '.exe')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
