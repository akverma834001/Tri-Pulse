"""Blood pressure validation and classification service for Project Pulse.

Implements explicit precedence rules without medical diagnosis or stage labels.
"""

from datetime import datetime, timedelta, timezone
from typing import Tuple, Dict, Any, Optional
from fastapi import HTTPException, status
from backend.config import (
    BP_SYSTOLIC_MIN,
    BP_SYSTOLIC_MAX,
    BP_DIASTOLIC_MIN,
    BP_DIASTOLIC_MAX,
    BP_MAX_FUTURE_MINUTES,
    BP_MAX_AGE_DAYS,
    BP_URGENT_SYSTOLIC,
    BP_URGENT_DIASTOLIC,
    BP_ABOVE_RANGE_SYSTOLIC,
    BP_ABOVE_RANGE_DIASTOLIC,
    BP_ELEVATED_SYSTOLIC,
    BP_ELEVATED_DIASTOLIC,
)
from backend.copy import BP_HELPER_TEXT, BP_URGENT_TEXT
from backend.clock import get_clock


def validate_bp_reading(
    systolic: int,
    diastolic: int,
    event_time: datetime,
) -> None:
    """Validate systolic and diastolic values and event time range."""
    if not (BP_SYSTOLIC_MIN <= systolic <= BP_SYSTOLIC_MAX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_systolic",
                "message": f"Systolic reading must be between {BP_SYSTOLIC_MIN} and {BP_SYSTOLIC_MAX} mmHg.",
            },
        )

    if not (BP_DIASTOLIC_MIN <= diastolic <= BP_DIASTOLIC_MAX):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_diastolic",
                "message": f"Diastolic reading must be between {BP_DIASTOLIC_MIN} and {BP_DIASTOLIC_MAX} mmHg.",
            },
        )

    if systolic <= diastolic:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "systolic_must_exceed_diastolic",
                "message": "Systolic reading must be higher than diastolic reading.",
            },
        )

    now = get_clock().now()
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    # Check future threshold (5 mins)
    if event_time > now + timedelta(minutes=BP_MAX_FUTURE_MINUTES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "future_timestamp",
                "message": "Reading timestamp cannot be in the future.",
            },
        )

    # Check past threshold (1 year)
    if event_time < now - timedelta(days=BP_MAX_AGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "timestamp_too_old",
                "message": "Reading timestamp cannot be older than one year.",
            },
        )


def classify_blood_pressure(systolic: int, diastolic: int) -> Tuple[str, str, bool, Optional[str]]:
    """Classify blood pressure with explicit precedence.
    Returns: (category, category_label, is_urgent, urgent_message)
    Highest category wins:
    1. urgent: systolic > 180 OR diastolic > 120
    2. above_range: systolic >= 140 OR diastolic >= 90
    3. elevated: systolic 130-139 OR diastolic 80-89
    4. normal: below 130 AND below 80
    """
    if systolic > BP_URGENT_SYSTOLIC or diastolic > BP_URGENT_DIASTOLIC:
        return (
            "urgent",
            "Urgent reading",
            True,
            BP_URGENT_TEXT,
        )

    if systolic >= BP_ABOVE_RANGE_SYSTOLIC or diastolic >= BP_ABOVE_RANGE_DIASTOLIC:
        return (
            "above_range",
            "Above target range",
            False,
            None,
        )

    if (
        (BP_ELEVATED_SYSTOLIC <= systolic < BP_ABOVE_RANGE_SYSTOLIC)
        or (BP_ELEVATED_DIASTOLIC <= diastolic < BP_ABOVE_RANGE_DIASTOLIC)
    ):
        return (
            "elevated",
            "Elevated",
            False,
            None,
        )

    return (
        "normal",
        "Normal",
        False,
        None,
    )


def get_bp_helper_text() -> str:
    return BP_HELPER_TEXT
