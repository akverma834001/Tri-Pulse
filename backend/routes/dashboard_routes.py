"""Routes for composite dashboard views."""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    User,
    UserSettings,
    Consent,
    Order,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Intervention,
    Insight,
)
from backend.schemas import (
    DashboardResponse,
    BaselineItem,
    TrendBucket,
    InsightResponse,
)
from backend.auth import get_current_user
from backend.copy import GENERAL_DISCLAIMER
from backend.clock import get_clock, to_local, ensure_utc
from backend.services.baseline_engine import get_or_calculate_baselines
from backend.services.pattern_engine import (
    run_pattern_engine_for_user,
    calculate_circular_average_order_time,
)
from backend.services.bp_classifier import classify_blood_pressure
from backend.services.order_parser import is_late_night_time
from backend.services.intervention_engine import (
    get_recommended_intervention,
    get_smoothed_completion_rate,
)
from backend.routes.insight_routes import _to_insight_response

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def format_relative_age(event_dt: datetime, now_dt: datetime) -> str:
    """Format readable age string (e.g. '2 hours ago', '3 days ago')."""
    diff_sec = int((now_dt - ensure_utc(event_dt)).total_seconds())
    if diff_sec < 60:
        return "just now"
    mins = diff_sec // 60
    if mins < 60:
        return f"{mins} min{'s' if mins > 1 else ''} ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days > 1 else ''} ago"


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = get_clock().now()
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    tz = settings.timezone if settings else "Asia/Kolkata"
    ln_start = settings.late_night_start if settings else "22:30"
    ln_end = settings.late_night_end if settings else "05:00"

    # --- 1. Latest / Today State ---
    # Latest Pulse
    latest_pulse = (
        db.query(PulseSession)
        .filter(PulseSession.user_id == user.id)
        .order_by(PulseSession.event_time.desc())
        .first()
    )
    pulse_state = {
        "has_data": latest_pulse is not None,
        "bpm": latest_pulse.bpm if latest_pulse else None,
        "age": format_relative_age(latest_pulse.event_time, now) if latest_pulse else "No readings yet",
    }

    # Latest BP
    latest_bp = (
        db.query(BloodPressure)
        .filter(BloodPressure.user_id == user.id)
        .order_by(BloodPressure.event_time.desc())
        .first()
    )
    if latest_bp:
        cat, label, _, _ = classify_blood_pressure(latest_bp.systolic, latest_bp.diastolic)
        bp_state = {
            "has_data": True,
            "systolic": latest_bp.systolic,
            "diastolic": latest_bp.diastolic,
            "category": cat,
            "category_label": label,
            "age": format_relative_age(latest_bp.event_time, now),
        }
    else:
        bp_state = {
            "has_data": False,
            "systolic": None,
            "diastolic": None,
            "category": None,
            "category_label": "No readings yet",
            "age": "No readings yet",
        }

    # Late-night orders in last 7 days (exclude cancelled and refunded)
    window_7d = now - timedelta(days=7)
    orders_7d = (
        db.query(Order)
        .filter(Order.user_id == user.id, Order.event_time >= window_7d)
        .all()
    )
    valid_orders_7d = [
        o for o in orders_7d if getattr(o, "order_status", "DELIVERED") not in ("CANCELLED", "REFUNDED")
    ]
    ln_orders_7d = [
        o for o in valid_orders_7d if is_late_night_time(o.event_time, ln_start, ln_end, tz)
    ]
    avg_ln_time = calculate_circular_average_order_time(ln_orders_7d, tz)
    orders_state = {
        "count": len(ln_orders_7d),
        "avg_time": avg_ln_time,
        "has_data": len(valid_orders_7d) > 0,
    }

    # Baselines
    baselines = get_or_calculate_baselines(user.id, db)
    typing_b = baselines["typing"]
    typing_state = {
        "has_data": typing_b.current_val is not None,
        "current_wpm": typing_b.current_val,
        "baseline_wpm": typing_b.baseline_val,
        "deviation_pct": typing_b.deviation_pct,
        "status_text": typing_b.explanation,
    }

    today_state = {
        "pulse": pulse_state,
        "bp": bp_state,
        "late_night_orders": orders_state,
        "typing": typing_state,
    }

    # --- 2. Insights & Recommended Action ---
    insights = run_pattern_engine_for_user(user.id, db)
    primary_ins = None
    supporting_ins = []

    for ins in insights:
        if ins.status != "resolved":
            # Safety safeguard (Section 3): Never display URGENT_BP if there is no current urgent reading
            if ins.rule_id == "URGENT_BP":
                if not latest_bp or not (latest_bp.systolic > 180 or latest_bp.diastolic > 120):
                    continue
            if not ins.is_supporting and primary_ins is None:
                primary_ins = ins
            else:
                supporting_ins.append(ins)

    rec_intervention = get_recommended_intervention(user.id, db)

    # --- 3. Onboarding Checklist ---
    # 1: Consent
    has_consent = db.query(Consent).filter(Consent.user_id == user.id, Consent.granted == True).first() is not None
    # 2: First order or BP
    has_order_or_bp = (
        db.query(Order).filter(Order.user_id == user.id).first() is not None
        or latest_bp is not None
    )
    # 3: Pulse or typing check
    has_pulse_or_typing = (
        latest_pulse is not None
        or db.query(BehaviorSession).filter(BehaviorSession.user_id == user.id).first() is not None
    )
    # 4: See first insight
    has_insight = len(insights) > 0

    steps = [
        {"id": "consent", "label": "Review and grant privacy consents", "completed": has_consent},
        {"id": "first_entry", "label": "Add your first food order or BP reading", "completed": has_order_or_bp},
        {"id": "checkin", "label": "Complete one pulse or typing check", "completed": has_pulse_or_typing},
        {"id": "insights", "label": "View your first behavioral pattern insight", "completed": has_insight},
    ]
    completed_steps_count = sum(1 for s in steps if s["completed"])
    onboarding = {
        "steps": steps,
        "completed_count": completed_steps_count,
        "total_steps": 4,
        "progress_percent": int((completed_steps_count / 4.0) * 100),
        "is_complete": completed_steps_count == 4,
    }

    # --- 4. Baseline Progress ---
    baseline_items = []
    for k, b in baselines.items():
        baseline_items.append(
            BaselineItem(
                signal=b.signal_key,
                name=b.name,
                unit=b.unit,
                baseline_value=b.baseline_val,
                current_value=b.current_val,
                deviation_percent=b.deviation_pct,
                session_count=b.session_count,
                required_sessions=b.required_sessions,
                is_ready=b.is_ready,
                status=getattr(b, "status", "INSUFFICIENT_DATA"),
                explanation=b.explanation,
            )
        )

    # --- 5. Weekly Trends (4 rolling 7-day buckets) ---
    trend_buckets = []
    all_user_orders = db.query(Order).filter(Order.user_id == user.id).all()
    all_user_bps = db.query(BloodPressure).filter(BloodPressure.user_id == user.id).all()
    all_user_pulses = db.query(PulseSession).filter(PulseSession.user_id == user.id).all()
    all_user_typing = db.query(BehaviorSession).filter(BehaviorSession.user_id == user.id).all()
    all_user_interventions = db.query(Intervention).filter(Intervention.user_id == user.id).all()

    typing_baseline_val = baselines["typing"].baseline_val

    for b_idx in range(4):
        # b_idx=0: days 0-6 ago, b_idx=1: days 7-13 ago, b_idx=2: days 14-20 ago, b_idx=3: days 21-27 ago
        b_end = now - timedelta(days=b_idx * 7)
        b_start = now - timedelta(days=(b_idx + 1) * 7)

        # Orders in bucket (exclude cancelled/refunded)
        b_orders = [o for o in all_user_orders if b_start <= ensure_utc(o.event_time) < b_end and getattr(o, "order_status", "DELIVERED") not in ("CANCELLED", "REFUNDED")]
        b_ln_orders = [o for o in b_orders if is_late_night_time(o.event_time, ln_start, ln_end, tz)]

        # BP in bucket
        b_bps = [b for b in all_user_bps if b_start <= ensure_utc(b.event_time) < b_end]
        avg_sys = round(float(np.mean([b.systolic for b in b_bps])), 1) if b_bps else None
        avg_dia = round(float(np.mean([b.diastolic for b in b_bps])), 1) if b_bps else None

        # Pulse in bucket
        b_pulses = [p for p in all_user_pulses if b_start <= ensure_utc(p.event_time) < b_end]
        avg_pulse = round(float(np.mean([p.bpm for p in b_pulses])), 1) if b_pulses else None

        # Typing in bucket
        b_typings = [t for t in all_user_typing if b_start <= ensure_utc(t.event_time) < b_end]
        if b_typings and typing_baseline_val and typing_baseline_val > 0:
            avg_wpm = float(np.mean([t.typing_speed_wpm for t in b_typings]))
            typing_dev = round(((avg_wpm - typing_baseline_val) / typing_baseline_val) * 100.0, 1)
        else:
            typing_dev = None

        # Interventions in bucket
        b_intervs = [i for i in all_user_interventions if b_start <= ensure_utc(i.created_at) < b_end and i.status in ("started", "completed", "waited", "abandoned")]
        comp_count = sum(1 for i in b_intervs if i.status in ("completed", "waited"))
        interv_rate = round(comp_count / len(b_intervs), 2) if b_intervs else None

        labels = ["This week", "1 week ago", "2 weeks ago", "3 weeks ago"]
        trend_buckets.append(
            TrendBucket(
                bucket_label=labels[b_idx],
                window_start=b_start,
                window_end=b_end,
                late_night_orders=len(b_ln_orders),
                has_order_data=len(b_orders) > 0,
                avg_bp_systolic=avg_sys,
                avg_bp_diastolic=avg_dia,
                has_bp_data=len(b_bps) > 0,
                avg_pulse=avg_pulse,
                has_pulse_data=len(b_pulses) > 0,
                typing_deviation_pct=typing_dev,
                has_typing_data=len(b_typings) > 0,
                intervention_completion_rate=interv_rate,
                has_intervention_data=len(b_intervs) > 0,
            )
        )

    return DashboardResponse(
        today_state=today_state,
        primary_insight=_to_insight_response(primary_ins) if primary_ins else None,
        supporting_insights=[_to_insight_response(i) for i in supporting_ins],
        recommended_action=rec_intervention,
        onboarding=onboarding,
        baseline_progress=baseline_items,
        weekly_trends=trend_buckets,
        disclaimer=GENERAL_DISCLAIMER,
    )
