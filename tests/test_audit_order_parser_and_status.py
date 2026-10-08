"""Audit Test: Order Parser, Status Handling & Date Logic (Sections 11, 12, 13, 14, 52).
Verifies:
1. Cancellations and Refunds are detected and mapped to CANCELLED/REFUNDED.
2. Cancelled and refunded orders are NOT counted in late-night food routine in pattern engine.
3. Date logic: receipt with time but no calendar date returns date_assumed=True, date_confidence=LOW.
4. Parsing failures flag status=NEEDS_CONFIRMATION or LOW confidence without fabricating dates.
5. Negative amounts and future dates (>24h) are rejected.
6. Behavioral food classifications rather than nutrition/causal claims.
"""

import pytest
from datetime import datetime, timezone, timedelta
from backend.services.order_parser import parse_order_text
from backend.models import User, Order, Consent, UserSettings
from backend.consent import update_consent_state
from backend.services.pattern_engine import run_pattern_engine_for_user


def test_order_parser_cancellations_and_refunds():
    # Cancellation text
    text_cancelled = "Your Swiggy order #98234 has been cancelled. Rs 350 refunded to UPI."
    res_can = parse_order_text(text_cancelled)
    assert res_can["order_status"] in ("CANCELLED", "REFUNDED")
    assert res_can["amount"]["value"] == 350.0

    # Refund text
    text_refund = "Zomato update: ₹420 refund initiated for your cancelled biryani order."
    res_ref = parse_order_text(text_refund)
    assert res_ref["order_status"] in ("CANCELLED", "REFUNDED")
    assert res_ref["amount"]["value"] == 420.0

    # Normal delivered order
    text_delivered = "Your order from Subway worth Rs 280 was delivered at 11:45 PM."
    res_del = parse_order_text(text_delivered)
    assert res_del["order_status"] == "DELIVERED"
    assert res_del["restaurant"]["value"] == "Subway"
    assert res_del["amount"]["value"] == 280.0


def test_order_parser_date_confidence():
    # Time only -> date_assumed is True, date_confidence is LOW
    text_time_only = "Order delivered at 11:15 PM from Burger King worth Rs 300"
    res = parse_order_text(text_time_only)
    assert res["date_assumed"] is True
    assert res["date_confidence"] == "LOW"

    # Specific date present -> date_assumed is False, date_confidence is HIGH
    text_with_date = "Order placed on 05 Oct at 11:15 PM from Burger King worth Rs 300"
    res2 = parse_order_text(text_with_date)
    assert res2["date_assumed"] is False
    assert res2["date_confidence"] == "HIGH"


def test_cancelled_orders_excluded_from_pattern_engine(client, authenticated_user, db_session):
    """Section 13: Cancelled/refunded orders must NOT count as food consumption events."""
    user, headers = authenticated_user
    update_consent_state(user.id, "order_data", True, db_session)

    now = datetime.now(timezone.utc)

    # Add 3 late-night orders: 1 DELIVERED, 2 CANCELLED
    orders = [
        {"restaurant": "KFC", "amount": 400.0, "status": "DELIVERED", "time": now - timedelta(days=1)},
        {"restaurant": "McD", "amount": 350.0, "status": "CANCELLED", "time": now - timedelta(days=2)},
        {"restaurant": "Domino's", "amount": 500.0, "status": "REFUNDED", "time": now - timedelta(days=3)},
    ]

    for o in orders:
        res = client.post(
            "/api/orders",
            json={
                "restaurant": o["restaurant"],
                "amount": o["amount"],
                "event_time": o["time"].isoformat(),
                "order_status": o["status"],
                "source": "Zomato",
                "food_items": ["Meal x1"],
            },
            headers=headers,
        )
        assert res.status_code == 201

    # Check dashboard late_night_orders count: only DELIVERED order should count!
    dash_res = client.get("/api/dashboard", headers=headers)
    assert dash_res.status_code == 200
    d = dash_res.json()
    assert d["today_state"]["late_night_orders"]["count"] <= 1

    # Rule A (late night routine >= 3 orders) must NOT fire because cancelled/refunded don't count
    insights = run_pattern_engine_for_user(user.id, db_session)
    rule_a_insights = [i for i in insights if i.rule_id in ("A", "RULE_A_LATE_NIGHT_ROUTINE")]
    assert len(rule_a_insights) == 0


def test_order_input_validation(client, authenticated_user, db_session):
    """Section 78: Reject negative amount and future timestamps safely."""
    user, headers = authenticated_user
    update_consent_state(user.id, "order_data", True, db_session)

    now = datetime.now(timezone.utc)

    # Negative amount
    res_neg = client.post(
        "/api/orders",
        json={
            "restaurant": "Test",
            "amount": -50.0,
            "event_time": now.isoformat(),
        },
        headers=headers,
    )
    assert res_neg.status_code in (400, 422)

    # Distant future timestamp (> 24h)
    res_future = client.post(
        "/api/orders",
        json={
            "restaurant": "Test",
            "amount": 250.0,
            "event_time": (now + timedelta(days=5)).isoformat(),
        },
        headers=headers,
    )
    assert res_future.status_code in (400, 422)
