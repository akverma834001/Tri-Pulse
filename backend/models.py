"""SQLAlchemy 2.0 ORM data models for Project Pulse."""

import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    Text,
)
from sqlalchemy.orm import relationship
from backend.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_demo = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships with CASCADE deletion
    settings = relationship("UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("SessionModel", back_populates="user", cascade="all, delete-orphan")
    consents = relationship("Consent", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    blood_pressures = relationship("BloodPressure", back_populates="user", cascade="all, delete-orphan")
    pulse_sessions = relationship("PulseSession", back_populates="user", cascade="all, delete-orphan")
    behavior_sessions = relationship("BehaviorSession", back_populates="user", cascade="all, delete-orphan")
    interventions = relationship("Intervention", back_populates="user", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="user", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="user", cascade="all, delete-orphan")
    baselines = relationship("CachedBaseline", back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    timezone = Column(String(50), default="Asia/Kolkata", nullable=False)
    late_night_start = Column(String(10), default="22:30", nullable=False)
    late_night_end = Column(String(10), default="05:00", nullable=False)
    nudges_enabled = Column(Boolean, default=True, nullable=False)
    food_nudges_enabled = Column(Boolean, default=True, nullable=False)
    quiet_hours_start = Column(String(10), default="01:00", nullable=False)
    quiet_hours_end = Column(String(10), default="07:00", nullable=False)
    sitting_reminder_minutes = Column(Integer, nullable=True)
    baselines_reset_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="settings")


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User", back_populates="sessions")


class Consent(Base):
    __tablename__ = "consent"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    consent_type = Column(String(50), nullable=False)  # camera, behavior, order_data, health_data
    granted = Column(Boolean, default=False, nullable=False)
    consent_version = Column(String(20), default="1.0", nullable=False)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="consents")

    __table_args__ = (
        UniqueConstraint("user_id", "consent_type", name="uq_user_consent_type"),
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)  # Delivery timestamp
    restaurant = Column(String(200), default="unknown", nullable=False)
    food_items = Column(Text, default="[]", nullable=False)  # JSON serialized list of strings
    amount = Column(Float, nullable=True)
    source = Column(String(50), default="unknown", nullable=False)
    food_categories = Column(Text, default="[]", nullable=False)  # JSON serialized list
    date_assumed = Column(Boolean, default=False, nullable=False)
    parse_confidence = Column(Float, default=1.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="orders")

    __table_args__ = (
        Index("ix_orders_user_event_time", "user_id", "event_time"),
    )

    def get_food_items(self) -> List[str]:
        try:
            return json.loads(self.food_items)
        except Exception:
            return []

    def get_food_categories(self) -> List[str]:
        try:
            return json.loads(self.food_categories)
        except Exception:
            return []


class BloodPressure(Base):
    __tablename__ = "blood_pressure"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    systolic = Column(Integer, nullable=False)
    diastolic = Column(Integer, nullable=False)
    pulse_optional = Column(Integer, nullable=True)
    source = Column(String(50), default="manual", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="blood_pressures")

    __table_args__ = (
        Index("ix_bp_user_event_time", "user_id", "event_time"),
    )


class PulseSession(Base):
    __tablename__ = "pulse_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    bpm = Column(Float, nullable=False)
    duration_seconds = Column(Float, nullable=False)
    signal_quality = Column(Float, nullable=False)  # 0.0 to 1.0
    source = Column(String(50), default="manual", nullable=False)  # camera, manual, demo
    client_uuid = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="pulse_sessions")

    __table_args__ = (
        Index("ix_pulse_user_event_time", "user_id", "event_time"),
        UniqueConstraint("user_id", "client_uuid", name="uq_pulse_user_client_uuid"),
    )


class BehaviorSession(Base):
    __tablename__ = "behavior_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    duration_seconds = Column(Float, nullable=False)
    keystrokes = Column(Integer, nullable=False)
    backspaces = Column(Integer, nullable=False)
    pause_count = Column(Integer, nullable=False)
    typing_speed_wpm = Column(Float, nullable=False)
    error_rate = Column(Float, nullable=False)
    source = Column(String(50), default="web_checkin", nullable=False)
    client_uuid = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="behavior_sessions")

    __table_args__ = (
        Index("ix_behavior_user_event_time", "user_id", "event_time"),
        UniqueConstraint("user_id", "client_uuid", name="uq_behavior_user_client_uuid"),
    )


class Intervention(Base):
    __tablename__ = "interventions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    trigger_type = Column(String(50), nullable=False)  # late_night_pattern, high_load, before_order, sitting_reminder, user_started
    intervention_type = Column(String(50), nullable=False)  # breathing_4min, winddown_5min, order_delay_10min, movement_5min
    suggested_by = Column(String(50), default="engine", nullable=False)  # engine, user
    insight_id = Column(Integer, ForeignKey("insights.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="suggested", nullable=False)  # suggested, started, completed, abandoned, skipped, dismissed, waited, ordered_anyway
    planned_seconds = Column(Integer, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    actual_seconds = Column(Integer, nullable=True)
    feeling_after = Column(String(50), nullable=True)  # calmer, same, worse

    user = relationship("User", back_populates="interventions")
    insight = relationship("Insight", back_populates="interventions")

    __table_args__ = (
        Index("ix_interventions_user_created_at", "user_id", "created_at"),
    )


class Insight(Base):
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    window_end_date = Column(String(10), nullable=False)  # YYYY-MM-DD for deterministic upsert per day
    category = Column(String(50), nullable=False)  # routine, vital, behavior, composite
    severity = Column(String(50), nullable=False)  # info, notice, attention, urgent
    title = Column(String(200), nullable=False)
    explanation = Column(Text, nullable=False)
    evidence = Column(Text, default="[]", nullable=False)  # JSON serialized list of strings
    recommended_action = Column(Text, nullable=False)
    status = Column(String(50), default="new", nullable=False)  # new, seen, dismissed, resolved
    is_supporting = Column(Boolean, default=False, nullable=False)
    feedback = Column(String(50), nullable=True)  # useful, not_useful

    user = relationship("User", back_populates="insights")
    interventions = relationship("Intervention", back_populates="insight")

    __table_args__ = (
        Index("ix_insights_user_created_at", "user_id", "created_at"),
        UniqueConstraint("user_id", "rule_id", "window_end_date", name="uq_user_rule_window_date"),
    )

    def get_evidence(self) -> List[str]:
        try:
            return json.loads(self.evidence)
        except Exception:
            return []


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(String(50), nullable=False)  # order, bp, pulse, typing, insight, intervention
    ref_table = Column(String(50), nullable=False)
    ref_id = Column(Integer, nullable=False)
    summary_json = Column(Text, default="{}", nullable=False)  # JSON summary
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="events")

    __table_args__ = (
        Index("ix_events_user_event_time", "user_id", "event_time"),
    )

    def get_summary(self) -> Dict[str, Any]:
        try:
            return json.loads(self.summary_json)
        except Exception:
            return {}


class CachedBaseline(Base):
    __tablename__ = "cached_baselines"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    signal_type = Column(String(50), primary_key=True)  # pulse_bpm, typing_wpm, pause_frequency, error_rate, bp_systolic, bp_diastolic, late_night_weekly_count
    baseline_value = Column(Float, nullable=False)
    session_count = Column(Integer, default=5, nullable=False)
    calculated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    is_frozen = Column(Boolean, default=True, nullable=False)

    user = relationship("User", back_populates="baselines")
