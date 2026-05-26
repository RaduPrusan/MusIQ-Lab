@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo No .venv found. Run: uv venv .venv ^&^& uv pip install -r requirements.txt
    pause
    exit /b 1
)
start "" http://localhost:8765/
.venv\Scripts\python.exe -m webui
