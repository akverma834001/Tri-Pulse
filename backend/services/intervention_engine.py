"""Intervention engine for Project Pulse.

Handles triggers, cooldowns, quiet hours, state transitions, smoothed completion learning,
and post-session outcome tracking.
"""

from datetime import datetime, timedelta, timezone, time as dt_time
from typing import Dict, Any, Optional, List, Tuple
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.config import (
    INTERVENTION_MAX_DAILY_SUGGESTIONS,
    INTERVENTION_COOLDOWN_HOURS,
    INTERVENTION_DISMISSAL_MUTE_COUNT,
    INTERVENTION_DISMISSAL_MUTE_DAYS,
    INTERVENTION_WORSE_MUTE_COUNT,
    INTERVENTION_LEARNING_MIN_ATTEMPTS,
)
from backend.models import (
    User,
    UserSettings,
    Intervention,
    Insight,
)
from backend.copy import INTERVENTions_INFO
from backend.clock import get_clock, to_local, ensure_utc
from backend.services.event_service import record_timeline_event


VALID_TYPES = ["breathing_4min", "winddown_5min", "order_delay_10min", "movement_5min"]


def is_in_quiet_hours(
    now_dt: datetime,
    quiet_start: str = "01:00",
    quiet_end: str = "07:00",
    user_tz: str = "Asia/Kolkata",
) -> bool:
    """Check if now_dt is within user's configured quiet hours."""
    local_time = to_local(now_dt, user_tz).time()
    sh, sm = map(int, quiet_start.split(":"))
    eh, em = map(int, quiet_end.split(":"))
    st = dt_time(sh, sm)
    et = dt_time(eh, em)

    if st > et:
        return local_time >= st or local_time < et
    return st <= local_time < et


def get_smoothed_completion_rate(attempts: int, completed: int) -> float:
    """Compute smoothed completion rate: (completed + 1) / (attempts + 2)."""
    return round((completed + 1.0) / (attempts + 2.0), 3)


def get_intervention_stats(user_id: int, db: Session) -> Dict[str, Dict[str, Any]]:
    """Compute attempt counts, completed counts, smoothed rate, and feeling outcomes."""
    records = db.query(Intervention).filter(Intervention.user_id == user_id).all()
    stats: Dict[str, Dict[str, Any]] = {
        itype: {
            "intervention_type": itype,
            "title": INTERVENTions_INFO[itype]["title"],
            "attempts": 0,
            "completed": 0,
            "waited": 0,
            "ordered_anyway": 0,
            "calmer": 0,
            "same": 0,
            "worse": 0,
            "smoothed_rate": 0.5,
        }
        for itype in VALID_TYPES
    }

    for rec in records:
        itype = rec.intervention_type
        if itype not in stats:
            continue

        # Count attempts if reached started, completed, abandoned, waited, ordered_anyway
        if rec.status in ("started", "completed", "abandoned", "waited", "ordered_anyway"):
            stats[itype]["attempts"] += 1

        if rec.status in ("completed", "waited"):
            stats[itype]["completed"] += 1

        if rec.status == "waited":
            stats[itype]["waited"] += 1
        elif rec.status == "ordered_anyway":
            stats[itype]["ordered_anyway"] += 1

        if rec.feeling_after == "calmer":
            stats[itype]["calmer"] += 1
        elif rec.feeling_after == "same":
            stats[itype]["same"] += 1
        elif rec.feeling_after == "worse":
            stats[itype]["worse"] += 1

    for itype, data in stats.items():
        data["smoothed_rate"] = get_smoothed_completion_rate(data["attempts"], data["completed"])

    return stats


def check_is_type_muted_worse(user_id: int, intervention_type: str, db: Session) -> bool:
    """Check if user rated 'Worse' twice for this type."""
    worse_count = (
        db.query(Intervention)
        .filter(
            Intervention.user_id == user_id,
            Intervention.intervention_type == intervention_type,
            Intervention.feeling_after == "worse",
        )
        .count()
    )
    return worse_count >= INTERVENTION_WORSE_MUTE_COUNT


