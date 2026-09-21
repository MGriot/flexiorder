"""
Backward-compatible entry point: `cd backend && python main.py`.
Prefer `python run.py` from the repository root.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flexiorder.app import app  # noqa: E402,F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
