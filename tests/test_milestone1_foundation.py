"""Tests for Milestone 1: Foundation (Auth, Config, Copy, Consent, Settings, Security)."""

import pytest
from backend import config
from backend import copy as copy_mod
from backend.cli import reset_password
from backend.models import User, Consent


def test_config_named_constants():
    """Verify named constants exist and have valid values."""
    assert config.PASSWORD_MIN_LENGTH == 10
    assert config.LOGIN_RATE_LIMIT_MAX_ATTEMPTS == 5
    assert config.LOGIN_RATE_LIMIT_WINDOW_MINUTES == 15
    assert config.DEFAULT_TIMEZONE == "Asia/Kolkata"
    assert config.BP_URGENT_SYSTOLIC == 180
    assert config.BP_URGENT_DIASTOLIC == 120
    assert config.PULSE_MIN_QUALITY == 0.6
    assert config.TYPING_MIN_KEYSTROKES == 40
    assert config.RULE_A_LATE_NIGHT_THRESHOLD == 3


def test_banned_phrases_in_copy():
    """Safety test: scan all user-facing copy in copy.py against banned phrases.
    Only explicit whitelisted phrases are allowed to contain words like 'diagnose'.
    """
    banned = copy_mod.BANNED_PHRASES
    whitelist = [w.lower() for w in copy_mod.WHITELISTED_PHRASES]

    # Gather all text strings from copy_mod
    all_strings = []
    for attr in dir(copy_mod):
        if attr.isupper():
            val = getattr(copy_mod, attr)
            if isinstance(val, str):
                all_strings.append(val)
            elif isinstance(val, dict):
                for sub_val in val.values():
                    if isinstance(sub_val, dict):
                        for item in sub_val.values():
                            if isinstance(item, str):
                                all_strings.append(item)
                    elif isinstance(sub_val, str):
                        all_strings.append(sub_val)

    for text in all_strings:
        lower_text = text.lower()
        # If the string contains a whitelisted phrase, remove that phrase before scanning
        cleaned_text = lower_text
        for wl in whitelist:
            cleaned_text = cleaned_text.replace(wl, "")

        for bp in banned:
            assert bp not in cleaned_text, f"Banned phrase '{bp}' found in copy: '{text}'"


def test_register_and_login(client):
    """Test user registration, 18+ enforcement, and login."""
    # Underage or missing checkbox fails
    res_underage = client.post(
        "/api/auth/register",
        json={"name": "Rohan", "email": "rohan@example.com", "password": "Password1234!", "age_confirmed": False},
    )
    assert res_underage.status_code == 422

    # Password too short fails
    res_short = client.post(
        "/api/auth/register",
        json={"name": "Rohan", "email": "rohan@example.com", "password": "short", "age_confirmed": True},
    )
    assert res_short.status_code == 422

    # Valid registration
    res_reg = client.post(
        "/api/auth/register",
        json={"name": "Rohan", "email": "rohan@example.com", "password": "Password1234!", "age_confirmed": True},
    )
    assert res_reg.status_code == 201
    user_data = res_reg.json()
    assert user_data["email"] == "rohan@example.com"
    assert "pulse_session" in res_reg.cookies

    # Duplicate registration returns 409
    res_dup = client.post(
        "/api/auth/register",
        json={"name": "Rohan 2", "email": "ROHAN@example.com", "password": "Password1234!", "age_confirmed": True},
    )
    assert res_dup.status_code == 409
    assert res_dup.json()["error"]["code"] == "email_exists"

    # Logout
    res_logout = client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    # Login with wrong password returns 401
    res_bad_pw = client.post(
        "/api/auth/login",
        json={"email": "rohan@example.com", "password": "WrongPassword!"},
    )
    assert res_bad_pw.status_code == 401
    assert res_bad_pw.json()["error"]["code"] == "invalid_credentials"

    # Login with correct password
    res_login = client.post(
        "/api/auth/login",
        json={"email": "rohan@example.com", "password": "Password1234!"},
    )
    assert res_login.status_code == 200
    assert res_login.json()["email"] == "rohan@example.com"

    # GET /api/me
    res_me = client.get("/api/me")
    assert res_me.status_code == 200
    assert res_me.json()["name"] == "Rohan"


def test_login_rate_limiting(client):
    """Test rate limiting: 5 failed attempts within window returns 429."""
    for i in range(5):
        res = client.post(
            "/api/auth/login",
            json={"email": "someone@test.com", "password": "badpassword"},
        )
        assert res.status_code == 401

    # 6th attempt should be rate limited (429)
    res_blocked = client.post(
        "/api/auth/login",
        json={"email": "someone@test.com", "password": "badpassword"},
    )
    assert res_blocked.status_code == 429
    assert res_blocked.json()["error"]["code"] == "rate_limited"


def test_csrf_header_protection(client):
    """Test that missing X-Pulse-Client header on state-changing API requests returns 403."""
    # Temporarily remove header
    res = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "Password123!"},
        headers={"X-Pulse-Client": "0"},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "missing_csrf_header"


def test_settings_and_consent(client, db_session):
    """Test settings update and consent toggle behavior."""
    # Register and get session
    client.post(
        "/api/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "Password1234!", "age_confirmed": True},
    )

    # Check default settings
    res_set = client.get("/api/settings")
    assert res_set.status_code == 200
    data_set = res_set.json()
    assert data_set["timezone"] == "Asia/Kolkata"
    assert data_set["nudges_enabled"] is True

    # Patch settings
    res_patch = client.patch(
        "/api/settings",
        json={"late_night_start": "23:00", "late_night_end": "04:30"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["late_night_start"] == "23:00"

    # Invalid timezone returns 422
    res_invalid_tz = client.patch("/api/settings", json={"timezone": "Mars/Olympus"})
    assert res_invalid_tz.status_code == 422

    # Check consents - all unchecked by default
    res_cons = client.get("/api/consent")
    assert res_cons.status_code == 200
    cons_data = res_cons.json()
    assert cons_data["camera"] is False
    assert cons_data["behavior"] is False
    assert cons_data["order_data"] is False
    assert cons_data["health_data"] is False

    # Grant consent
    res_grant = client.put(
        "/api/consent",
        json={"order_data": True, "health_data": True},
    )
    assert res_grant.status_code == 200
    assert res_grant.json()["order_data"] is True
    assert res_grant.json()["health_data"] is True
    assert res_grant.json()["camera"] is False
