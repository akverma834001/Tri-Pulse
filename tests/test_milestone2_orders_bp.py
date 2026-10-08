"""Tests for Milestone 2: Orders & Blood Pressure Ingestion, Parsing, Validation, and Classification."""

from datetime import datetime, timedelta, timezone
import pytest
from backend.services.order_parser import parse_order_text, is_late_night_time
from backend.services.food_classifier import classify_food_items
from backend.services.bp_classifier import classify_blood_pressure, validate_bp_reading
from backend.models import Event, Insight


def test_food_classifier():
    """Verify keyword mapping for behavioral food classification."""
    assert "high_calorie" in classify_food_items(["Chicken Biryani x1"])
    assert "fast_food" in classify_food_items(["Farmhouse Pizza"])
    assert "fried" in classify_food_items(["French Fries", "Paneer Pakora"])
    assert "sugary" in classify_food_items(["Gulab Jamun", "Chocolate Cake"])
    assert "balanced" in classify_food_items(["Dal Tadka", "Roti", "Green Salad"])
    assert classify_food_items(["Water bottle"]) == ["unknown"]


def test_order_parser_fixtures():
    """Verify order parser with realistic text fixtures."""
    # 1. Zomato with late night time
    t1 = "Zomato: Order from Meghana Foods has been delivered. Items: Chicken Biryani x1, Gulab Jamun x2. Total: ₹450.00 at 11:48 PM on 12 Oct 2026."
    res1 = parse_order_text(t1)
    assert res1["source"]["value"] == "Zomato"
    assert "Meghana Foods" in res1["restaurant"]["value"]
    assert res1["amount"]["value"] == 450.0
    assert "Chicken Biryani x1" in res1["food_items"]["value"]
    assert res1["delivery_time"]["value"] == "23:48"
    assert res1["is_late_night"] is True
    assert res1["date_assumed"] is False

    # 2. Swiggy daytime with Rs. currency
    t2 = "Swiggy order delivered from Chai Point. 2 x Veg Thali. Bill amount Rs. 320 at 1:15 PM on today."
    res2 = parse_order_text(t2)
    assert res2["source"]["value"] == "Swiggy"
    assert "Chai Point" in res2["restaurant"]["value"]
    assert res2["amount"]["value"] == 320.0
    assert res2["delivery_time"]["value"] == "13:15"
    assert res2["is_late_night"] is False

    # 3. Currency with commas and decimals
    t3 = "Your order from Barbeque Nation worth ₹1,240.50 was delivered at 8 PM."
    res3 = parse_order_text(t3)
    assert res3["amount"]["value"] == 1240.50
    assert "Barbeque Nation" in res3["restaurant"]["value"]
    assert res3["delivery_time"]["value"] == "20:00"

    # 4. Past midnight (00:02) - late night
    t4 = "Blinkit order from Midnight Bites delivered at 00:02."
    res4 = parse_order_text(t4)
    assert res4["is_late_night"] is True

    # 5. Missing date -> date assumed
    t5 = "Order from Domino's has Pizza x1 for ₹499."
    res5 = parse_order_text(t5)
    assert res5["date_assumed"] is True
    assert res5["restaurant"]["value"] == "Domino's"

    # 6. Unknown platform & missing amount
    t6 = "Takeaway from Corner Cafe delivered at 10:30 PM."
    res6 = parse_order_text(t6)
    assert res6["source"]["value"] == "unknown"
    assert res6["amount"]["found"] is False


def test_late_night_window_boundaries():
    """Verify exact boundaries: 22:29 False, 22:30 True, 04:59 True, 05:00 False."""
    # Local timezone Asia/Kolkata is UTC+5:30
    tz = "Asia/Kolkata"

    # 22:29 local = 16:59 UTC
    dt_2229 = datetime(2026, 10, 8, 16, 59, tzinfo=timezone.utc)
    assert is_late_night_time(dt_2229, "22:30", "05:00", tz) is False

    # 22:30 local = 17:00 UTC
    dt_2230 = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)
    assert is_late_night_time(dt_2230, "22:30", "05:00", tz) is True

    # 04:59 local = 23:29 UTC (previous day)
    dt_0459 = datetime(2026, 10, 8, 23, 29, tzinfo=timezone.utc)
    assert is_late_night_time(dt_0459, "22:30", "05:00", tz) is True

    # 05:00 local = 23:30 UTC
    dt_0500 = datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)
    assert is_late_night_time(dt_0500, "22:30", "05:00", tz) is False


