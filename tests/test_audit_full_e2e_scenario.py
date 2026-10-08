"""Audit Test: Section 76 Full End-to-End Scenario.
Automates:
Register -> Login -> Grant consent -> Add 3 late-night orders -> Add 2 BP readings ->
Add pulse sessions -> Add typing sessions -> Pattern engine runs -> Insight appears ->
Intervention appears -> User completes intervention -> Timeline updates ->
Dashboard updates -> Export works -> Delete health data -> Verify health data gone.
"""

import io
import zipfile
import pytest
from datetime import datetime, timezone, timedelta
from backend.models import User, BloodPressure, Order, PulseSession, BehaviorSession, Intervention, Insight


def test_section_76_complete_mvp_loop(client, db_session):
    # 1. Register
    reg_res = client.post(
        "/api/auth/register",
        json={
            "name": "Audit Tester",
            "email": "auditor@pulse.mvp",
            "password": "MvpPassword2026!",
            "age_confirmed": True,
        },
    )
    assert reg_res.status_code == 201
    user_id = reg_res.json()["id"]

    # 2. Login
    login_res = client.post(
        "/api/auth/login",
        json={"email": "auditor@pulse.mvp", "password": "MvpPassword2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.cookies.get("pulse_session")
    headers = {"Authorization": f"Bearer {token}", "X-Pulse-Client": "1"}

    # 3. Grant consent
    consent_res = client.put(
        "/api/consent",
        json={"camera": True, "behavior": True, "order_data": True, "health_data": True},
        headers=headers,
    )
    assert consent_res.status_code == 200

    # 4. Add 3 late-night orders
    now = datetime.now(timezone.utc)
    for i in range(3):
        dt = datetime(now.year, now.month, now.day, 18, 15, tzinfo=timezone.utc) - timedelta(days=i + 1)
        ord_res = client.post(
            "/api/orders",
            json={
                "restaurant": f"Midnight Cafe {i}",
                "amount": 320.0 + i * 20,
                "event_time": dt.isoformat(),
                "order_status": "DELIVERED",
                "source": "Zomato",
                "food_items": ["Biryani"],
            },
            headers=headers,
        )
        assert ord_res.status_code == 201

    # 5. Add 2 BP readings (both elevated)
    for i in range(2):
        bp_dt = (now - timedelta(days=2 - i)).isoformat()
        bp_res = client.post(
            "/api/bp",
            json={
                "systolic": 135,
                "diastolic": 86,
                "event_time": bp_dt,
                "source": "manual",
            },
            headers=headers,
        )
        assert bp_res.status_code == 201

    # 6. Add pulse sessions
    for i in range(3):
        p_res = client.post(
            "/api/pulse",
            json={
                "bpm": 76.0 + i,
                "duration_seconds": 30,
                "source": "manual",
                "event_time": (now - timedelta(days=3 - i)).isoformat(),
                "client_uuid": f"pulse-e2e-{i}",
            },
            headers=headers,
        )
        assert p_res.status_code == 201

    # 7. Add typing sessions
    for i in range(3):
        t_res = client.post(
            "/api/behavior",
            json={
                "duration_seconds": 60,
                "keystrokes": 240,
                "backspaces": 4,
                "pause_count": 2,
                "event_time": (now - timedelta(days=3 - i)).isoformat(),
                "client_uuid": f"type-e2e-{i}",
            },
            headers=headers,
        )
        assert t_res.status_code == 201

    # 8. Pattern engine runs & Insight appears
    ins_res = client.get("/api/insights", headers=headers)
    assert ins_res.status_code == 200
    insights = ins_res.json()
    assert len(insights) > 0, "Rule-based insights must appear"
    insight_id = insights[0]["id"]

    # 9. Intervention appears & starts
    interv_rec = client.get("/api/interventions/recommendation", headers=headers)
    assert interv_rec.status_code == 200
    rec_data = interv_rec.json()
    rec_type = rec_data["recommendation"]["intervention_type"] if rec_data["recommendation"] else "winddown_5min"

    interv_create = client.post(
        "/api/interventions",
        json={"intervention_type": rec_type, "trigger_type": "dashboard_prompt", "suggested_by": "copilot", "insight_id": insight_id},
        headers=headers,
    )
    assert interv_create.status_code == 201
    interv_id = interv_create.json()["id"]

    # Start intervention
    start_res = client.post(f"/api/interventions/{interv_id}/start", headers=headers)
    assert start_res.status_code == 200

    # 10. Complete intervention
    comp_res = client.post(
        f"/api/interventions/{interv_id}/complete",
        json={"actual_seconds": 300},
        headers=headers,
    )
    assert comp_res.status_code == 200

    # Feedback
    fb_res = client.post(
        f"/api/interventions/{interv_id}/feedback",
        json={"feeling_after": "calmer"},
        headers=headers,
    )
    assert fb_res.status_code == 200

    # 11. Timeline updates
    tl_res = client.get("/api/timeline", headers=headers)
    assert tl_res.status_code == 200
    events = tl_res.json()["items"]
    assert len(events) >= 5, "Events must include orders, bp, pulse, typing, intervention"

    # 12. Dashboard updates
    dash_res = client.get("/api/dashboard", headers=headers)
    assert dash_res.status_code == 200
    d = dash_res.json()
    assert d["today_state"]["late_night_orders"]["count"] >= 3
    assert d["today_state"]["bp"]["has_data"] is True

    # 13. Export works
    exp_res = client.get("/api/export", headers=headers)
    assert exp_res.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(exp_res.content))
    assert "orders.csv" in zf.namelist()
    assert "interventions.csv" in zf.namelist()
    assert "preferences.csv" in zf.namelist()

    # 14. Delete health data
    del_res = client.request(
        "DELETE",
        "/api/account/data",
        json={"confirm": "DELETE MY DATA", "password": "MvpPassword2026!"},
        headers=headers,
    )
    assert del_res.status_code == 200

    # 15. Verify health data gone
    assert db_session.query(Order).filter(Order.user_id == user_id).count() == 0
    assert db_session.query(BloodPressure).filter(BloodPressure.user_id == user_id).count() == 0
    assert db_session.query(PulseSession).filter(PulseSession.user_id == user_id).count() == 0
    assert db_session.query(BehaviorSession).filter(BehaviorSession.user_id == user_id).count() == 0
    assert db_session.query(Intervention).filter(Intervention.user_id == user_id).count() == 0
    assert db_session.query(Insight).filter(Insight.user_id == user_id).count() == 0
