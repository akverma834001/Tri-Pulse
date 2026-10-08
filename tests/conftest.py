"""Pytest fixtures for Project Pulse tests."""

import os
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["PULSE_ENV"] = "testing"
os.environ["PULSE_DB_PATH"] = ":memory:"
os.environ["DEMO_ENABLED"] = "true"

from backend.database import Base, get_db
from backend.main import app
from backend.clock import get_clock, Clock
import backend.auth as auth_mod


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear rate limiting between tests."""
    auth_mod._login_failures.clear()
    yield
    auth_mod._login_failures.clear()


@pytest.fixture
def mock_clock():
    """Provide a controllable test clock."""
    c = get_clock()
    yield c
    c.reset()


@pytest.fixture
def db_session():
    """Create a fresh in-memory database session per test using StaticPool."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session):
    """TestClient wired to the test in-memory database."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    # Default header for CSRF
    test_client.headers.update({"X-Pulse-Client": "1"})
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def authenticated_user(client, db_session):
    """Register and authenticate a default test user, returning (user, headers)."""
    res = client.post(
        "/api/auth/register",
        json={"name": "Audit User", "email": "audit_user@example.com", "password": "Password1234!", "age_confirmed": True},
    )
    assert res.status_code == 201
    user_data = res.json()
    from backend.models import User
    user = db_session.query(User).filter(User.id == user_data["id"]).first()
    token = res.cookies.get("pulse_session")
    headers = {"Authorization": f"Bearer {token}", "X-Pulse-Client": "1"} if token else {"X-Pulse-Client": "1"}
    return user, headers
