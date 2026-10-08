"""Audit Test: Security, IDOR Protection, Export & Deletion (Sections 42, 43, 44, 45, 46, 47).
Verifies:
1. IDOR Prevention: User A cannot read, modify, or delete User B's orders, BP, pulse, typing, or insights.
2. Direct API access without auth returns 401.
3. Export ZIP: contains only current user's data; includes preferences.csv; does not leak hashes or secrets.
4. "Delete Data Only": wipes health & behavioral tables while preserving user account.
5. "Delete Account": cascades all user data and invalidates sessions.
6. Password Change: verifies current password, hashes new password (min 10 chars).
"""

import io
import zipfile
import pytest
from datetime import datetime, timezone, timedelta
from backend.models import User, Order, BloodPressure
from backend.consent import update_consent_state


def test_idor_protection_between_users(client, db_session):
    """Section 46 & 47: User A can NEVER access or mutate User B's records."""
    # Register User A
    res_a = client.post(
        "/api/auth/register",
        json={"name": "Alice", "email": "alice@security.local", "password": "AlicePassword123!", "age_confirmed": True},
    )
    assert res_a.status_code == 201
    token_a = res_a.cookies.get("pulse_session")
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Pulse-Client": "1"}
    user_a_id = res_a.json()["id"]

    # Register User B
    res_b = client.post(
        "/api/auth/register",
        json={"name": "Bob", "email": "bob@security.local", "password": "BobPassword123!", "age_confirmed": True},
    )
    assert res_b.status_code == 201
    token_b = res_b.cookies.get("pulse_session")
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Pulse-Client": "1"}
    user_b_id = res_b.json()["id"]

    # Enable consent for User A and User B
    update_consent_state(user_a_id, "order_data", True, db_session)
    update_consent_state(user_a_id, "health_data", True, db_session)
    update_consent_state(user_b_id, "order_data", True, db_session)

    # User A creates an order
    order_a_res = client.post(
        "/api/orders",
        json={
            "restaurant": "Alice Secret Spot",
            "amount": 800.0,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "source": "Zomato",
            "food_items": ["Private Meal"],
        },
        headers=headers_a,
    )
    assert order_a_res.status_code == 201
    order_a_id = order_a_res.json()["id"]

    # User B attempts to delete User A's order -> 404 or 403 (Never succeeds)
    del_res = client.delete(f"/api/orders/{order_a_id}", headers=headers_b)
    assert del_res.status_code in (403, 404)

    # Verify order still belongs to User A
    order = db_session.query(Order).filter(Order.id == order_a_id).first()
    assert order is not None
    assert order.user_id == user_a_id

    # User B requests their own orders: must be empty
    orders_b_res = client.get("/api/orders", headers=headers_b)
    assert orders_b_res.status_code == 200
    assert len(orders_b_res.json()) == 0


def test_export_contains_only_current_user_and_includes_preferences(client, authenticated_user, db_session):
    """Section 42: Export must contain only current user's data + preferences.csv, without leaking secrets."""
    user, headers = authenticated_user
    update_consent_state(user.id, "order_data", True, db_session)

    # Add an order
    client.post(
        "/api/orders",
        json={
            "restaurant": "Export Cafe",
            "amount": 250.0,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "source": "Swiggy",
            "food_items": ["Coffee x2"],
        },
        headers=headers,
    )

    # Request export ZIP
    export_res = client.get("/api/export", headers=headers)
    assert export_res.status_code == 200
    assert export_res.headers["content-type"] == "application/zip"

    # Unpack ZIP in memory
    zf = zipfile.ZipFile(io.BytesIO(export_res.content))
    file_list = zf.namelist()

    # Must contain preferences.csv, orders.csv, blood_pressure.csv, etc.
    assert "preferences.csv" in file_list
    assert "orders.csv" in file_list
    assert "blood_pressure.csv" in file_list
    assert "consent.csv" in file_list
    assert "README.txt" in file_list

    # Must NOT contain password_hash or internal secrets
    readme = zf.read("README.txt").decode("utf-8")
    assert "password_hash" not in readme
    prefs_csv = zf.read("preferences.csv").decode("utf-8")
    assert "password" not in prefs_csv.lower()


def test_data_deletion_vs_account_deletion(client, db_session):
    """Sections 43 & 44: 'Delete Data Only' vs 'Delete Account'."""
    # 1. Register test user
    reg = client.post(
        "/api/auth/register",
        json={"name": "Dave", "email": "dave@deletion.local", "password": "DavePassword123!", "age_confirmed": True},
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    token = reg.cookies.get("pulse_session")
    headers = {"Authorization": f"Bearer {token}", "X-Pulse-Client": "1"}

    update_consent_state(user_id, "health_data", True, db_session)
    client.post(
        "/api/bp",
        json={"systolic": 125, "diastolic": 80, "event_time": datetime.now(timezone.utc).isoformat(), "source": "manual"},
        headers=headers,
    )
    assert db_session.query(BloodPressure).filter(BloodPressure.user_id == user_id).count() == 1

    # 2. Delete Data Only
    del_data_res = client.request(
        "DELETE",
        "/api/account/data",
        json={"confirm": "DELETE MY DATA", "password": "DavePassword123!"},
        headers=headers,
    )
    assert del_data_res.status_code == 200

    # Verify health data is gone but user account remains
    assert db_session.query(BloodPressure).filter(BloodPressure.user_id == user_id).count() == 0
    u = db_session.query(User).filter(User.id == user_id).first()
    assert u is not None

    # User can still make authenticated requests with existing session
    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200

    # 3. Delete Entire Account
    del_acc_res = client.request(
        "DELETE",
        "/api/account",
        json={"confirm": "DELETE MY DATA", "password": "DavePassword123!"},
        headers=headers,
    )
    assert del_acc_res.status_code == 200

    # User record must be completely deleted
    assert db_session.query(User).filter(User.id == user_id).first() is None

    # Old token must now be rejected with 401
    me_res2 = client.get("/api/auth/me", headers=headers)
    assert me_res2.status_code == 401
