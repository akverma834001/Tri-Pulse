"""Consent verification and enforcement module for Project Pulse."""

from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from backend.models import User, Consent
from backend.clock import get_clock


CONSENT_HUMAN_NAMES = {
    "camera": "Camera pulse estimation",
    "behavior": "Typing rhythm analysis",
    "order_data": "Food order receipt processing",
    "health_data": "Health data storage (Blood Pressure & Pulse)",
}


def check_user_consent(user: User, db: Session, consent_type: str) -> bool:
    """Check if the user has actively granted a specific consent type."""
    consent = (
        db.query(Consent)
        .filter(Consent.user_id == user.id, Consent.consent_type == consent_type)
        .first()
    )
    return bool(consent and consent.granted)


def require_consents(user: User, db: Session, required_types: List[str]) -> None:
    """Enforce required consent types. Raises 403 if any required consent is missing."""
    for c_type in required_types:
        if not check_user_consent(user, db, c_type):
            readable_name = CONSENT_HUMAN_NAMES.get(c_type, c_type)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "consent_required",
                    "consent": c_type,
                    "message": f"Consent for '{readable_name}' is required to use this feature.",
                },
            )


def update_consent_state(
    user_id: int,
    consent_type: str,
    granted: bool,
    db: Session,
    version: str = "1.0",
) -> Consent:
    """Update or create a consent record with timestamp."""
    now = get_clock().now()
    consent = (
        db.query(Consent)
        .filter(Consent.user_id == user_id, Consent.consent_type == consent_type)
        .first()
    )
    if not consent:
        consent = Consent(
            user_id=user_id,
            consent_type=consent_type,
            granted=granted,
            consent_version=version,
            granted_at=now if granted else None,
            revoked_at=now if not granted else None,
        )
        db.add(consent)
    else:
        consent.granted = granted
        consent.consent_version = version
        if granted:
            consent.granted_at = now
            consent.revoked_at = None
        else:
            consent.revoked_at = now

    db.commit()
    db.refresh(consent)
    return consent
