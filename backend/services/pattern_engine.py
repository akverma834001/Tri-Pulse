"""Pattern engine for Project Pulse.

Deterministic, explainable rule-based pattern detection with circular-time averaging
and idempotent insight upserts.
"""

import json
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from sqlalchemy.orm import Session

from backend.config import (
    RULE_A_LATE_NIGHT_THRESHOLD,
    RULE_B_MIN_DAYS,
    RULE_B_WINDOW_DAYS,
    RULE_PULSE_DEVIATION_PERCENT,
    RULE_PULSE_DIFF_BPM,
    RULE_TYPING_DEVIATION_PERCENT,
    CIRCULAR_HOUR_ORIGIN,
)
from backend.models import (
    User,
    UserSettings,
    Order,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Insight,
)
from backend.copy import INSIGHT_TEMPLATES
from backend.services.order_parser import is_late_night_time
from backend.services.bp_classifier import classify_blood_pressure
from backend.services.baseline_engine import get_or_calculate_baselines
from backend.clock import get_clock, to_local


PRIORITY_ORDER = ["G", "B", "A", "D", "C", "E", "F"]


def calculate_circular_average_order_time(orders: List[Order], user_tz: str = "Asia/Kolkata") -> Optional[str]:
    """Calculate circular average time for late-night orders relative to 18:00 (CIRCULAR_HOUR_ORIGIN).
    Ensures that orders crossing midnight (e.g. 23:52 and 00:02) average to ~23:57 instead of noon.
    """
    if not orders:
        return None

    minutes_after_ref = []
    for o in orders:
        local_dt = to_local(o.event_time, user_tz)
        h = local_dt.hour
        m = local_dt.minute

        # If hour is before origin (e.g. 00:00 to 05:00), treat as next day (h + 24)
        if h < CIRCULAR_HOUR_ORIGIN:
            h += 24

        mins = (h - CIRCULAR_HOUR_ORIGIN) * 60 + m
        minutes_after_ref.append(mins)

    avg_minutes = float(np.mean(minutes_after_ref))
    total_minutes_of_day = (CIRCULAR_HOUR_ORIGIN * 60 + avg_minutes) % 1440
    avg_hour = int(total_minutes_of_day // 60)
    avg_minute = int(round(total_minutes_of_day % 60))

    return f"{avg_hour:02d}:{avg_minute:02d}"


def run_pattern_engine_for_user(user_id: int, db: Session) -> List[Insight]:
    """Evaluate rules A through G for the user and perform idempotent upserts."""
    now = get_clock().now()
    today_date_str = now.strftime("%Y-%m-%d")
    window_7d_start = now - timedelta(days=7)
    window_14d_start = now - timedelta(days=RULE_B_WINDOW_DAYS)

    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    tz = settings.timezone if settings else "Asia/Kolkata"
    ln_start = settings.late_night_start if settings else "22:30"
    ln_end = settings.late_night_end if settings else "05:00"
    food_nudges = settings.food_nudges_enabled if settings else True

    # --- 1. Gather Signals ---
    # Orders
    orders_7d = (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.event_time >= window_7d_start)
        .all()
    )
    late_night_orders = [
        o for o in orders_7d if is_late_night_time(o.event_time, ln_start, ln_end, tz)
    ]
    late_night_count = len(late_night_orders)
    avg_order_time_str = calculate_circular_average_order_time(late_night_orders, tz)

    # Baselines
    baselines = get_or_calculate_baselines(user_id, db)
    pulse_b = baselines["pulse"]
    typing_b = baselines["typing"]
    bp_b = baselines["bp"]

    # Pulse above baseline check: >= +8% AND >= +5 BPM
    pulse_is_above = False
    pulse_diff = 0.0
    if (
        pulse_b.is_ready
        and pulse_b.current_val is not None
        and pulse_b.baseline_val is not None
        and pulse_b.deviation_pct is not None
    ):
        pulse_diff = pulse_b.current_val - pulse_b.baseline_val
        if pulse_b.deviation_pct >= RULE_PULSE_DEVIATION_PERCENT and pulse_diff >= RULE_PULSE_DIFF_BPM:
            pulse_is_above = True

    # Typing below baseline check: <= -10%
    typing_is_below = False
    if (
        typing_b.is_ready
        and typing_b.current_val is not None
        and typing_b.deviation_pct is not None
    ):
        if typing_b.deviation_pct <= RULE_TYPING_DEVIATION_PERCENT:
            typing_is_below = True

    # BP Rule B check: >= 2 different calendar days in 14 days whose daily-average BP is elevated or worse
    bp_14d = (
        db.query(BloodPressure)
        .filter(BloodPressure.user_id == user_id, BloodPressure.event_time >= window_14d_start)
        .all()
    )
    daily_bp_readings: Dict[date, List[Tuple[int, int]]] = {}
    for bp in bp_14d:
        local_day = to_local(bp.event_time, tz).date()
        daily_bp_readings.setdefault(local_day, []).append((bp.systolic, bp.diastolic))

    elevated_bp_days_count = 0
    for day_date, readings in daily_bp_readings.items():
        avg_sys = int(round(np.mean([r[0] for r in readings])))
        avg_dia = int(round(np.mean([r[1] for r in readings])))
        category, _, _, _ = classify_blood_pressure(avg_sys, avg_dia)
        if category in ("elevated", "above_range", "urgent"):
            elevated_bp_days_count += 1

    bp_is_repeated_elevated = elevated_bp_days_count >= RULE_B_MIN_DAYS

    # --- 2. Evaluate Rules ---
    rule_fires: Dict[str, Tuple[bool, List[str]]] = {}

    # Rule A: >= 3 late night orders in 7 days
    if food_nudges and late_night_count >= RULE_A_LATE_NIGHT_THRESHOLD:
        evidence = [f"{late_night_count} late-night orders in 7 days"]
        if avg_order_time_str:
            evidence.append(f"Average order time: {avg_order_time_str}")
        rule_fires["A"] = (True, evidence)
    else:
        rule_fires["A"] = (False, [])

    # Rule B: >= 2 different calendar days in 14 days elevated BP
    if bp_is_repeated_elevated:
        rule_fires["B"] = (
            True,
            [
                f"{elevated_bp_days_count} days with elevated BP readings in the last 14 days",
                "Daily average BP exceeded typical range on multiple days",
            ],
        )
    else:
        rule_fires["B"] = (False, [])

    # Rule C: >= 1 late-night order AND typing below baseline
    if food_nudges and late_night_count >= 1 and typing_is_below:
        rule_fires["C"] = (
            True,
            [
                f"{late_night_count} late-night order(s) in the same 7-day period",
                f"Typing speed {typing_b.current_val:.0f} vs baseline {typing_b.baseline_val:.0f} WPM ({typing_b.deviation_pct:.0f}%)",
            ],
        )
    else:
        rule_fires["C"] = (False, [])

    # Rule D: >= 1 late-night order AND pulse above baseline
    if food_nudges and late_night_count >= 1 and pulse_is_above:
        rule_fires["D"] = (
            True,
            [
                f"{late_night_count} late-night order(s) in the same 7-day period",
                f"Pulse {pulse_b.current_val:.0f} vs baseline {pulse_b.baseline_val:.0f} BPM (+{pulse_b.deviation_pct:.0f}%, +{pulse_diff:.0f} BPM)",
            ],
        )
    else:
        rule_fires["D"] = (False, [])

    # Rule E: pulse above baseline
    if pulse_is_above:
        rule_fires["E"] = (
            True,
            [
                f"Pulse {pulse_b.current_val:.0f} vs baseline {pulse_b.baseline_val:.0f} BPM (+{pulse_b.deviation_pct:.0f}%, +{pulse_diff:.0f} BPM)",
                "Elevated physiological rhythm compared to frozen baseline",
            ],
        )
    else:
        rule_fires["E"] = (False, [])

    # Rule F: typing below baseline
    if typing_is_below:
        rule_fires["F"] = (
            True,
            [
                f"Typing rhythm {typing_b.current_val:.0f} vs baseline {typing_b.baseline_val:.0f} WPM ({typing_b.deviation_pct:.0f}%)",
                "Slower typing speed and increased rhythm variation",
            ],
        )
    else:
        rule_fires["F"] = (False, [])

    # Rule G: Rule A AND at least one of {D/E, C/F, B}
    rule_a_fired = rule_fires["A"][0]
    supporting_signals = []
    if pulse_is_above:
        supporting_signals.append("pulse trend")
    if typing_is_below:
        supporting_signals.append("typing rhythm")
    if bp_is_repeated_elevated:
        supporting_signals.append("elevated blood pressure")

    if rule_a_fired and len(supporting_signals) >= 1:
        evidence_g = [
            f"{late_night_count} late-night orders in 7 days",
        ]
        if avg_order_time_str:
            evidence_g.append(f"Average order time: {avg_order_time_str}")
        if pulse_is_above:
            evidence_g.append(f"Pulse {pulse_b.current_val:.0f} vs baseline {pulse_b.baseline_val:.0f} BPM (+{pulse_b.deviation_pct:.0f}%)")
        if typing_is_below:
            evidence_g.append(f"Typing rhythm {typing_b.current_val:.0f} vs baseline {typing_b.baseline_val:.0f} WPM ({typing_b.deviation_pct:.0f}%)")
        if bp_is_repeated_elevated:
            evidence_g.append(f"{elevated_bp_days_count} days with elevated BP in 14 days")

        rule_fires["G"] = (True, evidence_g)
    else:
        rule_fires["G"] = (False, [])

    # Determine Severity for Rule G
    rule_g_severity = "attention" if len(supporting_signals) >= 2 else "notice"

    # --- 3. Upsert Insights Idempotently ---
    g_active = rule_fires["G"][0]
    upserted_insights = []

    for rule_id, (fires, evidence_list) in rule_fires.items():
        existing = (
            db.query(Insight)
            .filter(
                Insight.user_id == user_id,
                Insight.rule_id == rule_id,
                Insight.window_end_date == today_date_str,
            )
            .first()
        )

        if fires:
            tmpl = INSIGHT_TEMPLATES[rule_id]
            severity = rule_g_severity if rule_id == "G" else tmpl["severity"]

            # If G exists, mark other rules as supporting
            is_supp = (rule_id != "G") if g_active else False

            if not existing:
                ins = Insight(
                    user_id=user_id,
                    rule_id=rule_id,
                    created_at=now,
                    updated_at=now,
                    window_start=window_7d_start,
                    window_end=now,
                    window_end_date=today_date_str,
                    category=tmpl["category"],
                    severity=severity,
                    title=tmpl["title"],
                    explanation=tmpl["explanation"],
                    evidence=json.dumps(evidence_list),
                    recommended_action=tmpl["recommended_action"],
                    status="new",
                    is_supporting=is_supp,
                )
                db.add(ins)
                upserted_insights.append(ins)
            else:
                existing.updated_at = now
                existing.evidence = json.dumps(evidence_list)
                existing.severity = severity
                existing.is_supporting = is_supp
                if existing.status == "resolved":
                    existing.status = "new"
                upserted_insights.append(existing)
        else:
            # If previously existed, mark resolved
            if existing and existing.status != "resolved":
                existing.status = "resolved"
                existing.updated_at = now

    db.commit()

    # Re-fetch active insights in priority order
    active_insights = (
        db.query(Insight)
        .filter(
            Insight.user_id == user_id,
            Insight.window_end_date == today_date_str,
            Insight.status != "resolved",
        )
        .all()
    )

    # Sort according to PRIORITY_ORDER: G > B > A > D > C > E > F
    def get_priority_key(ins: Insight) -> int:
        if ins.rule_id == "URGENT_BP":
            return -1
        try:
            return PRIORITY_ORDER.index(ins.rule_id)
        except ValueError:
            return 99

    active_insights.sort(key=get_priority_key)
    return active_insights
