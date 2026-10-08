"""Deterministic demo data seeding for Project Pulse.

Seeds realistic historical records relative to 'now' and runs the real pipeline.
Never inserts insights directly.
"""

from datetime import datetime, timedelta, timezone, date
import json
import random
from typing import Dict, Any, Tuple
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
    Event,
    CachedBaseline,
)
from backend.auth import hash_password, create_session
from backend.consent import update_consent_state
from backend.services.event_service import record_timeline_event
from backend.services.pattern_engine import run_pattern_engine_for_user
from backend.services.baseline_engine import get_or_calculate_baselines
from backend.clock import get_clock, to_utc


DEMO_EMAIL = "demo@pulse.local"
DEMO_NAME = "Rohan (Demo)"


def seed_demo_user(db: Session) -> Tuple[User, str]:
    """Seed or reset demo user with the deterministic multi-week dataset specified in Section 7.13."""
    now = get_clock().now()

    # Find or create demo user
    demo_user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not demo_user:
        demo_user = User(
            name=DEMO_NAME,
            email=DEMO_EMAIL,
            password_hash=hash_password("DemoPassword123!"),
            is_demo=True,
            created_at=now - timedelta(days=25),
        )
        db.add(demo_user)
        db.flush()
    else:
        # Wipe existing demo data cleanly
        uid = demo_user.id
        db.query(Event).filter(Event.user_id == uid).delete()
        db.query(Order).filter(Order.user_id == uid).delete()
        db.query(BloodPressure).filter(BloodPressure.user_id == uid).delete()
        db.query(PulseSession).filter(PulseSession.user_id == uid).delete()
        db.query(BehaviorSession).filter(BehaviorSession.user_id == uid).delete()
        db.query(Intervention).filter(Intervention.user_id == uid).delete()
        db.query(CachedBaseline).filter(CachedBaseline.user_id == uid).delete()
        db.commit()

    user_id = demo_user.id

    # Ensure user settings
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if not settings:
        settings = UserSettings(user_id=user_id, timezone="Asia/Kolkata")
        db.add(settings)
    else:
        settings.timezone = "Asia/Kolkata"
        settings.late_night_start = "22:30"
        settings.late_night_end = "05:00"
        settings.nudges_enabled = True
        settings.food_nudges_enabled = True
        settings.baselines_reset_at = None
    db.commit()

    # Pre-grant all consents for demo user
    for c_type in ("camera", "behavior", "order_data", "health_data"):
        update_consent_state(user_id, c_type, True, db)

    # --- Week 1 (days 14–20 ago) ---
    # 2 late-night orders
    # Day 18 ago at 23:15 local
    dt_w1_o1 = to_utc(datetime(now.year, now.month, now.day, 23, 15) - timedelta(days=18), "Asia/Kolkata")
    dt_w1_o2 = to_utc(datetime(now.year, now.month, now.day, 23, 45) - timedelta(days=16), "Asia/Kolkata")
    
    order1 = Order(user_id=user_id, event_time=dt_w1_o1, restaurant="Bawarchi", food_items=json.dumps(["Chicken Biryani x1"]), amount=380.0, source="Zomato", food_categories=json.dumps(["high_calorie"]), created_at=dt_w1_o1)
    order2 = Order(user_id=user_id, event_time=dt_w1_o2, restaurant="Midnight Cafe", food_items=json.dumps(["Paneer Roll x1"]), amount=220.0, source="Swiggy", food_categories=json.dumps(["fast_food"]), created_at=dt_w1_o2)
    db.add_all([order1, order2])
    db.flush()
    record_timeline_event(db, user_id, dt_w1_o1, "order", "orders", order1.id, {"title": "Order from Bawarchi", "amount": 380.0, "late_night": True})
    record_timeline_event(db, user_id, dt_w1_o2, "order", "orders", order2.id, {"title": "Order from Midnight Cafe", "amount": 220.0, "late_night": True})

    # 5 BP readings centred on 122/78 (normal) -> baseline 122/78
    w1_bps = [(120, 76), (122, 78), (121, 78), (124, 80), (122, 77)]
    for i, (sys_val, dia_val) in enumerate(w1_bps):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 8, 30) - timedelta(days=20 - i), "Asia/Kolkata")
        bp_obj = BloodPressure(user_id=user_id, event_time=ev_dt, systolic=sys_val, diastolic=dia_val, source="manual", created_at=ev_dt)
        db.add(bp_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "bp", "blood_pressure", bp_obj.id, {"title": f"Blood Pressure: {sys_val}/{dia_val}", "category": "normal"})

    # 5 pulse sessions: 73, 74, 74, 75, 74 -> baseline 74
    w1_pulses = [73.0, 74.0, 74.0, 75.0, 74.0]
    for i, p_val in enumerate(w1_pulses):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 9, 0) - timedelta(days=20 - i), "Asia/Kolkata")
        p_obj = PulseSession(user_id=user_id, event_time=ev_dt, bpm=p_val, duration_seconds=30.0, signal_quality=0.85, source="demo", client_uuid=f"demo-w1-p-{i}", created_at=ev_dt)
        db.add(p_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "pulse", "pulse_sessions", p_obj.id, {"title": f"Pulse: {p_val:.0f} BPM", "bpm": p_val})

    # 5 typing sessions: 46-48 WPM -> baseline 47
    w1_typing = [46.0, 47.0, 47.0, 48.0, 47.0]
    for i, t_val in enumerate(w1_typing):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 11, 0) - timedelta(days=20 - i), "Asia/Kolkata")
        t_obj = BehaviorSession(user_id=user_id, event_time=ev_dt, duration_seconds=60.0, keystrokes=240, backspaces=5, pause_count=3, typing_speed_wpm=t_val, error_rate=0.02, source="demo", client_uuid=f"demo-w1-t-{i}", created_at=ev_dt)
        db.add(t_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "typing", "behavior_sessions", t_obj.id, {"title": f"Typing: {t_val:.0f} WPM", "wpm": t_val})

    # --- Week 2 (days 7–13 ago) ---
    # 3 late-night orders
    w2_order_days = [12, 10, 8]
    for i, d in enumerate(w2_order_days):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 23, 30) - timedelta(days=d), "Asia/Kolkata")
        ord_obj = Order(user_id=user_id, event_time=ev_dt, restaurant=f"Late Kitchen {i}", food_items=json.dumps(["Noodles x1"]), amount=280.0, source="Swiggy", food_categories=json.dumps(["fast_food"]), created_at=ev_dt)
        db.add(ord_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "order", "orders", ord_obj.id, {"title": f"Order from Late Kitchen {i}", "amount": 280.0, "late_night": True})

    # BP around 134/86 on 2 different days (days 11 and 9 ago)
    for d in (11, 9):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 8, 45) - timedelta(days=d), "Asia/Kolkata")
        bp_obj = BloodPressure(user_id=user_id, event_time=ev_dt, systolic=134, diastolic=86, source="manual", created_at=ev_dt)
        db.add(bp_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "bp", "blood_pressure", bp_obj.id, {"title": "Blood Pressure: 134/86", "category": "elevated"})

    # Pulse approx 79 BPM
    for i, d in enumerate((12, 10, 8)):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 14, 0) - timedelta(days=d), "Asia/Kolkata")
        p_obj = PulseSession(user_id=user_id, event_time=ev_dt, bpm=79.0, duration_seconds=30.0, signal_quality=0.82, source="demo", client_uuid=f"demo-w2-p-{i}", created_at=ev_dt)
        db.add(p_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "pulse", "pulse_sessions", p_obj.id, {"title": "Pulse: 79 BPM", "bpm": 79.0})

    # Typing approx 43 WPM (-8%)
    for i, d in enumerate((11, 9)):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 15, 30) - timedelta(days=d), "Asia/Kolkata")
        t_obj = BehaviorSession(user_id=user_id, event_time=ev_dt, duration_seconds=60.0, keystrokes=220, backspaces=5, pause_count=4, typing_speed_wpm=43.0, error_rate=0.02, source="demo", client_uuid=f"demo-w2-t-{i}", created_at=ev_dt)
        db.add(t_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "typing", "behavior_sessions", t_obj.id, {"title": "Typing: 43 WPM", "wpm": 43.0})

    # --- Week 3 (last 7 days) ---
    # Exactly 4 late-night orders at local times: 23:20, 23:30, 23:52, 00:02 (circular average = 23:41!)
    w3_order_times = [
        (5, 23, 20),
        (4, 23, 30),
        (2, 23, 52),
        (1, 0, 2),   # 00:02 next day
    ]
    for days_ago, hour_loc, min_loc in w3_order_times:
        ev_dt = to_utc(datetime(now.year, now.month, now.day, hour_loc, min_loc) - timedelta(days=days_ago), "Asia/Kolkata")
        ord_obj = Order(
            user_id=user_id,
            event_time=ev_dt,
            restaurant="Meghana Foods",
            food_items=json.dumps(["Special Biryani x1", "Thums Up x1"]),
            amount=420.0,
            source="Zomato",
            food_categories=json.dumps(["high_calorie", "sugary"]),
            created_at=ev_dt,
        )
        db.add(ord_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "order", "orders", ord_obj.id, {"title": "Order from Meghana Foods", "amount": 420.0, "late_night": True})

    # Add 1 normal hour order in Week 3
    dt_lunch = to_utc(datetime(now.year, now.month, now.day, 13, 0) - timedelta(days=3), "Asia/Kolkata")
    lunch_ord = Order(user_id=user_id, event_time=dt_lunch, restaurant="Salad Days", food_items=json.dumps(["Green Bowl x1"]), amount=250.0, source="Swiggy", food_categories=json.dumps(["balanced"]), created_at=dt_lunch)
    db.add(lunch_ord)
    db.flush()
    record_timeline_event(db, user_id, dt_lunch, "order", "orders", lunch_ord.id, {"title": "Order from Salad Days", "amount": 250.0, "late_night": False})

    # Latest BP exactly 138/88 (recorded 2 days ago)
    dt_bp_w3 = to_utc(datetime(now.year, now.month, now.day, 9, 30) - timedelta(days=2), "Asia/Kolkata")
    bp_latest = BloodPressure(user_id=user_id, event_time=dt_bp_w3, systolic=138, diastolic=88, source="manual", created_at=dt_bp_w3)
    db.add(bp_latest)
    db.flush()
    record_timeline_event(db, user_id, dt_bp_w3, "bp", "blood_pressure", bp_latest.id, {"title": "Blood Pressure: 138/88", "category": "elevated"})

    # Pulse 81, 82, 83, 82 (average = 82 BPM, +11% and +8 BPM vs baseline 74)
    w3_pulses = [(5, 81.0), (4, 82.0), (2, 83.0), (1, 82.0)]
    for i, (days_ago, p_val) in enumerate(w3_pulses):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 10, 0) - timedelta(days=days_ago), "Asia/Kolkata")
        p_obj = PulseSession(user_id=user_id, event_time=ev_dt, bpm=p_val, duration_seconds=30.0, signal_quality=0.88, source="demo", client_uuid=f"demo-w3-p-{i}", created_at=ev_dt)
        db.add(p_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "pulse", "pulse_sessions", p_obj.id, {"title": f"Pulse: {p_val:.0f} BPM", "bpm": p_val})

    # Typing 41, 40, 39 WPM (average = 40 WPM, -15% vs baseline 47)
    w3_typings = [(4, 41.0), (3, 40.0), (1, 39.0)]
    for i, (days_ago, t_val) in enumerate(w3_typings):
        ev_dt = to_utc(datetime(now.year, now.month, now.day, 16, 0) - timedelta(days=days_ago), "Asia/Kolkata")
        t_obj = BehaviorSession(user_id=user_id, event_time=ev_dt, duration_seconds=60.0, keystrokes=205, backspaces=5, pause_count=5, typing_speed_wpm=t_val, error_rate=0.024, source="demo", client_uuid=f"demo-w3-t-{i}", created_at=ev_dt)
        db.add(t_obj)
        db.flush()
        record_timeline_event(db, user_id, ev_dt, "typing", "behavior_sessions", t_obj.id, {"title": f"Typing: {t_val:.0f} WPM", "wpm": t_val})

    # Historical interventions
    # Wind-down: 2 of 3 completed
    for i in range(3):
        int_dt = to_utc(datetime(now.year, now.month, now.day, 22, 0) - timedelta(days=6 - i * 2), "Asia/Kolkata")
        status_val = "completed" if i < 2 else "dismissed"
        inv = Intervention(user_id=user_id, trigger_type="late_night_pattern", intervention_type="winddown_5min", suggested_by="engine", status=status_val, planned_seconds=300, actual_seconds=300 if status_val == "completed" else None, feeling_after="calmer" if status_val == "completed" else None, created_at=int_dt, started_at=int_dt if status_val == "completed" else None, ended_at=int_dt if status_val == "completed" else None)
        db.add(inv)

    # Breathing: 3 of 4 completed
    for i in range(4):
        int_dt = to_utc(datetime(now.year, now.month, now.day, 17, 0) - timedelta(days=7 - i), "Asia/Kolkata")
        status_val = "completed" if i < 3 else "abandoned"
        inv = Intervention(user_id=user_id, trigger_type="high_load", intervention_type="breathing_4min", suggested_by="engine", status=status_val, planned_seconds=240, actual_seconds=240 if status_val == "completed" else 60, feeling_after="calmer" if status_val == "completed" else None, created_at=int_dt, started_at=int_dt, ended_at=int_dt)
        db.add(inv)

    # Movement: 1 of 3 completed
    for i in range(3):
        int_dt = to_utc(datetime(now.year, now.month, now.day, 15, 0) - timedelta(days=8 - i * 2), "Asia/Kolkata")
        status_val = "completed" if i == 0 else "skipped"
        inv = Intervention(user_id=user_id, trigger_type="sitting_reminder", intervention_type="movement_5min", suggested_by="engine", status=status_val, planned_seconds=300, actual_seconds=300 if status_val == "completed" else None, created_at=int_dt, started_at=int_dt if status_val == "completed" else None, ended_at=int_dt if status_val == "completed" else None)
        db.add(inv)

    db.commit()

    # PUSH THROUGH REAL PIPELINE!
    run_pattern_engine_for_user(user_id, db)

    # Create session token
    token = create_session(user_id, db)
    return demo_user, token
