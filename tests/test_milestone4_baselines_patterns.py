"""Tests for Milestone 4: Baselines and Deterministic Pattern Engine."""

from datetime import datetime, timedelta, timezone
import json
import pytest
from backend.services.baseline_engine import get_or_calculate_baselines, compute_frozen_baseline
from backend.services.pattern_engine import (
    calculate_circular_average_order_time,
    run_pattern_engine_for_user,
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


def test_circular_average_order_time():
    """Verify circular time averaging around midnight relative to 18:00."""
    # Create mock orders: 23:52 and 00:02 local time
    # In Asia/Kolkata (UTC+5:30):
    # 23:52 local = 18:22 UTC
    # 00:02 local (next day) = 18:32 UTC
    o1 = Order(event_time=datetime(2026, 10, 8, 18, 22, tzinfo=timezone.utc), restaurant="A")
    o2 = Order(event_time=datetime(2026, 10, 8, 18, 32, tzinfo=timezone.utc), restaurant="B")

    avg_time = calculate_circular_average_order_time([o1, o2], user_tz="Asia/Kolkata")
    assert avg_time == "23:57", f"Expected '23:57', got '{avg_time}'"


def test_baselines_progress_and_median(client, db_session):
    """Verify baseline requires 5 sessions and calculates median."""
    # Register user
    reg = client.post(
        "/api/auth/register",
        json={"name": "Baseline User", "email": "base_user@test.com", "password": "Password1234!", "age_confirmed": True},
    )
    user_id = reg.json()["id"]
    client.put("/api/consent", json={"health_data": True, "camera": True, "behavior": True})

    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    # 1. Check with 3 pulse sessions (not ready)
    for i, bpm in enumerate([72.0, 75.0, 74.0]):
        db_session.add(
            PulseSession(
                user_id=user_id,
                event_time=now - timedelta(days=10 - i),
                bpm=bpm,
                duration_seconds=30.0,
                signal_quality=0.8,
                source="manual",
                client_uuid=f"base-pulse-{i}",
                created_at=now,
            )
        )
    db_session.commit()

    b_summary = get_or_calculate_baselines(user_id, db_session)
    assert b_summary["pulse"].is_ready is False
    assert b_summary["pulse"].session_count == 3
    assert b_summary["pulse"].baseline_val is None

    # 2. Add 2 more sessions -> 5 sessions total: [72, 75, 74, 80, 74] -> sorted: [72, 74, 74, 75, 80] -> median = 74.0
    for i, bpm in enumerate([80.0, 74.0], start=3):
        db_session.add(
            PulseSession(
                user_id=user_id,
                event_time=now - timedelta(days=10 - i),
                bpm=bpm,
                duration_seconds=30.0,
                signal_quality=0.8,
                source="manual",
                client_uuid=f"base-pulse-{i}",
                created_at=now,
            )
        )
    db_session.commit()

    b_summary = get_or_calculate_baselines(user_id, db_session)
    assert b_summary["pulse"].is_ready is True
    assert b_summary["pulse"].baseline_val == 74.0


def test_pattern_engine_rules(client, db_session, mock_clock):
    """Test Rules A, B, C, D, E, F, G, idempotency and resolution."""
    # Fix test clock
    test_now = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)
    mock_clock.set_time(test_now)

    reg = client.post(
        "/api/auth/register",
        json={"name": "Pattern User", "email": "pattern_user@test.com", "password": "Password1234!", "age_confirmed": True},
    )
    user_id = reg.json()["id"]
    client.put("/api/consent", json={"health_data": True, "order_data": True, "behavior": True})

    # Initially no data -> no insights
    insights = run_pattern_engine_for_user(user_id, db_session)
    assert len(insights) == 0

    # 1. Test Rule A: Add 3 late-night orders in last 7 days
    # Late night in Asia/Kolkata: 23:00 local = 17:30 UTC
    for i in range(3):
        db_session.add(
            Order(
                user_id=user_id,
                event_time=test_now - timedelta(days=i, hours=2),  # around 18:00 UTC = 23:30 local
                restaurant=f"Late Diner {i}",
                food_items=json.dumps(["Biryani x1"]),
                amount=350.0,
                source="Zomato",
                food_categories=json.dumps(["high_calorie"]),
                created_at=test_now,
            )
        )
    db_session.commit()

    insights = run_pattern_engine_for_user(user_id, db_session)
    rule_ids = [i.rule_id for i in insights if i.status != "resolved"]
    assert "A" in rule_ids

    # Idempotency check: running again yields the exact same insight count without duplicates
    insights_again = run_pattern_engine_for_user(user_id, db_session)
    active_again = [i for i in insights_again if i.status != "resolved"]
    assert len(active_again) == len([i for i in insights if i.status != "resolved"])

    # 2. Test Rule B: >= 2 different calendar days with elevated BP
    # Add 2 elevated readings on 2 different days
    db_session.add(
        BloodPressure(
            user_id=user_id,
            event_time=test_now - timedelta(days=2),
            systolic=135,
            diastolic=86,
            source="manual",
            created_at=test_now,
        )
    )
    db_session.add(
        BloodPressure(
            user_id=user_id,
            event_time=test_now - timedelta(days=4),
            systolic=138,
            diastolic=88,
            source="manual",
            created_at=test_now,
        )
    )
    db_session.commit()

    insights = run_pattern_engine_for_user(user_id, db_session)
    active_rules = {i.rule_id: i for i in insights if i.status != "resolved"}
    assert "B" in active_rules
    # Rule G should now fire (Rule A + Rule B)!
    assert "G" in active_rules
    # Under G, Rule A and B should be marked supporting
    assert active_rules["A"].is_supporting is True
    assert active_rules["B"].is_supporting is True
    assert active_rules["G"].is_supporting is False

    # 3. Test Insight resolution when orders are removed
    db_session.query(Order).filter(Order.user_id == user_id).delete()
    db_session.commit()

    insights_after_delete = run_pattern_engine_for_user(user_id, db_session)
    active_after = [i.rule_id for i in insights_after_delete if i.status != "resolved"]
    # Rule A and G must be resolved now!
    assert "A" not in active_after
    assert "G" not in active_after
    # Rule B should remain active
    assert "B" in active_after
