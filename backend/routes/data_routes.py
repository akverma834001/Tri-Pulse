"""Routes for data export and full account/data deletion."""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    User,
    UserSettings,
    Order,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Intervention,
    Insight,
    Event,
    CachedBaseline,
    SessionModel,
    Consent,
)
from backend.schemas import DataDeleteRequest
from backend.auth import get_current_user, verify_password, SESSION_COOKIE_NAME
from backend.services.export_service import generate_full_export_zip, generate_table_csv
from backend.clock import get_clock

router = APIRouter(prefix="/api", tags=["Data Management"])


@router.get("/export")
def export_user_data(
    table: Optional[str] = Query(None, description="Optional specific table name to export as single CSV"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export user data as a ZIP archive of CSVs or a single CSV file."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    user_tz = settings.timezone if settings else "Asia/Kolkata"

    if table:
        valid_tables = ["orders", "blood_pressure", "pulse_sessions", "behavior_sessions", "interventions", "insights", "events", "consent"]
        if table not in valid_tables:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_table", "message": f"Table '{table}' not supported."})
        csv_content = generate_table_csv(table, user.id, db, user_tz)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table}.csv"},
        )

    zip_bytes = generate_full_export_zip(user.id, db)
    timestamp_str = get_clock().now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=pulse_export_{timestamp_str}.zip"},
    )


@router.delete("/account/data")
def delete_all_data(
    data: DataDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete all activity, sensor, behavioral, insight, and event records while preserving login account."""
    if data.confirm.strip() != "DELETE MY DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "confirmation_mismatch", "message": "Confirmation string must be exactly 'DELETE MY DATA'."},
        )

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_password", "message": "Password is incorrect."},
        )

    uid = user.id
    # Count rows before deletion
    c_orders = db.query(Order).filter(Order.user_id == uid).delete()
    c_bp = db.query(BloodPressure).filter(BloodPressure.user_id == uid).delete()
    c_pulse = db.query(PulseSession).filter(PulseSession.user_id == uid).delete()
    c_behavior = db.query(BehaviorSession).filter(BehaviorSession.user_id == uid).delete()
    c_interv = db.query(Intervention).filter(Intervention.user_id == uid).delete()
    c_insights = db.query(Insight).filter(Insight.user_id == uid).delete()
    c_events = db.query(Event).filter(Event.user_id == uid).delete()
    c_baselines = db.query(CachedBaseline).filter(CachedBaseline.user_id == uid).delete()

    db.commit()

    return {
        "message": "All user data deleted successfully.",
        "counts": {
            "orders": c_orders,
            "blood_pressure": c_bp,
            "pulse_sessions": c_pulse,
            "behavior_sessions": c_behavior,
            "interventions": c_interv,
            "insights": c_insights,
            "events": c_events,
            "cached_baselines": c_baselines,
        },
    }


@router.delete("/account")
def delete_entire_account(
    data: DataDeleteRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete user account and all cascading data."""
    if data.confirm.strip() != "DELETE MY DATA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "confirmation_mismatch", "message": "Confirmation string must be exactly 'DELETE MY DATA'."},
        )

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_password", "message": "Password is incorrect."},
        )

    db.delete(user)
    db.commit()

    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"message": "Account and all associated records permanently removed."}
