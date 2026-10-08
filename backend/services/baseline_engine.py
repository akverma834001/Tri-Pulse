"""Personal baseline engine for Project Pulse.

Calculates frozen starting baselines (median of first 5 valid values)
and 7-day rolling current averages.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.config import (
    BASELINE_REQUIRED_SESSIONS,
    BASELINE_CURRENT_WINDOW_DAYS,
    BASELINE_CURRENT_MIN_SESSIONS,
    BASELINE_LATE_NIGHT_WINDOW_DAYS,
)
from backend.models import (
    User,
    UserSettings,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Order,
    CachedBaseline,
)
from backend.services.order_parser import is_late_night_time
from backend.clock import get_clock, ensure_utc


class BaselineSummary:
    def __init__(
        self,
        signal_key: str,
        name: str,
        unit: str,
        baseline_val: Optional[float],
        current_val: Optional[float],
        session_count: int,
        required_sessions: int = BASELINE_REQUIRED_SESSIONS,
    ):
        self.signal_key = signal_key
        self.name = name
        self.unit = unit
        self.baseline_val = baseline_val
        self.current_val = current_val
        self.session_count = session_count
        self.required_sessions = required_sessions
        self.is_ready = session_count >= required_sessions and baseline_val is not None

        if self.is_ready and current_val is not None and baseline_val is not None and baseline_val > 0:
            self.deviation_pct = round(((current_val - baseline_val) / baseline_val) * 100.0, 1)
        else:
            self.deviation_pct = None

        if not self.is_ready:
            self.explanation = f"Baseline building ({min(session_count, required_sessions)} of {required_sessions} sessions)"
        elif self.current_val is None:
            self.explanation = "Need at least 2 sessions in the last 7 days to evaluate trend"
        elif self.deviation_pct is not None:
            sign = "+" if self.deviation_pct > 0 else ""
            self.explanation = f"Current {current_val:.1f} vs baseline {baseline_val:.1f} {unit} ({sign}{self.deviation_pct:.1f}%)"
        else:
            self.explanation = f"Baseline established at {baseline_val:.1f} {unit}"


def get_user_reset_timestamp(user_id: int, db: Session) -> Optional[datetime]:
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    return settings.baselines_reset_at if settings else None


def compute_frozen_baseline(values: List[float], required_count: int = BASELINE_REQUIRED_SESSIONS) -> Optional[float]:
    """Compute median of first N sessions."""
    if len(values) < required_count:
        return None
    first_n = values[:required_count]
    return round(float(np.median(first_n)), 1)


def get_or_calculate_baselines(user_id: int, db: Session) -> Dict[str, BaselineSummary]:
    """Calculate all frozen baselines and current 7-day values for a user."""
    now = get_clock().now()
    reset_at = get_user_reset_timestamp(user_id, db)
    window_7d = now - timedelta(days=BASELINE_CURRENT_WINDOW_DAYS)

    # 1. Pulse sessions
    pulse_q = db.query(PulseSession).filter(PulseSession.user_id == user_id)
    if reset_at:
        pulse_q = pulse_q.filter(PulseSession.event_time >= reset_at)
    pulse_records = pulse_q.order_by(PulseSession.event_time.asc()).all()

    pulse_vals = [p.bpm for p in pulse_records]
    pulse_baseline = compute_frozen_baseline(pulse_vals)
    # Current: mean of last 7 days if >= 2 sessions
    recent_pulse = [p.bpm for p in pulse_records if ensure_utc(p.event_time) >= window_7d]
    pulse_current = (
        round(float(np.mean(recent_pulse)), 1)
        if len(recent_pulse) >= BASELINE_CURRENT_MIN_SESSIONS
        else None
    )

    pulse_summary = BaselineSummary(
        signal_key="pulse_bpm",
        name="Resting Pulse",
        unit="BPM",
        baseline_val=pulse_baseline,
        current_val=pulse_current,
        session_count=len(pulse_vals),
    )

    # 2. Behavior sessions
    behav_q = db.query(BehaviorSession).filter(BehaviorSession.user_id == user_id)
    if reset_at:
        behav_q = behav_q.filter(BehaviorSession.event_time >= reset_at)
    behav_records = behav_q.order_by(BehaviorSession.event_time.asc()).all()

    wpm_vals = [b.typing_speed_wpm for b in behav_records]
    wpm_baseline = compute_frozen_baseline(wpm_vals)
    recent_wpm = [b.typing_speed_wpm for b in behav_records if ensure_utc(b.event_time) >= window_7d]
    wpm_current = (
        round(float(np.mean(recent_wpm)), 1)
        if len(recent_wpm) >= BASELINE_CURRENT_MIN_SESSIONS
        else None
    )

    wpm_summary = BaselineSummary(
        signal_key="typing_wpm",
        name="Typing Rhythm",
        unit="WPM",
        baseline_val=wpm_baseline,
        current_val=wpm_current,
        session_count=len(wpm_vals),
    )

    # 3. Blood Pressure
    bp_q = db.query(BloodPressure).filter(BloodPressure.user_id == user_id)
    if reset_at:
        bp_q = bp_q.filter(BloodPressure.event_time >= reset_at)
    bp_records = bp_q.order_by(BloodPressure.event_time.asc()).all()

    sys_vals = [float(b.systolic) for b in bp_records]
    dia_vals = [float(b.diastolic) for b in bp_records]
    sys_baseline = compute_frozen_baseline(sys_vals)
    dia_baseline = compute_frozen_baseline(dia_vals)

    recent_sys = [float(b.systolic) for b in bp_records if ensure_utc(b.event_time) >= window_7d]
    recent_dia = [float(b.diastolic) for b in bp_records if ensure_utc(b.event_time) >= window_7d]
    sys_current = round(float(np.mean(recent_sys)), 1) if recent_sys else None
    dia_current = round(float(np.mean(recent_dia)), 1) if recent_dia else None

    bp_summary = BaselineSummary(
        signal_key="bp",
        name="Blood Pressure",
        unit="mmHg",
        baseline_val=sys_baseline,
        current_val=sys_current,
        session_count=len(bp_records),
    )
    # Store diastolic baseline on object
    bp_summary.dia_baseline = dia_baseline
    bp_summary.dia_current = dia_current

    return {
        "pulse": pulse_summary,
        "typing": wpm_summary,
        "bp": bp_summary,
    }