def check_is_type_muted_dismissed(user_id: int, intervention_type: str, now: datetime, db: Session) -> bool:
    """Check if the last 2 interactions for this type were dismissals in a row, within 3 days."""
    recent_actions = (
        db.query(Intervention)
        .filter(
            Intervention.user_id == user_id,
            Intervention.intervention_type == intervention_type,
            Intervention.status.in_(["dismissed", "completed", "waited", "started"]),
        )
        .order_by(Intervention.created_at.desc())
        .limit(2)
        .all()
    )
    if len(recent_actions) == 2 and all(r.status == "dismissed" for r in recent_actions):
        most_recent_time = ensure_utc(recent_actions[0].created_at)
        if now - most_recent_time < timedelta(days=INTERVENTION_DISMISSAL_MUTE_DAYS):
            return True
    return False


def get_recommended_intervention(
    user_id: int,
    db: Session,
    manual_stress_flag: bool = False,
) -> Optional[Dict[str, Any]]:
    """Determine the next recommended intervention based on active insights, cooldowns, and learned ranking."""
    now = get_clock().now()
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if settings and not settings.nudges_enabled:
        return None

    tz = settings.timezone if settings else "Asia/Kolkata"
    q_start = settings.quiet_hours_start if settings else "01:00"
    q_end = settings.quiet_hours_end if settings else "07:00"
    food_nudges = settings.food_nudges_enabled if settings else True

    # 1. Quiet Hours check
    if is_in_quiet_hours(now, q_start, q_end, tz):
        return None

    # 2. Daily suggestions cap check (max 3 per day)
    local_today_start = to_local(now, tz).replace(hour=0, minute=0, second=0, microsecond=0)
    utc_today_start = ensure_utc(local_today_start)
    daily_count = (
        db.query(Intervention)
        .filter(
            Intervention.user_id == user_id,
            Intervention.suggested_by == "engine",
            Intervention.created_at >= utc_today_start,
        )
        .count()
    )
    if daily_count >= INTERVENTION_MAX_DAILY_SUGGESTIONS:
        return None

    # 3. Check active insights for triggers
    today_date_str = now.strftime("%Y-%m-%d")
    active_insights = (
        db.query(Insight)
        .filter(
            Insight.user_id == user_id,
            Insight.window_end_date == today_date_str,
            Insight.status != "resolved",
        )
        .all()
    )

    # Urgent BP: never trigger wind-down / relaxation
    urgent_bp_active = any(i.rule_id == "URGENT_BP" for i in active_insights)
    if urgent_bp_active:
        return None

    active_rule_ids = {i.rule_id: i for i in active_insights}

    # Determine candidate triggers and types
    candidates: List[Tuple[str, str, Optional[int]]] = []  # (trigger_type, intervention_type, insight_id)

    # Rule A or G -> suggest winddown_5min (if food nudges enabled)
    if food_nudges and ("G" in active_rule_ids or "A" in active_rule_ids):
        ins_id = active_rule_ids.get("G", active_rule_ids.get("A")).id
        candidates.append(("late_night_pattern", "winddown_5min", ins_id))

    # High load: Rule C, D, E, F or manual stress -> suggest breathing_4min
    if manual_stress_flag or any(r in active_rule_ids for r in ("C", "D", "E", "F")):
        ins_match = next((active_rule_ids[r].id for r in ("C", "D", "E", "F") if r in active_rule_ids), None)
        candidates.append(("high_load", "breathing_4min", ins_match))

    if not candidates:
        return None

    stats = get_intervention_stats(user_id, db)

    # 4. Filter out cooling down, worse-muted, or dismissed-muted types
    valid_candidates = []
    for trigger_type, itype, ins_id in candidates:
        # Check Worse mute
        if check_is_type_muted_worse(user_id, itype, db):
            continue

        # Check Dismissal mute
        if check_is_type_muted_dismissed(user_id, itype, now, db):
            continue

        # Check 6-hour cooldown for same type
        six_hours_ago = now - timedelta(hours=INTERVENTION_COOLDOWN_HOURS)
        recent_same = (
            db.query(Intervention)
            .filter(
                Intervention.user_id == user_id,
                Intervention.intervention_type == itype,
                Intervention.created_at >= six_hours_ago,
            )
            .first()
        )
        if recent_same:
            continue

        valid_candidates.append((trigger_type, itype, ins_id))

    if not valid_candidates:
        return None

    # 5. Learning & Personalization ranking if attempts >= 5
    def candidate_score(item: Tuple[str, str, Optional[int]]) -> float:
        c_type = item[1]
        c_stats = stats.get(c_type, {})
        attempts = c_stats.get("attempts", 0)
        if attempts >= INTERVENTION_LEARNING_MIN_ATTEMPTS:
            return c_stats.get("smoothed_rate", 0.5)
        # Default priority: winddown if late night, breathing if stress
        return 1.0 if item[0] == "late_night_pattern" else 0.8

    valid_candidates.sort(key=candidate_score, reverse=True)
    selected_trigger, selected_type, selected_ins_id = valid_candidates[0]

    info = INTERVENTions_INFO[selected_type]
    return {
        "trigger_type": selected_trigger,
        "intervention_type": selected_type,
        "title": info["title"],
        "subtitle": info["subtitle"],
        "planned_seconds": info["planned_seconds"],
        "instructions": info["instructions"],
        "safety_note": info["safety_note"],
        "insight_id": selected_ins_id,
        "suggested_by": "engine",
    }


