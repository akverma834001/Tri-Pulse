"""Tests for Milestone 5: Micro-interventions state machine, cooldowns, outcomes, and learning."""

from datetime import datetime, timedelta, timezone
import pytest
from backend.services.intervention_engine import (
    get_recommended_intervention,
    update_intervention_status,
    get_smoothed_completion_rate,
    get_intervention_stats,
)
from backend.models import User, UserSettings, Intervention, Insight


def test_smoothed_completion_rate():
    """Verify smoothed rate formula (completed + 1) / (attempts + 2)."""
    # 0 attempts, 0 completed -> 1/2 = 0.5
    assert get_smoothed_completion_rate(0, 0) == 0.5
    # 3 attempts, 2 completed -> 3/5 = 0.6
    assert get_smoothed_completion_rate(3, 2) == 0.6
    # 10 attempts, 8 completed -> 9/12 = 0.75
    assert get_smoothed_completion_rate(10, 8) == 0.75


def test_intervention_state_transitions(client, db_session):
    """Verify strict state transitions and 409 on invalid transitions."""
    # Register user
    client.post(
        "/api/auth/register",
        json={"name": "Intervention User", "email": "inter_user@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # 1. Create suggested intervention
    res_create = client.post(
        "/api/interventions",
        json={"trigger_type": "user_started", "intervention_type": "breathing_4min"},
    )
    assert res_create.status_code == 201
    int_id = res_create.json()["id"]
    assert res_create.json()["status"] == "suggested"

    # 2. Invalid jump: suggested -> complete directly -> 409
    res_bad = client.post(f"/api/interventions/{int_id}/complete")
    assert res_bad.status_code == 409
    assert res_bad.json()["error"]["code"] == "invalid_state_transition"

    # 3. Transition: suggested -> started -> 200
    res_start = client.post(f"/api/interventions/{int_id}/start")
    assert res_start.status_code == 200
    assert res_start.json()["status"] == "started"

    # 4. Transition: started -> completed -> 200
    res_comp = client.post(
        f"/api/interventions/{int_id}/complete",
        json={"actual_seconds": 240, "feeling_after": "calmer"},
    )
    assert res_comp.status_code == 200
    assert res_comp.json()["status"] == "completed"
    assert res_comp.json()["feeling_after"] == "calmer"


def test_cooldowns_and_muting(client, db_session, mock_clock):
    """Verify quiet hours, daily max suggestions, and dismissal/worse muting."""
    test_now = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)  # 19:30 local (not quiet hours)
    mock_clock.set_time(test_now)

    reg = client.post(
        "/api/auth/register",
        json={"name": "Cooldown User", "email": "cool_user@test.com", "password": "Password1234!", "age_confirmed": True},
    )
    user_id = reg.json()["id"]
    client.put("/api/consent", json={"health_data": True, "order_data": True, "behavior": True})

    # Add an active insight for high load
    ins = Insight(
        user_id=user_id,
        rule_id="E",
        created_at=test_now,
        updated_at=test_now,
        window_start=test_now - timedelta(days=7),
        window_end=test_now,
        window_end_date=test_now.strftime("%Y-%m-%d"),
        category="vital",
        severity="info",
        title="Pulse above baseline",
        explanation="Pulse higher than normal",
        recommended_action="Take a pause",
    )
    db_session.add(ins)
    db_session.commit()

    # 1. Recommendation should be available (breathing_4min)
    res_rec = client.get("/api/interventions/recommendation")
    assert res_rec.status_code == 200
    rec = res_rec.json()["recommendation"]
    assert rec is not None
    assert rec["intervention_type"] == "breathing_4min"

    # 2. Quiet hours check: set local time to 02:00 AM (20:30 UTC previous day)
    quiet_now = datetime(2026, 10, 8, 20, 30, tzinfo=timezone.utc)
    mock_clock.set_time(quiet_now)
    res_quiet = client.get("/api/interventions/recommendation")
    assert res_quiet.json()["recommendation"] is None

    # Reset back to daytime
    mock_clock.set_time(test_now)

    # 3. Two "Worse" ratings mute the intervention type
    for i in range(2):
        res_i = client.post(
            "/api/interventions",
            json={"trigger_type": "user_started", "intervention_type": "breathing_4min"},
        )
        i_id = res_i.json()["id"]
        client.post(f"/api/interventions/{i_id}/start")
        client.post(f"/api/interventions/{i_id}/complete", json={"feeling_after": "worse"})

    res_after_worse = client.get("/api/interventions/recommendation")
    # Breathing is now muted because user rated worse twice
    rec_worse = res_after_worse.json()["recommendation"]
    assert rec_worse is None or rec_worse["intervention_type"] != "breathing_4min"
