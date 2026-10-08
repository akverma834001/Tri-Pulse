"""Event service for managing timeline events in the same transaction as records."""

import json
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from backend.models import Event
from backend.clock import get_clock


def record_timeline_event(
    db: Session,
    user_id: int,
    event_time: datetime,
    event_type: str,
    ref_table: str,
    ref_id: int,
    summary: Dict[str, Any],
) -> Event:
    """Create a timeline event record."""
    now = get_clock().now()
    event_obj = Event(
        user_id=user_id,
        event_time=event_time,
        event_type=event_type,
        ref_table=ref_table,
        ref_id=ref_id,
        summary_json=json.dumps(summary),
        created_at=now,
    )
    db.add(event_obj)
    return event_obj


def delete_timeline_event(
    db: Session,
    user_id: int,
    ref_table: str,
    ref_id: int,
) -> None:
    """Delete the associated timeline event for a record."""
    db.query(Event).filter(
        Event.user_id == user_id,
        Event.ref_table == ref_table,
        Event.ref_id == ref_id,
    ).delete()
