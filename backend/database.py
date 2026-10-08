"""Database connection, session management, and SQLite pragma configuration."""

import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from backend.config import PULSE_DB_PATH

# Ensure parent directory for database exists if using file path
if not PULSE_DB_PATH.startswith(":memory:") and not PULSE_DB_PATH.startswith("sqlite:///:memory:"):
    db_file_path = Path(PULSE_DB_PATH)
    db_file_path.parent.mkdir(parents=True, exist_ok=True)

SQLITE_URL = f"sqlite:///{PULSE_DB_PATH}" if "://" not in PULSE_DB_PATH else PULSE_DB_PATH

engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enforce foreign key integrity and WAL journal mode on every SQLite connection."""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    except Exception:
        pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
