"""Consent management routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import (
    User,
    Consent,
    Order,
    BloodPressure,
    PulseSession,
    BehaviorSession,
    Event,
    CachedBaseline,
)
from backend.schemas import ConsentUpdateRequest, ConsentStatusResponse
from backend.auth import get_current_user
from backend.consent import update_consent_state

router = APIRouter(prefix="/api/consent", tags=["Consent"])

ALL_CONSENT_TYPES = ["camera", "behavior", "order_data", "health_data"]


@router.get("", response_model=ConsentStatusResponse)
def get_consents(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    consents = db.query(Consent).filter(Consent.user_id == user.id).all()
    status_map = {c.consent_type: c.granted for c in consents}
    details_map = {
        c.consent_type: {
            "granted": c.granted,
            "version": c.consent_version,
            "granted_at": c.granted_at.isoformat() if c.granted_at else None,
            "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
        }
        for c in consents
    }

    return ConsentStatusResponse(
        camera=status_map.get("camera", False),
        behavior=status_map.get("behavior", False),
        order_data=status_map.get("order_data", False),
        health_data=status_map.get("health_data", False),
        details=details_map,
    )


@router.put("", response_model=ConsentStatusResponse)
def update_consents(
    data: ConsentUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = {
        "camera": data.camera,
        "behavior": data.behavior,
        "order_data": data.order_data,
        "health_data": data.health_data,
    }

    revoked_types = []
    for c_type, new_val in updates.items():
        if new_val is not None:
            # Check previous value
            prev = (
                db.query(Consent)
                .filter(Consent.user_id == user.id, Consent.consent_type == c_type)
                .first()
            )
            was_granted = bool(prev and prev.granted)
            update_consent_state(user.id, c_type, new_val, db)
            if was_granted and not new_val:
                revoked_types.append(c_type)

    # Optional: Delete data collected under revoked consents if requested
    if data.delete_revoked_data and revoked_types:
        for r_type in revoked_types:
            if r_type == "order_data":
                orders = db.query(Order).filter(Order.user_id == user.id).all()
                order_ids = [o.id for o in orders]
                db.query(Event).filter(Event.user_id == user.id, Event.ref_table == "orders").delete()
                db.query(Order).filter(Order.user_id == user.id).delete()
            elif r_type == "health_data":
                db.query(Event).filter(Event.user_id == user.id, Event.ref_table.in_(["blood_pressure", "pulse_sessions"])).delete()
                db.query(BloodPressure).filter(BloodPressure.user_id == user.id).delete()
                db.query(PulseSession).filter(PulseSession.user_id == user.id).delete()
            elif r_type == "camera":
                db.query(Event).filter(Event.user_id == user.id, Event.ref_table == "pulse_sessions").delete()
                db.query(PulseSession).filter(PulseSession.user_id == user.id, PulseSession.source == "camera").delete()
            elif r_type == "behavior":
                db.query(Event).filter(Event.user_id == user.id, Event.ref_table == "behavior_sessions").delete()
                db.query(BehaviorSession).filter(BehaviorSession.user_id == user.id).delete()

        # Invalidate cached baselines so they are re-calculated or reset
        db.query(CachedBaseline).filter(CachedBaseline.user_id == user.id).delete()
        db.commit()

    return get_consents(user, db)
