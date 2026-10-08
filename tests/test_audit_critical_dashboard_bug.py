"""Audit Test: Critical Dashboard Bug & BP States (Sections 3, 4, 5, 6).
Verifies:
1. Urgent alert is NEVER shown when there are no BP readings (--/--).
2. Explicit states: NO_DATA, NORMAL, ELEVATED, HIGH, URGENT, INVALID.
3. Urgent reading (>180/>120) triggers urgent guidance.
4. Deleting urgent BP reading auto-resolves urgent guidance.
5. No diagnostic claims in descriptions or category labels.
"""

import pytest
from datetime import datetime, timezone
from backend.models import User, BloodPressure, Insight, UserSettings, Consent
from backend.services.bp_classifier import classify_blood_pressure, get_bp_state
from backend.schemas import BPState


def test_bp_classifier_explicit_states():
    # Valid categories
    assert get_bp_state("normal") == BPState.NORMAL.value
    assert get_bp_state("elevated") == BPState.ELEVATED.value
    assert get_bp_state("high") == BPState.HIGH.value
    assert get_bp_state("urgent") == BPState.URGENT.value
    assert get_bp_state(None) == BPState.NO_DATA.value
    assert get_bp_state("unknown") == BPState.INVALID.value

    # Classification boundaries & safety
    cat, label, urgent, _ = classify_blood_pressure(120, 75)
    assert cat == "normal"
    assert not urgent
    assert "diagnosis" not in label.lower()

    cat, label, urgent, _ = classify_blood_pressure(185, 110)
    assert cat == "urgent"
    assert urgent
    assert "hypertension" not in label.lower()  # Section 6: No diagnosis claims

    # Section 5: Rejection of invalid values via validate_bp_reading
    from backend.services.bp_classifier import validate_bp_reading
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validate_bp_reading(80, 120, datetime.now(timezone.utc))  # diastolic >= systolic

    with pytest.raises(HTTPException):
        validate_bp_reading(0, 70, datetime.now(timezone.utc))  # non-positive systolic

    with pytest.raises(HTTPException):
        validate_bp_reading(120, -10, datetime.now(timezone.utc))  # non-positive diastolic

    with pytest.raises(HTTPException):
        validate_bp_reading(120, 80, None)  # missing timestamp


def test_dashboard_never_contradicts_empty_bp(client, authenticated_user):
    """Section 3: If no BP readings exist, urgent alert MUST be hidden."""
    user, headers = authenticated_user

    res = client.get("/api/dashboard", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # BP state must show has_data = False
    assert data["today_state"]["bp"]["has_data"] is False
    assert data["today_state"]["bp"]["systolic"] is None

    # Primary insight must not be URGENT_BP
    if data["primary_insight"]:
        assert data["primary_insight"]["rule_id"] != "URGENT_BP"
        assert data["primary_insight"]["severity"] != "urgent"


def test_dashboard_urgent_bp_lifecycle(client, authenticated_user, db_session):
    """Add urgent BP -> dashboard shows urgent alert.
    Delete BP reading -> dashboard auto-resolves urgent alert.
    """
    user, headers = authenticated_user

    # Enable health data consent
    from backend.consent import update_consent_state
    update_consent_state(user.id, "health_data", True, db_session)

    # 1. Log urgent BP (190/110)
    bp_res = client.post(
        "/api/bp",
        json={
            "systolic": 190,
            "diastolic": 110,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "source": "manual",
        },
        headers=headers,
    )
    assert bp_res.status_code == 201
    bp_data = bp_res.json()
    bp_id = bp_data["id"]
    assert bp_data["category"] == "urgent"
    assert bp_data["state"] == BPState.URGENT.value

    # Dashboard should now show urgent reading and primary insight
    dash_res = client.get("/api/dashboard", headers=headers)
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["today_state"]["bp"]["has_data"] is True
    assert dash_data["today_state"]["bp"]["systolic"] == 190
    assert dash_data["primary_insight"] is not None
    assert dash_data["primary_insight"]["rule_id"] == "URGENT_BP"

    # 2. Delete the urgent BP reading
    del_res = client.delete(f"/api/bp/{bp_id}", headers=headers)
    assert del_res.status_code == 200

    # 3. Dashboard must immediately hide urgent alert and reflect no readings
    dash_res2 = client.get("/api/dashboard", headers=headers)
    assert dash_res2.status_code == 200
    dash_data2 = dash_res2.json()
    assert dash_data2["today_state"]["bp"]["has_data"] is False
    if dash_data2["primary_insight"]:
        assert dash_data2["primary_insight"]["rule_id"] != "URGENT_BP"
