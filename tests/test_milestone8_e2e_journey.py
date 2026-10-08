"""Tests for Milestone 8: Full End-to-End User Journey."""

from datetime import datetime, timedelta, timezone
import io
import zipfile
import pytest
from tests.test_milestone3_typing_pulse import generate_synthetic_ppg


def test_complete_e2e_user_journey(client, db_session, mock_clock):
    """Walkthrough the complete user journey:
    Register -> Consent -> Parse & Save Order -> Add BP -> Record Camera Pulse ->
    Complete Typing Check -> View Insights -> Get Recommendation -> Start & Complete Intervention ->
    Inspect Dashboard & Timeline -> Export Data ZIP -> Wipe Data.
    """
    now = datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc)
    mock_clock.set_time(now)

    # 1. Register User
    res_reg = client.post(
        "/api/auth/register",
        json={
            "name": "Rohan E2E",
            "email": "rohan_e2e@pulse.local",
            "password": "SecurePassword2026!",
            "age_confirmed": True,
        },
    )
    assert res_reg.status_code == 201
    user_id = res_reg.json()["id"]

    # 2. Grant Privacy Consents
    res_consent = client.put(
        "/api/consent",
        json={
            "camera": True,
            "behavior": True,
            "order_data": True,
            "health_data": True,
        },
    )
    assert res_consent.status_code == 200
    assert res_consent.json()["camera"] is True

    # 3. Parse and Save Order (Late night in Asia/Kolkata: 23:45 local = 18:15 UTC)
    receipt_text = "Zomato order from Bawarchi delivered at 11:45 PM. Items: Chicken Biryani x1. Total ₹420."
    res_parse = client.post("/api/orders/parse", json={"pasted_text": receipt_text})
    assert res_parse.status_code == 200
    assert res_parse.json()["restaurant"]["value"] == "Bawarchi"
    assert res_parse.json()["amount"]["value"] == 420.0

    order_time = (now - timedelta(hours=1)).isoformat()
    res_order = client.post(
        "/api/orders",
        json={
            "event_time": order_time,
            "restaurant": "Bawarchi",
            "food_items": ["Chicken Biryani x1"],
            "amount": 420.0,
            "source": "Zomato",
            "food_categories": ["high_calorie"],
        },
    )
    assert res_order.status_code == 201

    # 4. Add Blood Pressure reading
    res_bp = client.post(
        "/api/bp",
        json={
            "systolic": 124,
            "diastolic": 78,
            "pulse_optional": 72,
            "event_time": (now - timedelta(hours=2)).isoformat(),
        },
    )
    assert res_bp.status_code == 201
    assert res_bp.json()["category"] == "normal"

    # 5. Record Camera Pulse (synthetic signal)
    ts, green = generate_synthetic_ppg(bpm=72.0)
    res_pulse = client.post(
        "/api/pulse",
        json={
            "timestamps_ms": ts,
            "green": green,
            "client_uuid": "e2e-pulse-uuid-1",
        },
    )
    assert res_pulse.status_code == 201
    assert abs(res_pulse.json()["bpm"] - 72.0) <= 3.0

    # 6. Complete Typing Check
    res_typing = client.post(
        "/api/behavior",
        json={
            "client_uuid": "e2e-type-uuid-1",
            "duration_seconds": 60.0,
            "keystrokes": 240,
            "backspaces": 6,
            "pause_count": 3,
        },
    )
    assert res_typing.status_code == 201
    assert res_typing.json()["typing_speed_wpm"] > 40.0

    # 7. Start & Complete an Intervention
    res_rec = client.get("/api/interventions/recommendation")
    assert res_rec.status_code == 200

    res_int = client.post(
        "/api/interventions",
        json={
            "trigger_type": "user_started",
            "intervention_type": "breathing_4min",
        },
    )
    assert res_int.status_code == 201
    int_id = res_int.json()["id"]

    res_start = client.post(f"/api/interventions/{int_id}/start")
    assert res_start.status_code == 200

    res_complete = client.post(
        f"/api/interventions/{int_id}/complete",
        json={"actual_seconds": 240, "feeling_after": "calmer"},
    )
    assert res_complete.status_code == 200
    assert res_complete.json()["status"] == "completed"

    # 8. Check Dashboard and Timeline updates
    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 200
    d = res_dash.json()
    assert d["today_state"]["pulse"]["has_data"] is True
    assert d["today_state"]["bp"]["has_data"] is True
    assert d["onboarding"]["completed_count"] >= 3

    res_tl = client.get("/api/timeline")
    assert res_tl.status_code == 200
    events = res_tl.json()["items"]
    event_types = [e["event_type"] for e in events]
    assert "order" in event_types
    assert "bp" in event_types
    assert "pulse" in event_types
    assert "typing" in event_types

    # 9. Export ZIP
    res_export = client.get("/api/export")
    assert res_export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_export.content), "r") as zf:
        assert "orders.csv" in zf.namelist()
        assert "README.txt" in zf.namelist()

    # 10. Data Deletion
    res_del = client.request(
        "DELETE",
        "/api/account/data",
        json={"confirm": "DELETE MY DATA", "password": "SecurePassword2026!"},
    )
    assert res_del.status_code == 200

    # Dashboard should now reflect zero data
    res_dash_after = client.get("/api/dashboard")
    assert res_dash_after.json()["today_state"]["pulse"]["has_data"] is False
    assert res_dash_after.json()["today_state"]["bp"]["has_data"] is False
