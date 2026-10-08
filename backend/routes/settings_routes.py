"""Settings management routes."""

import re
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User, UserSettings, CachedBaseline
from backend.schemas import SettingsResponse, SettingsUpdate
from backend.auth import get_current_user
from backend.clock import get_clock

router = APIRouter(prefix="/api/settings", tags=["Settings"])

TIME_REGEX = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validate_time_format(val: str, field_name: str) -> None:
    if not TIME_REGEX.match(val):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_time_format", "message": f"{field_name} must be in HH:MM format (24-hour)"},
        )


@router.get("", response_model=SettingsResponse)
def get_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.patch("", response_model=SettingsResponse)
def update_settings(
    data: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)

    if data.timezone is not None:
        try:
            ZoneInfo(data.timezone)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_timezone", "message": f"Unknown timezone: {data.timezone}"},
            )
        settings.timezone = data.timezone

    if data.late_night_start is not None:
        validate_time_format(data.late_night_start, "late_night_start")
        settings.late_night_start = data.late_night_start

    if data.late_night_end is not None:
        validate_time_format(data.late_night_end, "late_night_end")
        settings.late_night_end = data.late_night_end

    if data.quiet_hours_start is not None:
        validate_time_format(data.quiet_hours_start, "quiet_hours_start")
        settings.quiet_hours_start = data.quiet_hours_start

    if data.quiet_hours_end is not None:
        validate_time_format(data.quiet_hours_end, "quiet_hours_end")
        settings.quiet_hours_end = data.quiet_hours_end

    if data.nudges_enabled is not None:
        settings.nudges_enabled = data.nudges_enabled

    if data.food_nudges_enabled is not None:
        settings.food_nudges_enabled = data.food_nudges_enabled

    if data.sitting_reminder_minutes is not None:
        settings.sitting_reminder_minutes = data.sitting_reminder_minutes

    db.commit()
    db.refresh(settings)
    return settings


from backend.services.event_service import record_timeline_event


@router.post("/recalibrate")
def recalibrate_baselines(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset baselines to rebuild from next 5 values."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
    
    now = get_clock().now()
    settings.baselines_reset_at = now
    settings.baseline_version = (settings.baseline_version or 1) + 1

    # Clear existing cached baselines for this user
    db.query(CachedBaseline).filter(CachedBaseline.user_id == user.id).delete()

    record_timeline_event(
        db=db,
        user_id=user.id,
        event_time=now,
        event_type="baseline",
        ref_table="user_settings",
        ref_id=user.id,
        summary={
            "title": f"Baselines Recalibrated (v{settings.baseline_version})",
            "message": "Reset baseline calculation. Next 5 sessions will establish new personal baselines.",
        },
    )

    db.commit()

    try:
        from backend.services.pattern_engine import run_pattern_engine_for_user
        run_pattern_engine_for_user(user.id, db)
    except Exception:
        pass

    return {
        "message": f"Baselines marked for recalibration (version {settings.baseline_version}). Next 5 sessions will establish new baselines.",
        "baseline_version": settings.baseline_version,
    }