def update_intervention_status(
    intervention: Intervention,
    new_status: str,
    db: Session,
    actual_seconds: Optional[int] = None,
    feeling_after: Optional[str] = None,
) -> Intervention:
    """Transition intervention state with strict state machine verification."""
    now = get_clock().now()
    cur = intervention.status

    # State machine rules
    # suggested -> started, skipped, dismissed
    # started -> completed, abandoned
    # order_delay_10min: suggested -> started -> waited, ordered_anyway, dismissed
    allowed_transitions = {
        "suggested": ["started", "skipped", "dismissed", "waited", "ordered_anyway"],
        "started": ["completed", "abandoned", "waited", "ordered_anyway"],
    }

    if cur not in allowed_transitions or new_status not in allowed_transitions[cur]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "invalid_state_transition",
                "message": f"Cannot transition intervention from '{cur}' to '{new_status}'.",
            },
        )

    intervention.status = new_status

    if new_status == "started" and not intervention.started_at:
        intervention.started_at = now
        record_timeline_event(
            db=db,
            user_id=intervention.user_id,
            event_time=now,
            event_type="intervention_started",
            ref_table="interventions",
            ref_id=intervention.id,
            summary={"type": intervention.intervention_type, "status": "started"},
        )
    elif new_status in ("completed", "abandoned", "waited", "ordered_anyway"):
        intervention.ended_at = now
        if actual_seconds is not None:
            intervention.actual_seconds = actual_seconds
        elif intervention.started_at:
            intervention.actual_seconds = int((now - ensure_utc(intervention.started_at)).total_seconds())

        if feeling_after:
            intervention.feeling_after = feeling_after

        record_timeline_event(
            db=db,
            user_id=intervention.user_id,
            event_time=now,
            event_type=f"intervention_{new_status}",
            ref_table="interventions",
            ref_id=intervention.id,
            summary={
                "type": intervention.intervention_type,
                "status": new_status,
                "feeling": intervention.feeling_after,
            },
        )
    elif new_status in ("skipped", "dismissed"):
        intervention.ended_at = now

    db.commit()
    db.refresh(intervention)
    return intervention
