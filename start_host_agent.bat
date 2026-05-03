@echo off
echo Setting up FlexiOrder Host Agent...
cd /d "%~dp0"
if not exist .venv_host (
    python -m venv .venv_host
)
call .venv_host\Scripts\activate
pip install fastapi uvicorn pywin32 pydantic
echo.
echo Starting Host Agent on port 8001...
python host_agent.py
pause
