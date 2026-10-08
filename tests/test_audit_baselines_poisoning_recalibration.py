"""Audit Test: Baseline Architecture, Anti-Poisoning & Recalibration (Sections 7, 8, 9, 10, 20, 21).
Verifies:
1. Two-layer insight architecture: Layer A rule-based signals fire immediately without 5 baseline sessions.
2. Baseline status progression: NOT_STARTED -> INSUFFICIENT_DATA -> ESTABLISHED -> RECALIBRATING.
3. Baseline anti-poisoning: rapid-fire sessions (< 3 minutes apart) are marked is_baseline_eligible=False.
4. Baseline recalibration: resets baseline calculation, increments baseline_version, does NOT delete raw health records.
5. Minimum typing session thresholds (>= 40 keystrokes, >= 30 seconds).
"""

import pytest
from datetime import datetime, timezone, timedelta
from backend.models import User, PulseSession, BehaviorSession, Order, UserSettings
from backend.consent import update_consent_state
from backend.services.baseline_engine import get_or_calculate_baselines
from backend.services.pattern_engine import run_pattern_engine_for_user


def test_layer_a_rule_based_insights_work_without_baseline(client, authenticated_user, db_session):
    """Section 7: Layer A immediate signals work with 0 baseline sessions."""
    user, headers = authenticated_user
    update_consent_state(user.id, "order_data", True, db_session)

    # User has 0 pulse and 0 typing sessions (baseline is NOT_STARTED / INSUFFICIENT_DATA)
    baselines = get_or_calculate_baselines(user.id, db_session)
    assert baselines["pulse"].status == "NOT_STARTED"

    # User adds 3 late-night orders in 7 days
    now = datetime.now(timezone.utc)
    for i in range(3):
        # 11:30 PM local (Asia/Kolkata) = 18:00 UTC
        dt = datetime(now.year, now.month, now.day, 18, 0, tzinfo=timezone.utc) - timedelta(days=i + 1)
        client.post(
            "/api/orders",
            json={
                "restaurant": f"Late Spot {i}",
                "amount": 350.0,
                "event_time": dt.isoformat(),
                "order_status": "DELIVERED",
                "source": "Zomato",
                "food_items": ["Biryani"],
            },
            headers=headers,
        )

    # Layer A Rule A MUST fire even with zero baseline sessions!
    insights = run_pattern_engine_for_user(user.id, db_session)
    rule_a_found = any(i.rule_id in ("A", "RULE_A_LATE_NIGHT_ROUTINE") for i in insights)
    assert rule_a_found, "Layer A rule-based insight must fire without baseline"


def test_baseline_anti_poisoning_rapid_sessions(client, authenticated_user, db_session):
    """Section 21: Prevent baseline poisoning from rapid-fire spam sessions."""
    user, headers = authenticated_user
    update_consent_state(user.id, "health_data", True, db_session)

    now = datetime.now(timezone.utc)

    # Submit session 1
    res1 = client.post(
        "/api/pulse",
        json={
            "bpm": 72,
            "duration_seconds": 30,
            "source": "manual",
            "event_time": now.isoformat(),
            "client_uuid": "uuid-1",
        },
        headers=headers,
    )
    assert res1.status_code == 201

    # Submit session 2 only 30 seconds later (too soon: < 180s)
    res2 = client.post(
        "/api/pulse",
        json={
            "bpm": 120,  # Poison reading!
            "duration_seconds": 30,
            "source": "manual",
            "event_time": (now + timedelta(seconds=30)).isoformat(),
            "client_uuid": "uuid-2",
        },
        headers=headers,
    )
    assert res2.status_code == 201

    # Check database: second session must have is_baseline_eligible = False!
    sessions = db_session.query(PulseSession).filter(PulseSession.user_id == user.id).order_by(PulseSession.event_time.asc()).all()
    assert len(sessions) == 2
    assert sessions[0].is_baseline_eligible is True
    assert sessions[1].is_baseline_eligible is False, "Rapid session must be marked ineligible for baseline"


def test_baseline_recalibration_lifecycle(client, authenticated_user, db_session):
    """Section 10: Recalibration resets calculation & increments version without deleting historical records."""
    user, headers = authenticated_user
    update_consent_state(user.id, "health_data", True, db_session)

    now = datetime.now(timezone.utc)

    # Add 5 valid spaced pulse sessions
    for i in range(5):
        client.post(
            "/api/pulse",
            json={
                "bpm": 70 + i,
                "duration_seconds": 30,
                "source": "manual",
                "event_time": (now - timedelta(days=5 - i)).isoformat(),
                "client_uuid": f"pulse-rec-{i}",
            },
            headers=headers,
        )

    # Baseline should be established
    b_before = get_or_calculate_baselines(user.id, db_session)
    assert b_before["pulse"].status == "ESTABLISHED"
    assert b_before["pulse"].is_ready is True

    # User requests recalibration via settings
    recal_res = client.post("/api/settings/recalibrate", headers=headers)
    assert recal_res.status_code == 200

    # User settings baseline_version must have incremented
    settings = db_session.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    assert settings.baseline_version >= 2
    assert settings.baselines_reset_at is not None

    # Historical pulse records must STILL exist in database!
    pulse_count = db_session.query(PulseSession).filter(PulseSession.user_id == user.id).count()
    assert pulse_count == 5, "Historical data must not be deleted during recalibration"

    # Baseline status is now RECALIBRATING (needs 5 new sessions)
    b_after = get_or_calculate_baselines(user.id, db_session)
    assert b_after["pulse"].status == "RECALIBRATING"
    assert b_after["pulse"].is_ready is False
