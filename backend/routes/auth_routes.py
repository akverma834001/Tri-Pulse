"""Authentication routes: register, login, logout, me, change-password."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import User, UserSettings, SessionModel
from backend.schemas import (
    UserRegister,
    UserLogin,
    UserResponse,
    PasswordChange,
)
from backend.auth import (
    hash_password,
    verify_password,
    create_session,
    get_current_user,
    check_login_rate_limit,
    record_login_failure,
    clear_login_failures,
    SESSION_COOKIE_NAME,
    hash_token,
)
from backend.config import SESSION_EXPIRY_DAYS, DEFAULT_TIMEZONE

router = APIRouter(prefix="/api", tags=["Auth"])


def set_session_cookie(response: Response, raw_token: str, request: Request):
    is_secure = request.url.scheme == "https"
    max_age = SESSION_EXPIRY_DAYS * 24 * 3600
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_secure,
        path="/",
    )


@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    data: UserRegister,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    # Check email uniqueness
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "email_exists", "message": "An account with this email already exists."},
        )

    pw_hash = hash_password(data.password)
    user = User(
        name=data.name.strip(),
        email=data.email,
        password_hash=pw_hash,
        is_demo=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Initialize default settings
    settings = UserSettings(
        user_id=user.id,
        timezone=DEFAULT_TIMEZONE,
    )
    db.add(settings)
    db.commit()

    # Create session and set cookie
    token = create_session(user.id, db)
    set_session_cookie(response, token, request)

    return user


@router.post("/auth/login", response_model=UserResponse)
def login(
    data: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    # Check rate limit
    if not check_login_rate_limit(data.email, client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": "Too many failed login attempts. Please try again after 15 minutes.",
            },
        )

    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        record_login_failure(data.email, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Email or password is incorrect"},
        )

    # Clear rate limit failures on success
    clear_login_failures(data.email, client_ip)

    token = create_session(user.id, db)
    set_session_cookie(response, token, request)

    return user


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        token_h = hash_token(raw_token)
        db.query(SessionModel).filter(SessionModel.token_hash == token_h).delete()
        db.commit()

    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
@router.get("/auth/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


@router.post("/auth/change-password")
def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "incorrect_password", "message": "Current password is incorrect"},
        )

    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "Password updated successfully"}
