#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  PROJECT PULSE: SILENT CO-PILOT (v2, hardened)"
echo "========================================================"

if [ ! -f .env ]; then
    echo "[.env not found - creating from .env.example]"
    cp .env.example .env
fi

mkdir -p data data/logs

echo "Starting Project Pulse server on http://127.0.0.1:8000 ..."
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
