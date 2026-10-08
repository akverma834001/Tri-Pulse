"""Vercel Serverless Function entry point for Project Pulse."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.main import app

# Vercel looks for the ASGI 'app' object in api/index.py
