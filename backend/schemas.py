"""Pydantic v2 schemas for request validation and response serialization."""

from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict


# --- Base Response Envelope ---
class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    consent: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --- Auth Schemas ---
class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=10)
    age_confirmed: bool = Field(..., description="Must confirm age 18 or older")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        clean = v.strip().lower()
        if "@" not in clean or "." not in clean:
            raise ValueError("Invalid email format")
        return clean

    @field_validator("age_confirmed")
    @classmethod
    def check_age(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must be 18 or older to register")
        return v


class UserLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=10)


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_demo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Settings Schemas ---
class SettingsResponse(BaseModel):
    user_id: int
    timezone: str
    late_night_start: str
    late_night_end: str
    nudges_enabled: bool
    food_nudges_enabled: bool
    quiet_hours_start: str
    quiet_hours_end: str
    sitting_reminder_minutes: Optional[int] = None
    baselines_reset_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SettingsUpdate(BaseModel):
    timezone: Optional[str] = None
    late_night_start: Optional[str] = None
    late_night_end: Optional[str] = None
    nudges_enabled: Optional[bool] = None
    food_nudges_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    sitting_reminder_minutes: Optional[int] = None


# --- Consent Schemas ---
class ConsentUpdateRequest(BaseModel):
    camera: Optional[bool] = None
    behavior: Optional[bool] = None
    order_data: Optional[bool] = None
    health_data: Optional[bool] = None
    delete_revoked_data: Optional[bool] = False


class ConsentStatusResponse(BaseModel):
    camera: bool = False
    behavior: bool = False
    order_data: bool = False
    health_data: bool = False
    details: Dict[str, Any] = {}


# --- Orders Schemas ---
class OrderParseRequest(BaseModel):
    pasted_text: str = Field(..., min_length=3)


class ParsedField(BaseModel):
    value: Any
    found: bool


class OrderParseResponse(BaseModel):
    restaurant: ParsedField
    food_items: ParsedField
    amount: ParsedField
    delivery_time: ParsedField
    delivery_date: ParsedField
    source: ParsedField
    date_assumed: bool
    parse_confidence: float
    suggested_categories: List[str]
    is_late_night: bool
    normalized_event_time: str  # ISO UTC string


class OrderCreate(BaseModel):
    event_time: datetime
    restaurant: str = "unknown"
    food_items: List[str] = []
    amount: Optional[float] = None
    source: str = "unknown"
    food_categories: List[str] = []
    date_assumed: bool = False
    parse_confidence: float = 1.0
    client_uuid: Optional[str] = None


class OrderUpdate(BaseModel):
    restaurant: Optional[str] = None
    food_items: Optional[List[str]] = None
    amount: Optional[float] = None
    event_time: Optional[datetime] = None
    food_categories: Optional[List[str]] = None


class OrderResponse(BaseModel):
    id: int
    user_id: int
    event_time: datetime
    restaurant: str
    food_items: List[str]
    amount: Optional[float]
    source: str
    food_categories: List[str]
    date_assumed: bool
    parse_confidence: float
    is_late_night: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Blood Pressure Schemas ---
class BPCreate(BaseModel):
    systolic: int
    diastolic: int
    pulse_optional: Optional[int] = None
    event_time: Optional[datetime] = None
    source: str = "manual"
    client_uuid: Optional[str] = None


class BPUpdate(BaseModel):
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    pulse_optional: Optional[int] = None
    event_time: Optional[datetime] = None


class BPResponse(BaseModel):
    id: int
    user_id: int
    event_time: datetime
    systolic: int
    diastolic: int
    pulse_optional: Optional[int]
    category: str
    category_label: str
    source: str
    created_at: datetime
    urgent_alert: bool = False
    urgent_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Pulse Schemas ---
class PulseCameraInput(BaseModel):
    timestamps_ms: List[float] = Field(..., description="Timestamps in milliseconds from performance.now()")
    green: List[float] = Field(..., description="Mean green intensity values")
    client_uuid: str = Field(..., description="Idempotency key")


