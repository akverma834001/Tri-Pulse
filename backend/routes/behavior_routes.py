"""Routes for typing rhythm prompt retrieval and session recording."""

from datetime import datetime, timezone
import random
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, BehaviorSession
from backend.schemas import (
    TypingPromptResponse,
    TypingSubmit,
    BehaviorSessionResponse,
)
from backend.auth import get_current_user
from backend.consent import require_consents
from backend.services.behavior_engine import get_typing_prompt, evaluate_typing_session, NEUTRAL_TYPING_PROMPTS
from backend.services.event_service import record_timeline_event, delete_timeline_event
from backend.clock import get_clock

router = APIRouter(prefix="/api/behavior", tags=["Behavior"])


@router.get("/prompt", response_model=TypingPromptResponse)
def get_prompt():
    """Retrieve a random neutral typing prompt from the fixed pool."""
    idx = random.randint(0, len(NEUTRAL_TYPING_PROMPTS) - 1)
    text = get_typing_prompt(idx)
    return TypingPromptResponse(prompt_id=idx, text=text)


@router.post("", response_model=BehaviorSessionResponse, status_code=status.HTTP_201_CREATED)
def record_typing_session(
    data: TypingSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record typing rhythm session (counts only; no text received)."""
    require_consents(user, db, ["behavior"])

    # Idempotency check
    existing = (
        db.query(BehaviorSession)
        .filter(BehaviorSession.user_id == user.id, BehaviorSession.client_uuid == data.client_uuid)
        .first()
    )
    if existing:
        minutes = existing.duration_seconds / 60.0
        return BehaviorSessionResponse(
            id=existing.id,
            user_id=existing.user_id,
            event_time=existing.event_time,
            duration_seconds=existing.duration_seconds,
            keystrokes=existing.keystrokes,
            backspaces=existing.backspaces,
            pause_count=existing.pause_count,
            typing_speed_wpm=existing.typing_speed_wpm,
            error_rate=existing.error_rate,
            pause_frequency=round(existing.pause_count / minutes, 1),
            source=existing.source,
            client_uuid=existing.client_uuid,
            created_at=existing.created_at,
        )

    wpm, err_rate, pause_freq = evaluate_typing_session(
        duration_seconds=data.duration_seconds,
        keystrokes=data.keystrokes,
        backspaces=data.backspaces,
        pause_count=data.pause_count,
    )

    ev_time = data.event_time or get_clock().now()
    if ev_time.tzinfo is None:
        ev_time = ev_time.replace(tzinfo=timezone.utc)

    session_obj = BehaviorSession(
        user_id=user.id,
        event_time=ev_time,
        duration_seconds=data.duration_seconds,
        keystrokes=data.keystrokes,
        backspaces=data.backspaces,
        pause_count=data.pause_count,
        typing_speed_wpm=wpm,
        error_rate=err_rate,
        source="web_checkin",
        client_uuid=data.client_uuid,
        created_at=get_clock().now(),
    )
    db.add(session_obj)
    db.flush()

    # Timeline event
    record_timeline_event(
        db=db,
        user_id=user.id,
        event_time=session_obj.event_time,
        event_type="typing",
        ref_table="behavior_sessions",
        ref_id=session_obj.id,
        summary={
            "title": f"Typing Rhythm: {session_obj.typing_speed_wpm:.0f} WPM",
            "wpm": session_obj.typing_speed_wpm,
            "error_rate": session_obj.error_rate,
            "pauses": session_obj.pause_count,
        },
    )

    db.commit()
    db.refresh(session_obj)

    _trigger_pipeline(user.id, db)

    return BehaviorSessionResponse(
        id=session_obj.id,
        user_id=session_obj.user_id,
        event_time=session_obj.event_time,
        duration_seconds=session_obj.duration_seconds,
        keystrokes=session_obj.keystrokes,
        backspaces=session_obj.backspaces,
        pause_count=session_obj.pause_count,
        typing_speed_wpm=session_obj.typing_speed_wpm,
        error_rate=session_obj.error_rate,
        pause_frequency=pause_freq,
        source=session_obj.source,
        client_uuid=session_obj.client_uuid,
        created_at=session_obj.created_at,
    )


@router.get("", response_model=List[BehaviorSessionResponse])
def get_typing_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(BehaviorSession)
        .filter(BehaviorSession.user_id == user.id)
        .order_by(BehaviorSession.event_time.desc())
        .all()
    )
    res = []
    for s in sessions:
        minutes = max(0.1, s.duration_seconds / 60.0)
        res.append(
            BehaviorSessionResponse(
                id=s.id,
                user_id=s.user_id,
                event_time=s.event_time,
                duration_seconds=s.duration_seconds,
                keystrokes=s.keystrokes,
                backspaces=s.backspaces,
                pause_count=s.pause_count,
                typing_speed_wpm=s.typing_speed_wpm,
                error_rate=s.error_rate,
                pause_frequency=round(s.pause_count / minutes, 1),
                source=s.source,
                client_uuid=s.client_uuid,
                created_at=s.created_at,
            )
        )
    return res


@router.delete("/{session_id}")
def delete_typing_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_obj = (
        db.query(BehaviorSession)
        .filter(BehaviorSession.id == session_id, BehaviorSession.user_id == user.id)
        .first()
    )
    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Typing session not found."},
        )

    delete_timeline_event(db, user.id, "behavior_sessions", session_obj.id)
    db.delete(session_obj)
    db.commit()

    _trigger_pipeline(user.id, db)

    return {"message": "Typing session deleted successfully."}


def _trigger_pipeline(user_id: int, db: Session):
    try:
        from backend.services.pattern_engine import run_pattern_engine_for_user
        run_pattern_engine_for_user(user_id, db)
    except ImportError:
        pass
