"""Routes for user insights retrieval, status updates, and feedback."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Insight
from backend.schemas import InsightResponse, InsightPatch
from backend.auth import get_current_user
from backend.services.pattern_engine import run_pattern_engine_for_user, PRIORITY_ORDER

router = APIRouter(prefix="/api/insights", tags=["Insights"])


def _to_insight_response(ins: Insight) -> InsightResponse:
    return InsightResponse(
        id=ins.id,
        user_id=ins.user_id,
        rule_id=ins.rule_id,
        window_start=ins.window_start,
        window_end=ins.window_end,
        category=ins.category,
        severity=ins.severity,
        title=ins.title,
        explanation=ins.explanation,
        evidence=ins.get_evidence(),
        recommended_action=ins.recommended_action,
        status=ins.status,
        is_supporting=ins.is_supporting,
        feedback=ins.feedback,
        created_at=ins.created_at,
        updated_at=ins.updated_at,
    )


@router.get("", response_model=List[InsightResponse])
def get_insights(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve all current insights for user in priority order."""
    insights = run_pattern_engine_for_user(user.id, db)
    return [_to_insight_response(i) for i in insights]


@router.patch("/{insight_id}", response_model=InsightResponse)
def patch_insight(
    insight_id: int,
    data: InsightPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ins = db.query(Insight).filter(Insight.id == insight_id, Insight.user_id == user.id).first()
    if not ins:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "insight_not_found", "message": "Insight not found."},
        )

    if data.status is not None:
        if data.status in ("new", "seen", "dismissed"):
            ins.status = data.status
    if data.feedback is not None:
        if data.feedback in ("useful", "not_useful"):
            ins.feedback = data.feedback

    db.commit()
    db.refresh(ins)
    return _to_insight_response(ins)
