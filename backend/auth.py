"""Authentication, password hashing, session tokens, and rate-limiting."""

import hashlib
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import bcrypt
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session
from backend.config import (
    SESSION_EXPIRY_DAYS,
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW_MINUTES,
)
from backend.database import get_db
from backend.models import User, SessionModel
from backend.clock import get_clock


# --- In-memory Rate Limiting ---
# Structure: (email, ip) -> list of failure timestamps (float)
_login_failures: dict[Tuple[str, str], list[float]] = defaultdict(list)


def check_login_rate_limit(email: str, ip: str) -> bool:
    """Return True if under rate limit, False if rate limited."""
    now_ts = time.time()
    window_sec = LOGIN_RATE_LIMIT_WINDOW_MINUTES * 60
    key = (email.lower(), ip)
    
    # Prune older than window
    recent = [t for t in _login_failures[key] if now_ts - t < window_sec]
    _login_failures[key] = recent
    
    return len(recent) < LOGIN_RATE_LIMIT_MAX_ATTEMPTS


def record_login_failure(email: str, ip: str) -> None:
    """Record a failed login attempt."""
    _login_failures[(email.lower(), ip)].append(time.time())


def clear_login_failures(email: str, ip: str) -> None:
    """Clear recorded failures upon successful login."""
    key = (email.lower(), ip)
    if key in _login_failures:
        del _login_failures[key]


# --- Password Hashing ---
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# --- Session Management ---
SESSION_COOKIE_NAME = "pulse_session"


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(user_id: int, db: Session) -> str:
    """Create a new session, store its hash in DB, and return the raw token."""
    raw_token = secrets.token_hex(32)  # 256 bits
    token_h = hash_token(raw_token)
    now = get_clock().now()
    expires_at = now + timedelta(days=SESSION_EXPIRY_DAYS)
    
    session_obj = SessionModel(
        user_id=user_id,
        token_hash=token_h,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(session_obj)
    db.commit()
    return raw_token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    # Check explicit Authorization header first, fall back to session cookie
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        raw_token = auth_header[7:].strip()
    else:
        raw_token = request.cookies.get(SESSION_COOKIE_NAME)

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Authentication required"},
        )

    token_h = hash_token(raw_token)
    now = get_clock().now()

    session_obj = (
        db.query(SessionModel)
        .filter(SessionModel.token_hash == token_h)
        .first()
    )

    if not session_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthenticated", "message": "Invalid session"},
        )

    # Check expiration (ensure tz-aware)
    exp = session_obj.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    
    if exp < now:
        db.delete(session_obj)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "session_expired", "message": "Session has expired"},
        )

    # 7-day sliding expiry
    session_obj.expires_at = now + timedelta(days=SESSION_EXPIRY_DAYS)
    db.commit()

    user = db.query(User).filter(User.id == session_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "user_not_found", "message": "User not found"},
        )

    # Store user in request.state for logging
    request.state.user_id = user.id
    return user
