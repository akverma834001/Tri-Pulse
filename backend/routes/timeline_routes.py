"""Routes for timeline events history."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, UserSettings, Event
from backend.schemas import TimelineResponse, TimelineItem
from backend.auth import get_current_user
from backend.clock import get_clock, to_local, ensure_utc

router = APIRouter(prefix="/api/timeline", tags=["Timeline"])


@router.get("", response_model=TimelineResponse)
def get_timeline(
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = Query(None, description="ISO timestamp cursor for pagination"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    tz = settings.timezone if settings else "Asia/Kolkata"

    query = db.query(Event).filter(Event.user_id == user.id)

    if before:
        try:
            cursor_dt = datetime.fromisoformat(before)
            cursor_dt = ensure_utc(cursor_dt)
            query = query.filter(Event.event_time < cursor_dt)
        except Exception:
            pass

    records = query.order_by(Event.event_time.desc()).limit(limit + 1).all()
    has_more = len(records) > limit
    results = records[:limit]

    items = []
    for ev in results:
        ev_utc = ensure_utc(ev.event_time)
        ev_local = to_local(ev_utc, tz)
        time_str = ev_local.strftime("%I:%M %p")
        date_str = ev_local.strftime("%b %d, %Y")

        summary_dict = ev.get_summary()
        title = summary_dict.get("title", f"Event: {ev.event_type.title()}")
        details = summary_dict

        can_del = ev.ref_table in ("orders", "blood_pressure", "pulse_sessions", "behavior_sessions")

        items.append(
            TimelineItem(
                id=ev.id,
                event_time=ev_utc,
                event_time_local=f"{date_str} at {time_str}",
                event_type=ev.event_type,
                ref_table=ev.ref_table,
                ref_id=ev.ref_id,
                title=title,
                summary=f"{time_str} — {title}",
                details=details,
                can_delete=can_del,
            )
        )

    next_cursor = results[-1].event_time.isoformat() if has_more and results else None

    return TimelineResponse(
        items=items,
        has_more=has_more,
        next_cursor=next_cursor,
    )
