"""Export service for Project Pulse.

Generates CSV files with formula injection protection and packages them into a ZIP archive.
"""

import csv
import io
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

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
    Event,
)
from backend.copy import GENERAL_DISCLAIMER
from backend.clock import get_clock, to_local, ensure_utc


def sanitize_csv_cell(value: Any) -> str:
    """Neutralize CSV formula injection:
    Prefix any cell starting with '=', '+', '-', '@', tab, or CR with a single quote.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


def build_csv_string(headers: List[str], rows: List[List[Any]]) -> str:
    """Generate a sanitized CSV string with UTF-8 encoding."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([sanitize_csv_cell(h) for h in headers])
    for r in rows:
        writer.writerow([sanitize_csv_cell(v) for v in r])
    return output.getvalue()


def generate_table_csv(table_name: str, user_id: int, db: Session, user_tz: str) -> str:
    """Generate sanitized CSV for a specific table."""
    def fmt_dt(dt: Optional[datetime]) -> Tuple[str, str]:
        if not dt:
            return "", ""
        u_dt = ensure_utc(dt)
        l_dt = to_local(u_dt, user_tz)
        return u_dt.isoformat(), l_dt.strftime("%Y-%m-%d %H:%M:%S")

    if table_name == "orders":
        headers = ["id", "event_time_utc", "event_time_local", "restaurant", "food_items", "amount", "source", "food_categories", "date_assumed", "parse_confidence", "created_at_utc"]
        records = db.query(Order).filter(Order.user_id == user_id).order_by(Order.event_time.desc()).all()
        rows = []
        for o in records:
            u_t, l_t = fmt_dt(o.event_time)
            rows.append([o.id, u_t, l_t, o.restaurant, o.food_items, o.amount, o.source, o.food_categories, o.date_assumed, o.parse_confidence, fmt_dt(o.created_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "blood_pressure":
        headers = ["id", "event_time_utc", "event_time_local", "systolic", "diastolic", "pulse_optional", "source", "created_at_utc"]
        records = db.query(BloodPressure).filter(BloodPressure.user_id == user_id).order_by(BloodPressure.event_time.desc()).all()
        rows = []
        for b in records:
            u_t, l_t = fmt_dt(b.event_time)
            rows.append([b.id, u_t, l_t, b.systolic, b.diastolic, b.pulse_optional, b.source, fmt_dt(b.created_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "pulse_sessions":
        headers = ["id", "event_time_utc", "event_time_local", "bpm", "duration_seconds", "signal_quality", "source", "client_uuid", "created_at_utc"]
        records = db.query(PulseSession).filter(PulseSession.user_id == user_id).order_by(PulseSession.event_time.desc()).all()
        rows = []
        for p in records:
            u_t, l_t = fmt_dt(p.event_time)
            rows.append([p.id, u_t, l_t, p.bpm, p.duration_seconds, p.signal_quality, p.source, p.client_uuid, fmt_dt(p.created_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "behavior_sessions":
        headers = ["id", "event_time_utc", "event_time_local", "duration_seconds", "keystrokes", "backspaces", "pause_count", "typing_speed_wpm", "error_rate", "source", "client_uuid", "created_at_utc"]
        records = db.query(BehaviorSession).filter(BehaviorSession.user_id == user_id).order_by(BehaviorSession.event_time.desc()).all()
        rows = []
        for s in records:
            u_t, l_t = fmt_dt(s.event_time)
            rows.append([s.id, u_t, l_t, s.duration_seconds, s.keystrokes, s.backspaces, s.pause_count, s.typing_speed_wpm, s.error_rate, s.source, s.client_uuid, fmt_dt(s.created_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "interventions":
        headers = ["id", "created_at_utc", "created_at_local", "trigger_type", "intervention_type", "suggested_by", "insight_id", "status", "planned_seconds", "actual_seconds", "feeling_after", "started_at_utc", "ended_at_utc"]
        records = db.query(Intervention).filter(Intervention.user_id == user_id).order_by(Intervention.created_at.desc()).all()
        rows = []
        for i in records:
            u_t, l_t = fmt_dt(i.created_at)
            rows.append([i.id, u_t, l_t, i.trigger_type, i.intervention_type, i.suggested_by, i.insight_id, i.status, i.planned_seconds, i.actual_seconds, i.feeling_after, fmt_dt(i.started_at)[0], fmt_dt(i.ended_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "insights":
        headers = ["id", "rule_id", "created_at_utc", "category", "severity", "title", "explanation", "evidence", "recommended_action", "status", "is_supporting", "feedback"]
        records = db.query(Insight).filter(Insight.user_id == user_id).order_by(Insight.created_at.desc()).all()
        rows = []
        for ins in records:
            rows.append([ins.id, ins.rule_id, fmt_dt(ins.created_at)[0], ins.category, ins.severity, ins.title, ins.explanation, ins.evidence, ins.recommended_action, ins.status, ins.is_supporting, ins.feedback])
        return build_csv_string(headers, rows)

    elif table_name == "events":
        headers = ["id", "event_time_utc", "event_time_local", "event_type", "ref_table", "ref_id", "summary_json", "created_at_utc"]
        records = db.query(Event).filter(Event.user_id == user_id).order_by(Event.event_time.desc()).all()
        rows = []
        for ev in records:
            u_t, l_t = fmt_dt(ev.event_time)
            rows.append([ev.id, u_t, l_t, ev.event_type, ev.ref_table, ev.ref_id, ev.summary_json, fmt_dt(ev.created_at)[0]])
        return build_csv_string(headers, rows)

    elif table_name == "consent":
        headers = ["id", "consent_type", "granted", "consent_version", "granted_at_utc", "revoked_at_utc"]
        records = db.query(Consent).filter(Consent.user_id == user_id).all()
        rows = []
        for c in records:
            rows.append([c.id, c.consent_type, c.granted, c.consent_version, fmt_dt(c.granted_at)[0], fmt_dt(c.revoked_at)[0]])
        return build_csv_string(headers, rows)

    return ""


def generate_full_export_zip(user_id: int, db: Session) -> bytes:
    """Generate in-memory zip archive containing CSVs of all user tables plus README.txt."""
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    user_tz = settings.timezone if settings else "Asia/Kolkata"
    now = get_clock().now()

    tables = [
        "orders",
        "blood_pressure",
        "pulse_sessions",
        "behavior_sessions",
        "interventions",
        "insights",
        "events",
        "consent",
    ]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t_name in tables:
            csv_content = generate_table_csv(t_name, user_id, db, user_tz)
            zf.writestr(f"{t_name}.csv", csv_content)

        # Add README.txt
        readme_content = (
            f"PROJECT PULSE DATA EXPORT\n"
            f"========================\n"
            f"Export Date (UTC): {now.isoformat()}\n"
            f"User Timezone: {user_tz}\n\n"
            f"Medical Disclaimer:\n"
            f"{GENERAL_DISCLAIMER}\n\n"
            f"Files included:\n"
            f"- orders.csv: Food orders derived from parsed receipts\n"
            f"- blood_pressure.csv: Blood pressure readings\n"
            f"- pulse_sessions.csv: Pulse checks (camera DSP and manual)\n"
            f"- behavior_sessions.csv: Typing rhythm rhythm metrics (no text)\n"
            f"- interventions.csv: Completed/started micro-interventions\n"
            f"- insights.csv: Generated behavioral insights and patterns\n"
            f"- events.csv: Chronological timeline events\n"
            f"- consent.csv: Audit log of data collection consents\n"
        )
        zf.writestr("README.txt", readme_content)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()