def test_order_endpoints(client, db_session):
    """Test parse preview, consent enforcement, save, duplicate 409, and delete."""
    # Register user
    client.post(
        "/api/auth/register",
        json={"name": "Rohan", "email": "rohan_orders@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # 1. Parse without consent -> 403
    res_no_consent = client.post(
        "/api/orders/parse",
        json={"pasted_text": "Zomato order from Meghana Foods at 11:30 PM for Rs. 500"},
    )
    assert res_no_consent.status_code == 403
    assert res_no_consent.json()["error"]["code"] == "consent_required"

    # Grant order_data consent
    client.put("/api/consent", json={"order_data": True})

    # 2. Parse with consent -> 200
    res_parse = client.post(
        "/api/orders/parse",
        json={"pasted_text": "Zomato order from Meghana Foods at 11:30 PM for Rs. 500"},
    )
    assert res_parse.status_code == 200
    assert res_parse.json()["restaurant"]["value"] == "Meghana Foods"

    # 3. Create order
    order_payload = {
        "event_time": datetime(2026, 10, 8, 18, 0, tzinfo=timezone.utc).isoformat(),
        "restaurant": "Meghana Foods",
        "food_items": ["Chicken Biryani x1"],
        "amount": 500.0,
        "source": "Zomato",
        "food_categories": ["high_calorie"],
    }
    res_create = client.post("/api/orders", json=order_payload)
    assert res_create.status_code == 201
    order_id = res_create.json()["id"]

    # Verify timeline event was created
    ev = db_session.query(Event).filter(Event.ref_table == "orders", Event.ref_id == order_id).first()
    assert ev is not None
    assert "Meghana Foods" in ev.summary_json

    # Duplicate order -> 409
    res_dup = client.post("/api/orders", json=order_payload)
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "duplicate_order"

    # Delete order
    res_del = client.delete(f"/api/orders/{order_id}")
    assert res_del.status_code == 200

    # Verify timeline event also deleted
    ev_after = db_session.query(Event).filter(Event.ref_table == "orders", Event.ref_id == order_id).first()
    assert ev_after is None


def test_bp_classification_and_endpoints(client, db_session):
    """Test blood pressure classification categories, boundaries, validation, and API routes."""
    # Precedence & category tests
    cat, _, urgent, _ = classify_blood_pressure(120, 75)
    assert cat == "normal" and not urgent

    cat, _, urgent, _ = classify_blood_pressure(130, 79)
    assert cat == "elevated" and not urgent

    cat, _, urgent, _ = classify_blood_pressure(129, 80)
    assert cat == "elevated" and not urgent

    cat, _, urgent, _ = classify_blood_pressure(140, 89)
    assert cat == "above_range" and not urgent

    cat, _, urgent, _ = classify_blood_pressure(181, 80)
    assert cat == "urgent" and urgent

    cat, _, urgent, _ = classify_blood_pressure(120, 121)
    assert cat == "urgent" and urgent

    # Register user
    client.post(
        "/api/auth/register",
        json={"name": "Rohan BP", "email": "rohan_bp@test.com", "password": "Password1234!", "age_confirmed": True},
    )

    # POST without health_data consent -> 403
    bp_data = {"systolic": 125, "diastolic": 78}
    res_no_consent = client.post("/api/bp", json=bp_data)
    assert res_no_consent.status_code == 403

    # Grant health_data consent
    client.put("/api/consent", json={"health_data": True})

    # Invalid BP: systolic <= diastolic -> 422
    res_invalid = client.post("/api/bp", json={"systolic": 80, "diastolic": 90})
    assert res_invalid.status_code == 422

    # Normal reading
    res_valid = client.post("/api/bp", json=bp_data)
    assert res_valid.status_code == 201
    bp_id = res_valid.json()["id"]
    assert res_valid.json()["category"] == "normal"

    # Duplicate within 2 mins -> 409
    res_dup = client.post("/api/bp", json=bp_data)
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "duplicate_reading"

    # Urgent reading -> urgent_alert True and Insight created
    urgent_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    res_urgent = client.post(
        "/api/bp",
        json={"systolic": 185, "diastolic": 95, "event_time": urgent_time},
    )
    assert res_urgent.status_code == 201
    assert res_urgent.json()["urgent_alert"] is True
    assert res_urgent.json()["urgent_message"] is not None

    # Check urgent insight in DB
    ins = db_session.query(Insight).filter(Insight.rule_id == "URGENT_BP").first()
    assert ins is not None
    assert ins.severity == "urgent"
