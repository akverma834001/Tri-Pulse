"""Routes for blood pressure recording, updates, and deletion."""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, BloodPressure, Insight
from backend.schemas import BPCreate, BPUpdate, BPResponse
from backend.auth import get_current_user
from backend.consent import require_consents
from backend.services.bp_classifier import validate_bp_reading, classify_blood_pressure
from backend.services.event_service import record_timeline_event, delete_timeline_event
from backend.copy import INSIGHT_TEMPLATES
from backend.config import BP_DUPLICATE_WINDOW_MINUTES
from backend.clock import get_clock

router = APIRouter(prefix="/api/bp", tags=["Blood Pressure"])


def _to_bp_response(bp: BloodPressure) -> BPResponse:
    category, label, is_urgent, urgent_msg = classify_blood_pressure(bp.systolic, bp.diastolic)
    return BPResponse(
        id=bp.id,
        user_id=bp.user_id,
        event_time=bp.event_time,
        systolic=bp.systolic,
        diastolic=bp.diastolic,
        pulse_optional=bp.pulse_optional,
        category=category,
        category_label=label,
        source=bp.source,
        created_at=bp.created_at,
        urgent_alert=is_urgent,
        urgent_message=urgent_msg,
    )


@router.post("", response_model=BPResponse, status_code=status.HTTP_201_CREATED)
def create_bp_reading(
    data: BPCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_consents(user, db, ["health_data"])

    event_dt = data.event_time or get_clock().now()
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)

    # Validate range and timestamps
    validate_bp_reading(data.systolic, data.diastolic, event_dt)

    # Duplicate check: same systolic & diastolic within 2 minutes
    window_start = event_dt - timedelta(minutes=BP_DUPLICATE_WINDOW_MINUTES)
    window_end = event_dt + timedelta(minutes=BP_DUPLICATE_WINDOW_MINUTES)
    duplicate = (
        db.query(BloodPressure)
        .filter(
            BloodPressure.user_id == user.id,
            BloodPressure.systolic == data.systolic,
            BloodPressure.diastolic == data.diastolic,
            BloodPressure.event_time.between(window_start, window_end),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_reading",
                "message": "A matching blood pressure reading was recorded within the last 2 minutes.",
            },
        )

    category, label, is_urgent, urgent_msg = classify_blood_pressure(data.systolic, data.diastolic)

    bp = BloodPressure(
        user_id=user.id,
        event_time=event_dt,
        systolic=data.systolic,
        diastolic=data.diastolic,
        pulse_optional=data.pulse_optional,
        source=data.source or "manual",
        created_at=get_clock().now(),
    )
    db.add(bp)
    db.flush()

    # Record timeline event
    record_timeline_event(
        db=db,
        user_id=user.id,
        event_time=bp.event_time,
        event_type="bp",
        ref_table="blood_pressure",
        ref_id=bp.id,
        summary={
            "title": f"Blood Pressure: {bp.systolic}/{bp.diastolic} mmHg",
            "category": category,
            "category_label": label,
            "pulse": bp.pulse_optional,
        },
    )

    # If reading is urgent, immediately record an urgent insight
    if is_urgent:
        tmpl = INSIGHT_TEMPLATES["URGENT_BP"]
        now = get_clock().now()
        date_str = event_dt.strftime("%Y-%m-%d")
        urgent_insight = (
            db.query(Insight)
            .filter(
                Insight.user_id == user.id,
                Insight.rule_id == "URGENT_BP",
                Insight.window_end_date == date_str,
            )
            .first()
        )
        if not urgent_insight:
            urgent_insight = Insight(
                user_id=user.id,
                rule_id="URGENT_BP",
                created_at=now,
                updated_at=now,
                window_start=event_dt,
                window_end=event_dt,
                window_end_date=date_str,
                category=tmpl["category"],
                severity=tmpl["severity"],
                title=tmpl["title"],
                explanation=tmpl["explanation"],
                evidence=json.dumps([f"Reading: {bp.systolic}/{bp.diastolic} mmHg"]),
                recommended_action=tmpl["recommended_action"],
                status="new",
                is_supporting=False,
            )
            db.add(urgent_insight)

    db.commit()
    db.refresh(bp)

    _trigger_pipeline(user.id, db)

    return _to_bp_response(bp)


@router.get("", response_model=List[BPResponse])
def get_bp_readings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    readings = (
        db.query(BloodPressure)
        .filter(BloodPressure.user_id == user.id)
        .order_by(BloodPressure.event_time.desc())
        .all()
    )
    return [_to_bp_response(b) for b in readings]


@router.patch("/{bp_id}", response_model=BPResponse)
def update_bp_reading(
    bp_id: int,
    data: BPUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_consents(user, db, ["health_data"])
    bp = db.query(BloodPressure).filter(BloodPressure.id == bp_id, BloodPressure.user_id == user.id).first()
    if not bp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "reading_not_found", "message": "Reading not found."},
        )

    sys_val = data.systolic if data.systolic is not None else bp.systolic
    dia_val = data.diastolic if data.diastolic is not None else bp.diastolic
    ev_time = data.event_time if data.event_time is not None else bp.event_time
    if ev_time.tzinfo is None:
        ev_time = ev_time.replace(tzinfo=timezone.utc)

    validate_bp_reading(sys_val, dia_val, ev_time)

    bp.systolic = sys_val
    bp.diastolic = dia_val
    bp.event_time = ev_time
    if data.pulse_optional is not None:
        bp.pulse_optional = data.pulse_optional

    db.commit()
    db.refresh(bp)

    _trigger_pipeline(user.id, db)

    return _to_bp_response(bp)


@router.delete("/{bp_id}")
def delete_bp_reading(
    bp_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bp = db.query(BloodPressure).filter(BloodPressure.id == bp_id, BloodPressure.user_id == user.id).first()
    if not bp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "reading_not_found", "message": "Reading not found."},
        )

    delete_timeline_event(db, user.id, "blood_pressure", bp.id)
    db.delete(bp)
    db.commit()

    _trigger_pipeline(user.id, db)

    return {"message": "Reading deleted successfully."}


def _trigger_pipeline(user_id: int, db: Session):
    try:
        from backend.services.pattern_engine import run_pattern_engine_for_user
        run_pattern_engine_for_user(user_id, db)
    except ImportError:
        pass
