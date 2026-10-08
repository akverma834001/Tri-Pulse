"""Routes for baseline progress inspection."""

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import User
from backend.schemas import BaselineItem
from backend.auth import get_current_user
from backend.services.baseline_engine import get_or_calculate_baselines

router = APIRouter(prefix="/api/baselines", tags=["Baselines"])


@router.get("", response_model=List[BaselineItem])
def get_user_baselines(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    baselines = get_or_calculate_baselines(user.id, db)
    items = []
    for key, b in baselines.items():
        items.append(
            BaselineItem(
                signal=b.signal_key,
                name=b.name,
                unit=b.unit,
                baseline_value=b.baseline_val,
                current_value=b.current_val,
                deviation_percent=b.deviation_pct,
                session_count=b.session_count,
                required_sessions=b.required_sessions,
                is_ready=b.is_ready,
                status=getattr(b, "status", "INSUFFICIENT_DATA"),
                explanation=b.explanation,
            )
        )
    return items
