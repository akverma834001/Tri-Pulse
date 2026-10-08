"""Tests for Milestones 6 & 7: Dashboard, Timeline, Export, Deletion, and Demo Mode."""

import io
import zipfile
from datetime import datetime, timedelta, timezone
import pytest
from backend.models import (
    User,
    Order,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Intervention,
    Insight,
    Event,
)
from backend.services.export_service import sanitize_csv_cell


def test_csv_formula_injection_neutralization():
    """Verify cells starting with dangerous symbols are sanitized with a single quote prefix."""
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("+49123") == "'+49123"
    assert sanitize_csv_cell("-12.5") == "'-12.5"
    assert sanitize_csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert sanitize_csv_cell("\tTab") == "'\tTab"
    assert sanitize_csv_cell("Normal Text") == "Normal Text"
    assert sanitize_csv_cell(123) == "123"


def test_dashboard_and_timeline(client, db_session):
    """Test dashboard aggregation, onboarding checklist, and timeline pagination."""
    # Register user
    client.post(
        "/api/auth/register",
        json={"name": "Dash User", "email": "dash_user@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # 1. Initial dashboard empty state
    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 200
    d_data = res_dash.json()
    assert d_data["today_state"]["pulse"]["has_data"] is False
    assert d_data["onboarding"]["completed_count"] == 0

    # 2. Grant consent -> Onboarding step 1 completes
    client.put("/api/consent", json={"health_data": True, "order_data": True})
    res_dash2 = client.get("/api/dashboard")
    assert res_dash2.json()["onboarding"]["steps"][0]["completed"] is True

    # 3. Add BP reading -> Onboarding step 2 completes, timeline updates
    client.post("/api/bp", json={"systolic": 120, "diastolic": 80})
    res_dash3 = client.get("/api/dashboard")
    assert res_dash3.json()["onboarding"]["steps"][1]["completed"] is True
    assert res_dash3.json()["today_state"]["bp"]["has_data"] is True

    # Check timeline
    res_tl = client.get("/api/timeline")
    assert res_tl.status_code == 200
    items = res_tl.json()["items"]
    assert len(items) >= 1
    assert items[0]["ref_table"] == "blood_pressure"


def test_export_and_deletion(client, db_session):
    """Test ZIP export and transactional data deletion without touching other users."""
    # Register User A
    client.post(
        "/api/auth/register",
        json={"name": "User A", "email": "user_a@test.com", "password": "Password1234!", "age_confirmed": True},
    )
    client.put("/api/consent", json={"health_data": True, "order_data": True})
    client.post("/api/bp", json={"systolic": 122, "diastolic": 78})

    # Register User B
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"name": "User B", "email": "user_b@test.com", "password": "Password1234!", "age_confirmed": True},
    )
    client.put("/api/consent", json={"health_data": True})
    client.post("/api/bp", json={"systolic": 130, "diastolic": 85})

    # Export for User B
    res_exp = client.get("/api/export")
    assert res_exp.status_code == 200
    assert res_exp.headers["content-type"] == "application/zip"

    zip_bytes = io.BytesIO(res_exp.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        file_list = zf.namelist()
        assert "orders.csv" in file_list
        assert "blood_pressure.csv" in file_list
        assert "README.txt" in file_list

        bp_csv = zf.read("blood_pressure.csv").decode("utf-8")
        assert "130" in bp_csv
        # Must NOT contain User A's data (122)
        assert "122" not in bp_csv

    # Single table export
    res_single = client.get("/api/export?table=blood_pressure")
    assert res_single.status_code == 200
    assert "text/csv" in res_single.headers["content-type"]

    # Delete User B's data
    res_del_data = client.request(
        "DELETE",
        "/api/account/data",
        json={"confirm": "DELETE MY DATA", "password": "Password1234!"},
    )
    assert res_del_data.status_code == 200

    # User B's BP should be 0 rows now
    user_b = db_session.query(User).filter(User.email == "user_b@test.com").first()
    assert db_session.query(BloodPressure).filter(BloodPressure.user_id == user_b.id).count() == 0

    # User A's data must remain untouched!
    user_a = db_session.query(User).filter(User.email == "user_a@test.com").first()
    assert db_session.query(BloodPressure).filter(BloodPressure.user_id == user_a.id).count() == 1


def test_demo_mode_dataset_and_dashboard_values(client, db_session, mock_clock):
    """Verify Section 7.13 Demo Mode: exact metrics and real pipeline execution."""
    test_now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    mock_clock.set_time(test_now)

    res_load = client.post("/api/demo/load")
    assert res_load.status_code == 200
    assert res_load.json()["email"] == "demo@pulse.local"
    assert res_load.json()["is_demo"] is True

    # Inspect dashboard
    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 200
    d = res_dash.json()

    # Section 7.13 Acceptance criteria:
    # 1. Late night orders: exactly 4 in last 7 days
    assert d["today_state"]["late_night_orders"]["count"] == 4

    # 2. Circular average order time: 23:41
    assert d["today_state"]["late_night_orders"]["avg_time"] == "23:41"

    # 3. Latest BP: exactly 138/88
    assert d["today_state"]["bp"]["systolic"] == 138
    assert d["today_state"]["bp"]["diastolic"] == 88

    # 4. Average pulse: 82 BPM (+11% vs baseline 74)
    assert d["today_state"]["pulse"]["bpm"] == 82.0 or round(d["baseline_progress"][0]["current_value"]) == 82

    # 5. Typing deviation: -15%
    typing_item = next(b for b in d["baseline_progress"] if b["signal"] == "typing_wpm")
    assert round(typing_item["deviation_percent"]) == -15

    # 6. Primary insight: Combined routine (Rule G)
    assert d["primary_insight"] is not None
    assert d["primary_insight"]["rule_id"] == "G"

    # 7. Recommended action: wind-down
    assert d["recommended_action"] is not None
    assert d["recommended_action"]["intervention_type"] == "winddown_5min"
    assert "wind-down" in d["recommended_action"]["title"].lower() or "wind-down" in d["primary_insight"]["recommended_action"].lower()
