"""Routes for pulse estimation (camera DSP and manual entry)."""

from datetime import datetime, timezone
from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, PulseSession
from backend.schemas import (
    PulseCameraInput,
    PulseManualInput,
    PulseSessionResponse,
)
from backend.auth import get_current_user
from backend.consent import require_consents
from backend.services.pulse_processor import process_pulse_series
from backend.services.event_service import record_timeline_event, delete_timeline_event
from backend.clock import get_clock

router = APIRouter(prefix="/api/pulse", tags=["Pulse"])


@router.post("", response_model=PulseSessionResponse, status_code=status.HTTP_201_CREATED)
def record_pulse(
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record pulse session via camera green series or manual entry."""
    client_uuid = payload.get("client_uuid")
    if not client_uuid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "missing_client_uuid", "message": "client_uuid is required for idempotency."},
        )

    # Idempotency check: if already processed for this user, return existing record
    existing = (
        db.query(PulseSession)
        .filter(PulseSession.user_id == user.id, PulseSession.client_uuid == client_uuid)
        .first()
    )
    if existing:
        return existing

    # Detect source
    if "timestamps_ms" in payload and "green" in payload:
        # Camera PPG
        require_consents(user, db, ["camera", "health_data"])
        ts_list = payload.get("timestamps_ms", [])
        green_list = payload.get("green", [])
        bpm, dur, qual = process_pulse_series(ts_list, green_list)
        source = "camera"
        ev_time = get_clock().now()
    elif "bpm" in payload:
        # Manual entry
        require_consents(user, db, ["health_data"])
        raw_bpm = float(payload.get("bpm", 0))
        if not (30 <= raw_bpm <= 240):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_bpm", "message": "BPM must be between 30 and 240."},
            )
        bpm = round(raw_bpm, 1)
        dur = 30.0
        qual = 1.0  # manual entry assumed verified by user
        source = payload.get("source", "manual")
        ev_time_str = payload.get("event_time")
        if ev_time_str:
            try:
                ev_time = datetime.fromisoformat(ev_time_str)
                if ev_time.tzinfo is None:
                    ev_time = ev_time.replace(tzinfo=timezone.utc)
            except Exception:
                ev_time = get_clock().now()
        else:
            ev_time = get_clock().now()
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_payload", "message": "Must provide either camera data or manual bpm."},
        )

    pulse_session = PulseSession(
        user_id=user.id,
        event_time=ev_time,
        bpm=bpm,
        duration_seconds=dur,
        signal_quality=qual,
        source=source,
        client_uuid=client_uuid,
        created_at=get_clock().now(),
    )
    db.add(pulse_session)
    db.flush()

    # Timeline event
    record_timeline_event(
        db=db,
        user_id=user.id,
        event_time=pulse_session.event_time,
        event_type="pulse",
        ref_table="pulse_sessions",
        ref_id=pulse_session.id,
        summary={
            "title": f"Pulse Check: {pulse_session.bpm:.0f} BPM",
            "bpm": pulse_session.bpm,
            "source": pulse_session.source,
            "quality": pulse_session.signal_quality,
        },
    )

    db.commit()
    db.refresh(pulse_session)

    _trigger_pipeline(user.id, db)

    return pulse_session


@router.get("", response_model=List[PulseSessionResponse])
def get_pulse_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(PulseSession)
        .filter(PulseSession.user_id == user.id)
        .order_by(PulseSession.event_time.desc())
        .all()
    )
    return sessions


@router.delete("/{pulse_id}")
def delete_pulse_session(
    pulse_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_obj = (
        db.query(PulseSession)
        .filter(PulseSession.id == pulse_id, PulseSession.user_id == user.id)
        .first()
    )
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Pulse session not found."},
        )

    delete_timeline_event(db, user.id, "pulse_sessions", session_obj.id)
    db.delete(session_obj)
    db.commit()

    _trigger_pipeline(user.id, db)

    return {"message": "Pulse session deleted successfully."}


def _trigger_pipeline(user_id: int, db: Session):
    try:
        from backend.services.pattern_engine import run_pattern_engine_for_user
        run_pattern_engine_for_user(user_id, db)
    except ImportError:
        pass
