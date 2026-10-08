"""Routes for order ingestion, parsing, updates, and deletion."""

import json
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, UserSettings, Order
from backend.schemas import (
    OrderParseRequest,
    OrderParseResponse,
    OrderCreate,
    OrderUpdate,
    OrderResponse,
)
from backend.auth import get_current_user
from backend.consent import require_consents
from backend.services.order_parser import parse_order_text, is_late_night_time
from backend.services.food_classifier import classify_food_items
from backend.services.event_service import record_timeline_event, delete_timeline_event
from backend.clock import get_clock

router = APIRouter(prefix="/api/orders", tags=["Orders"])


def _to_order_response(order: Order, settings: Optional[UserSettings]) -> OrderResponse:
    tz = settings.timezone if settings else "Asia/Kolkata"
    ln_start = settings.late_night_start if settings else "22:30"
    ln_end = settings.late_night_end if settings else "05:00"

    is_ln = is_late_night_time(order.event_time, ln_start, ln_end, tz)
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        event_time=order.event_time,
        restaurant=order.restaurant,
        food_items=order.get_food_items(),
        amount=order.amount,
        source=order.source,
        food_categories=order.get_food_categories(),
        date_assumed=order.date_assumed,
        parse_confidence=order.parse_confidence,
        is_late_night=is_ln,
        created_at=order.created_at,
    )


@router.post("/parse", response_model=OrderParseResponse)
def parse_order(
    data: OrderParseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Parse pasted order receipt in memory without saving."""
    require_consents(user, db, ["order_data"])

    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    tz = settings.timezone if settings else "Asia/Kolkata"
    ln_start = settings.late_night_start if settings else "22:30"
    ln_end = settings.late_night_end if settings else "05:00"

    result = parse_order_text(
        data.pasted_text,
        user_tz_name=tz,
        late_night_start=ln_start,
        late_night_end=ln_end,
    )
    return result


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    data: OrderCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save user-confirmed order, trigger pipeline recomputation, and record event."""
    require_consents(user, db, ["order_data"])

    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    event_dt = data.event_time
    if event_dt.tzinfo is None:
        event_dt = event_dt.replace(tzinfo=timezone.utc)

    # Duplicate check: same (user, event_time, amount, restaurant)
    existing = (
        db.query(Order)
        .filter(
            Order.user_id == user.id,
            Order.event_time == event_dt,
            Order.amount == data.amount,
            Order.restaurant == data.restaurant,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "duplicate_order", "message": "This order looks already saved."},
        )

    # Derive food categories if empty
    categories = data.food_categories
    if not categories and data.food_items:
        categories = classify_food_items(data.food_items)

    order = Order(
        user_id=user.id,
        event_time=event_dt,
        restaurant=data.restaurant or "unknown",
        food_items=json.dumps(data.food_items or []),
        amount=data.amount,
        source=data.source or "unknown",
        food_categories=json.dumps(categories or []),
        date_assumed=data.date_assumed,
        parse_confidence=data.parse_confidence,
        created_at=get_clock().now(),
    )
    db.add(order)
    db.flush()  # get order.id

    tz = settings.timezone if settings else "Asia/Kolkata"
    ln_start = settings.late_night_start if settings else "22:30"
    ln_end = settings.late_night_end if settings else "05:00"
    is_ln = is_late_night_time(order.event_time, ln_start, ln_end, tz)

    # Timeline event
    record_timeline_event(
        db=db,
        user_id=user.id,
        event_time=order.event_time,
        event_type="order",
        ref_table="orders",
        ref_id=order.id,
        summary={
            "title": f"Order from {order.restaurant}",
            "amount": order.amount,
            "items_count": len(data.food_items),
            "late_night": is_ln,
        },
    )

    db.commit()
    db.refresh(order)

    # Pipeline hook: trigger pattern re-run
    _trigger_pipeline(user.id, db)

    return _to_order_response(order, settings)


@router.get("", response_model=List[OrderResponse])
def get_orders(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    orders = (
        db.query(Order)
        .filter(Order.user_id == user.id)
        .order_by(Order.event_time.desc())
        .all()
    )
    return [_to_order_response(o, settings) for o in orders]


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    data: OrderUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_consents(user, db, ["order_data"])
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "order_not_found", "message": "Order not found."},
        )

    if data.restaurant is not None:
        order.restaurant = data.restaurant
    if data.amount is not None:
        order.amount = data.amount
    if data.event_time is not None:
        order.event_time = data.event_time.replace(tzinfo=timezone.utc) if data.event_time.tzinfo is None else data.event_time
    if data.food_items is not None:
        order.food_items = json.dumps(data.food_items)
        if data.food_categories is None:
            order.food_categories = json.dumps(classify_food_items(data.food_items))
    if data.food_categories is not None:
        order.food_categories = json.dumps(data.food_categories)

    db.commit()
    db.refresh(order)

    # Pipeline hook
    _trigger_pipeline(user.id, db)

    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    return _to_order_response(order, settings)


@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "order_not_found", "message": "Order not found."},
        )

    delete_timeline_event(db, user.id, "orders", order.id)
    db.delete(order)
    db.commit()

    # Re-run pipeline after deletion
    _trigger_pipeline(user.id, db)

    return {"message": "Order deleted successfully."}


def _trigger_pipeline(user_id: int, db: Session):
    """Pipeline hook: recompute baselines and pattern engine if available."""
    try:
        from backend.services.pattern_engine import run_pattern_engine_for_user
        run_pattern_engine_for_user(user_id, db)
    except ImportError:
        pass
