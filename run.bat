@echo off
echo ========================================================
echo   PROJECT PULSE: SILENT CO-PILOT (v2, hardened)
echo ========================================================

IF NOT EXIST .env (
    echo [.env not found - creating from .env.example]
    copy .env.example .env > nul
)

IF NOT EXIST data (
    mkdir data
)

IF NOT EXIST data\logs (
    mkdir data\logs
)

echo Starting Project Pulse server on http://127.0.0.1:8000 ...
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
