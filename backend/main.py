"""Main FastAPI application factory for Project Pulse."""

import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.config import PULSE_ENV
from backend.database import Base, engine
import backend.models  # Register all models with Base.metadata
from backend.middleware import PulseSecurityAndLoggingMiddleware, logger
from backend.clock import get_clock

# Create DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Project Pulse: Silent Co-Pilot",
    description="Wellness and behavioral-pattern support tool for high-stress professionals.",
    version="2.0.0",
    docs_url="/docs" if PULSE_ENV == "development" else None,
    redoc_url=None,
)

# Add Middleware
app.add_middleware(PulseSecurityAndLoggingMiddleware)


# --- Standardized Error Handlers ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)
    request.state.error_code = str(exc.status_code)
    
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", f"http_{exc.status_code}")
        message = exc.detail.get("message", "An error occurred")
        consent = exc.detail.get("consent")
    else:
        code = f"http_{exc.status_code}"
        message = str(exc.detail)
        consent = None

    error_dict = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if consent:
        error_dict["consent"] = consent

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error_dict},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    request.state.error_code = "validation_error"
    
    # Generate user-friendly error message from pydantic errors
    errors = exc.errors()
    msg_parts = []
    for err in errors:
        loc = " -> ".join(str(l) for l in err.get("loc", []) if l != "body")
        msg = err.get("msg", "invalid")
        if loc:
            msg_parts.append(f"{loc}: {msg}")
        else:
            msg_parts.append(msg)
    
    human_msg = "; ".join(msg_parts) if msg_parts else "Invalid input data provided."
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": human_msg,
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    request_id = getattr(request.state, "request_id", None)
    request.state.error_code = "database_error"
    logger.error(f"Database error (request_id={request_id}): {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "database_error",
                "message": "A database error occurred. Please try again.",
                "request_id": request_id,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    request.state.error_code = "internal_server_error"
    logger.error(f"Unhandled exception (request_id={request_id}): {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_server_error",
                "message": "An unexpected error occurred. Please try again.",
                "request_id": request_id,
            }
        },
    )


# --- Health Endpoint ---
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "timestamp": get_clock().now().isoformat(),
        "version": "2.0.0",
    }


# --- Import and Include Core Routers ---
from backend.routes.auth_routes import router as auth_router
from backend.routes.settings_routes import router as settings_router
from backend.routes.consent_routes import router as consent_router
from backend.routes.order_routes import router as order_router
from backend.routes.bp_routes import router as bp_router

from backend.routes.pulse_routes import router as pulse_router
from backend.routes.behavior_routes import router as behavior_router
from backend.routes.insight_routes import router as insight_router
from backend.routes.baseline_routes import router as baseline_router
from backend.routes.intervention_routes import router as intervention_router

from backend.routes.dashboard_routes import router as dashboard_router
from backend.routes.timeline_routes import router as timeline_router
from backend.routes.data_routes import router as data_router
from backend.routes.demo_routes import router as demo_router

app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(consent_router)
app.include_router(order_router)
app.include_router(bp_router)
app.include_router(pulse_router)
app.include_router(behavior_router)
app.include_router(insight_router)
app.include_router(baseline_router)
app.include_router(intervention_router)
app.include_router(dashboard_router)
app.include_router(timeline_router)
app.include_router(data_router)
app.include_router(demo_router)

# Mount frontend static files
frontend_path = Path("frontend")
if frontend_path.exists():
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
