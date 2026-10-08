"""Routes for micro-interventions lifecycle and outcome recording."""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User, Intervention
from backend.schemas import (
    InterventionCreate,
    InterventionResponse,
    InterventionOutcome,
    InterventionFeedback,
    InterventionStatsItem,
)
from backend.auth import get_current_user
from backend.copy import INTERVENTions_INFO
from backend.clock import get_clock
from backend.services.intervention_engine import (
    get_recommended_intervention,
    update_intervention_status,
    get_intervention_stats,
    VALID_TYPES,
)

router = APIRouter(prefix="/api/interventions", tags=["Interventions"])


def _to_intervention_response(i: Intervention) -> InterventionResponse:
    return InterventionResponse(
        id=i.id,
        user_id=i.user_id,
        trigger_type=i.trigger_type,
        intervention_type=i.intervention_type,
        suggested_by=i.suggested_by,
        insight_id=i.insight_id,
        status=i.status,
        planned_seconds=i.planned_seconds,
        actual_seconds=i.actual_seconds,
        feeling_after=i.feeling_after,
        created_at=i.created_at,
        started_at=i.started_at,
        ended_at=i.ended_at,
    )


@router.get("/recommendation")
def get_recommendation(
    manual_stress: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve current intervention recommendation if available under cooldown rules."""
    rec = get_recommended_intervention(user.id, db, manual_stress_flag=manual_stress)
    return {"recommendation": rec}


@router.post("", response_model=InterventionResponse, status_code=status.HTTP_201_CREATED)
def create_intervention(
    data: InterventionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or start an intervention."""
    if data.intervention_type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_type", "message": f"Unsupported intervention type '{data.intervention_type}'."},
        )

    info = INTERVENTions_INFO[data.intervention_type]
    planned_sec = info["planned_seconds"]

    intervention = Intervention(
        user_id=user.id,
        trigger_type=data.trigger_type,
        intervention_type=data.intervention_type,
        suggested_by=data.suggested_by,
        insight_id=data.insight_id,
        status="suggested",
        planned_seconds=planned_sec,
        created_at=get_clock().now(),
    )
    db.add(intervention)
    db.commit()
    db.refresh(intervention)
    return _to_intervention_response(intervention)


@router.post("/{intervention_id}/start", response_model=InterventionResponse)
def start_intervention(
    intervention_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    res = update_intervention_status(rec, "started", db)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/complete", response_model=InterventionResponse)
def complete_intervention(
    intervention_id: int,
    payload: dict = Body(default={}),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    actual_sec = payload.get("actual_seconds")
    feeling = payload.get("feeling_after")
    res = update_intervention_status(rec, "completed", db, actual_seconds=actual_sec, feeling_after=feeling)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/skip", response_model=InterventionResponse)
def skip_intervention(
    intervention_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    res = update_intervention_status(rec, "skipped", db)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/dismiss", response_model=InterventionResponse)
def dismiss_intervention(
    intervention_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    res = update_intervention_status(rec, "dismissed", db)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/abandon", response_model=InterventionResponse)
def abandon_intervention(
    intervention_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    res = update_intervention_status(rec, "abandoned", db)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/outcome", response_model=InterventionResponse)
def record_outcome(
    intervention_id: int,
    data: InterventionOutcome,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record outcome for order-delay (waited or ordered_anyway)."""
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    if data.status not in ("waited", "ordered_anyway", "dismissed"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_status", "message": "Invalid outcome status."})

    res = update_intervention_status(rec, data.status, db)
    return _to_intervention_response(res)


@router.post("/{intervention_id}/feedback", response_model=InterventionResponse)
def record_feedback(
    intervention_id: int,
    data: InterventionFeedback,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record optional feeling after: calmer, same, worse."""
    rec = db.query(Intervention).filter(Intervention.id == intervention_id, Intervention.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "not_found", "message": "Intervention not found."})

    if data.feeling_after not in ("calmer", "same", "worse"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_feeling", "message": "Invalid feeling value."})

    rec.feeling_after = data.feeling_after
    db.commit()
    db.refresh(rec)
    return _to_intervention_response(rec)


@router.get("/stats")
def get_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stats = get_intervention_stats(user.id, db)
    return stats
