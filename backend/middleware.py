"""Middleware for structured request logging, error handling, security headers, and CSRF protection."""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import time
import uuid
from pathlib import Path
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from backend.config import LOG_LEVEL

logger = logging.getLogger("pulse")
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
logger.handlers.clear()

# Console handler (standard for Vercel and local terminal output)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Rotating file handler (optional file persistence, safe on serverless)
try:
    log_dir = Path("/tmp/logs" if os.getenv("VERCEL") else "data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pulse.log"
    file_handler = RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_formatter = logging.Formatter(
        '{"time":"%(asctime)s","level":"%(levelname)s","message":%(message)s}'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
except Exception:
    pass


class PulseSecurityAndLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start_time = time.time()

        # CSRF check: state-changing API endpoints must include X-Pulse-Client: 1
        path = request.url.path
        method = request.method.upper()
        if path.startswith("/api/") and method in ("POST", "PUT", "PATCH", "DELETE"):
            # Exclude login/register if needed, but spec says:
            # "State-changing endpoints accept only application/json and require a custom header X-Pulse-Client: 1"
            client_header = request.headers.get("X-Pulse-Client")
            if client_header != "1":
                # Check if it's an API request missing header
                error_body = {
                    "error": {
                        "code": "missing_csrf_header",
                        "message": "Missing required 'X-Pulse-Client: 1' security header",
                        "request_id": request_id,
                    }
                }
                return JSONResponse(status_code=403, content=error_body)

        response = await call_next(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        user_id = getattr(request.state, "user_id", None)
        error_code = getattr(request.state, "error_code", None)

        # Structured log entry (No passwords, tokens, query strings, health values or bodies!)
        log_payload = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "user_id": user_id,
            "error_code": error_code,
        }
        logger.info(json.dumps(log_payload))

        # Security Headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(self)"
        response.headers["X-Request-ID"] = request_id
        
        # CSP: safe policy allowing local inline styles for dynamic UI components
        csp = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "media-src 'self' blob:; "
            "connect-src 'self'"
        )
        response.headers["Content-Security-Policy"] = csp

        return response
