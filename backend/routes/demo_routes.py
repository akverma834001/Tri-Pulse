"""Routes for demo mode initialization and reseeding."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.config import DEMO_ENABLED, SESSION_EXPIRY_DAYS
from backend.schemas import UserResponse
from backend.services.demo_seed import seed_demo_user
from backend.auth import SESSION_COOKIE_NAME

router = APIRouter(prefix="/api/demo", tags=["Demo"])


def _set_cookie(response: Response, token: str, request: Request):
    is_secure = request.url.scheme == "https"
    max_age = SESSION_EXPIRY_DAYS * 24 * 3600
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )


@router.post("/load", response_model=UserResponse)
def load_demo(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Seed or refresh the separate demo user and log the client in."""
    if not DEMO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "demo_disabled", "message": "Demo mode is disabled."})

    user, token = seed_demo_user(db)
    _set_cookie(response, token, request)
    return user


@router.post("/reset", response_model=UserResponse)
def reset_demo(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Reset the demo user dataset back to initial clean state."""
    if not DEMO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "demo_disabled", "message": "Demo mode is disabled."})

    user, token = seed_demo_user(db)
    _set_cookie(response, token, request)
    return user