class PulseManualInput(BaseModel):
    bpm: float = Field(..., ge=30, le=240)
    client_uuid: str
    event_time: Optional[datetime] = None


class PulseSessionResponse(BaseModel):
    id: int
    user_id: int
    event_time: datetime
    bpm: float
    duration_seconds: float
    signal_quality: float
    source: str
    client_uuid: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Typing Rhythm Schemas ---
class TypingPromptResponse(BaseModel):
    prompt_id: int
    text: str


class TypingSubmit(BaseModel):
    client_uuid: str
    duration_seconds: float
    keystrokes: int
    backspaces: int
    pause_count: int
    total_pause_seconds: Optional[float] = 0.0
    event_time: Optional[datetime] = None


class BehaviorSessionResponse(BaseModel):
    id: int
    user_id: int
    event_time: datetime
    duration_seconds: float
    keystrokes: int
    backspaces: int
    pause_count: int
    typing_speed_wpm: float
    error_rate: float
    pause_frequency: float
    source: str
    client_uuid: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Intervention Schemas ---
class InterventionCreate(BaseModel):
    trigger_type: str = "user_started"
    intervention_type: str
    suggested_by: str = "user"
    insight_id: Optional[int] = None


class InterventionOutcome(BaseModel):
    status: str  # waited, ordered_anyway, dismissed


class InterventionFeedback(BaseModel):
    feeling_after: str  # calmer, same, worse


class InterventionResponse(BaseModel):
    id: int
    user_id: int
    trigger_type: str
    intervention_type: str
    suggested_by: str
    insight_id: Optional[int]
    status: str
    planned_seconds: int
    actual_seconds: Optional[int]
    feeling_after: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    ended_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class InterventionStatsItem(BaseModel):
    intervention_type: str
    attempts: int
    completed: int
    completion_rate: float
    calmer_count: int


# --- Insight Schemas ---
class InsightPatch(BaseModel):
    status: Optional[str] = None  # seen, dismissed
    feedback: Optional[str] = None  # useful, not_useful


class InsightResponse(BaseModel):
    id: int
    user_id: int
    rule_id: str
    window_start: datetime
    window_end: datetime
    category: str
    severity: str
    title: str
    explanation: str
    evidence: List[str]
    recommended_action: str
    status: str
    is_supporting: bool
    feedback: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Baselines & Trends ---
class BaselineItem(BaseModel):
    signal: str
    name: str
    unit: str
    baseline_value: Optional[float]
    current_value: Optional[float]
    deviation_percent: Optional[float]
    session_count: int
    required_sessions: int
    is_ready: bool
    explanation: str


class TrendBucket(BaseModel):
    bucket_label: str
    window_start: datetime
    window_end: datetime
    late_night_orders: int
    avg_bp_systolic: Optional[float]
    avg_bp_diastolic: Optional[float]
    avg_pulse: Optional[float]
    typing_deviation_pct: Optional[float]
    intervention_completion_rate: Optional[float]


# --- Dashboard Schema ---
class DashboardResponse(BaseModel):
    today_state: Dict[str, Any]
    primary_insight: Optional[InsightResponse]
    supporting_insights: List[InsightResponse]
    recommended_action: Optional[Dict[str, Any]]
    onboarding: Dict[str, Any]
    baseline_progress: List[BaselineItem]
    weekly_trends: List[TrendBucket]
    disclaimer: str


# --- Timeline Schema ---
class TimelineItem(BaseModel):
    id: int
    event_time: datetime
    event_time_local: str
    event_type: str
    ref_table: str
    ref_id: int
    title: str
    summary: str
    details: Dict[str, Any]
    can_delete: bool


class TimelineResponse(BaseModel):
    items: List[TimelineItem]
    has_more: bool
    next_cursor: Optional[str] = None


# --- Account Deletion Schema ---
class DataDeleteRequest(BaseModel):
    confirm: str = Field(..., description="Must match 'DELETE MY DATA'")
    password: str
