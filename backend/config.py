"""Configuration module for Project Pulse.

All thresholds, windows, and limits are defined as named constants,
overridable via environment variables.
"""

import os
from typing import List


def _get_str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")


# --- Environment & App ---
PULSE_ENV: str = _get_str("PULSE_ENV", "development")
PULSE_DB_PATH: str = _get_str("PULSE_DB_PATH", "data/pulse.db")
DEMO_ENABLED: bool = _get_bool("DEMO_ENABLED", True)
LOG_LEVEL: str = _get_str("LOG_LEVEL", "INFO")
SESSION_EXPIRY_DAYS: int = _get_int("SESSION_EXPIRY_DAYS", 7)
DEFAULT_TIMEZONE: str = _get_str("DEFAULT_TIMEZONE", "Asia/Kolkata")

# --- Security & Auth ---
PASSWORD_MIN_LENGTH: int = _get_int("PASSWORD_MIN_LENGTH", 10)
LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = _get_int("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5)
LOGIN_RATE_LIMIT_WINDOW_MINUTES: int = _get_int("LOGIN_RATE_LIMIT_WINDOW_MINUTES", 15)

# --- Orders ---
DEFAULT_LATE_NIGHT_START: str = _get_str("DEFAULT_LATE_NIGHT_START", "22:30")
DEFAULT_LATE_NIGHT_END: str = _get_str("DEFAULT_LATE_NIGHT_END", "05:00")
SUPPORTED_PLATFORMS: List[str] = [
    "Zomato",
    "Swiggy",
    "Zepto",
    "Blinkit",
    "EatSure",
    "Domino's",
    "McDonald's",
    "KFC",
    "Burger King",
    "Pizza Hut",
]

# --- Blood Pressure ---
BP_SYSTOLIC_MIN: int = _get_int("BP_SYSTOLIC_MIN", 60)
BP_SYSTOLIC_MAX: int = _get_int("BP_SYSTOLIC_MAX", 260)
BP_DIASTOLIC_MIN: int = _get_int("BP_DIASTOLIC_MIN", 30)
BP_DIASTOLIC_MAX: int = _get_int("BP_DIASTOLIC_MAX", 160)
BP_MAX_FUTURE_MINUTES: int = _get_int("BP_MAX_FUTURE_MINUTES", 5)
BP_MAX_AGE_DAYS: int = _get_int("BP_MAX_AGE_DAYS", 365)
BP_DUPLICATE_WINDOW_MINUTES: int = _get_int("BP_DUPLICATE_WINDOW_MINUTES", 2)

BP_URGENT_SYSTOLIC: int = _get_int("BP_URGENT_SYSTOLIC", 180)
BP_URGENT_DIASTOLIC: int = _get_int("BP_URGENT_DIASTOLIC", 120)
BP_ABOVE_RANGE_SYSTOLIC: int = _get_int("BP_ABOVE_RANGE_SYSTOLIC", 140)
BP_ABOVE_RANGE_DIASTOLIC: int = _get_int("BP_ABOVE_RANGE_DIASTOLIC", 90)
BP_ELEVATED_SYSTOLIC: int = _get_int("BP_ELEVATED_SYSTOLIC", 130)
BP_ELEVATED_DIASTOLIC: int = _get_int("BP_ELEVATED_DIASTOLIC", 80)

# --- Camera Pulse DSP ---
PULSE_MIN_SECONDS: float = _get_float("PULSE_MIN_SECONDS", 20.0)
PULSE_MIN_FPS: float = _get_float("PULSE_MIN_FPS", 15.0)
PULSE_SAMPLING_RATE_HZ: float = _get_float("PULSE_SAMPLING_RATE_HZ", 30.0)
PULSE_DETREND_WINDOW_SECONDS: float = _get_float("PULSE_DETREND_WINDOW_SECONDS", 1.5)
PULSE_FREQ_MIN_HZ: float = _get_float("PULSE_FREQ_MIN_HZ", 0.7)  # ~42 BPM
PULSE_FREQ_MAX_HZ: float = _get_float("PULSE_FREQ_MAX_HZ", 3.0)  # ~180 BPM
PULSE_MIN_QUALITY: float = _get_float("PULSE_MIN_QUALITY", 0.6)
PULSE_MIN_BPM: float = _get_float("PULSE_MIN_BPM", 40.0)
PULSE_MAX_BPM: float = _get_float("PULSE_MAX_BPM", 180.0)
PULSE_MAX_ESTIMATE_DIFF_BPM: float = _get_float("PULSE_MAX_ESTIMATE_DIFF_BPM", 5.0)
PULSE_MAX_SAMPLES: int = _get_int("PULSE_MAX_SAMPLES", 3600)
PULSE_DROP_INITIAL_SECONDS: float = _get_float("PULSE_DROP_INITIAL_SECONDS", 3.0)

# --- Typing Rhythm ---
TYPING_MIN_KEYSTROKES: int = _get_int("TYPING_MIN_KEYSTROKES", 40)
TYPING_MIN_DURATION_SECONDS: float = _get_float("TYPING_MIN_DURATION_SECONDS", 30.0)
TYPING_MAX_DURATION_SECONDS: float = _get_float("TYPING_MAX_DURATION_SECONDS", 120.0)
TYPING_TARGET_DURATION_SECONDS: float = _get_float("TYPING_TARGET_DURATION_SECONDS", 60.0)
TYPING_PAUSE_THRESHOLD_SECONDS: float = _get_float("TYPING_PAUSE_THRESHOLD_SECONDS", 2.0)
TYPING_MAX_WPM_CAP: float = _get_float("TYPING_MAX_WPM_CAP", 250.0)

# --- Personal Baselines ---
BASELINE_REQUIRED_SESSIONS: int = _get_int("BASELINE_REQUIRED_SESSIONS", 5)
BASELINE_CURRENT_WINDOW_DAYS: int = _get_int("BASELINE_CURRENT_WINDOW_DAYS", 7)
BASELINE_CURRENT_MIN_SESSIONS: int = _get_int("BASELINE_CURRENT_MIN_SESSIONS", 2)
BASELINE_LATE_NIGHT_WINDOW_DAYS: int = _get_int("BASELINE_LATE_NIGHT_WINDOW_DAYS", 14)
BASELINE_RECALIBRATE_DAYS: int = _get_int("BASELINE_RECALIBRATE_DAYS", 60)

# --- Pattern Engine ---
RULE_A_LATE_NIGHT_THRESHOLD: int = _get_int("RULE_A_LATE_NIGHT_THRESHOLD", 3)
RULE_B_MIN_DAYS: int = _get_int("RULE_B_MIN_DAYS", 2)
RULE_B_WINDOW_DAYS: int = _get_int("RULE_B_WINDOW_DAYS", 14)
RULE_PULSE_DEVIATION_PERCENT: float = _get_float("RULE_PULSE_DEVIATION_PERCENT", 8.0)
RULE_PULSE_DIFF_BPM: float = _get_float("RULE_PULSE_DIFF_BPM", 5.0)
RULE_TYPING_DEVIATION_PERCENT: float = _get_float("RULE_TYPING_DEVIATION_PERCENT", -10.0)
CIRCULAR_HOUR_ORIGIN: int = _get_int("CIRCULAR_HOUR_ORIGIN", 18)  # 18:00 local time reference

# --- Interventions ---
INTERVENTION_MAX_DAILY_SUGGESTIONS: int = _get_int("INTERVENTION_MAX_DAILY_SUGGESTIONS", 3)
INTERVENTION_COOLDOWN_HOURS: float = _get_float("INTERVENTION_COOLDOWN_HOURS", 6.0)
INTERVENTION_DISMISSAL_MUTE_COUNT: int = _get_int("INTERVENTION_DISMISSAL_MUTE_COUNT", 2)
INTERVENTION_DISMISSAL_MUTE_DAYS: int = _get_int("INTERVENTION_DISMISSAL_MUTE_DAYS", 3)
INTERVENTION_WORSE_MUTE_COUNT: int = _get_int("INTERVENTION_WORSE_MUTE_COUNT", 2)
INTERVENTION_LEARNING_MIN_ATTEMPTS: int = _get_int("INTERVENTION_LEARNING_MIN_ATTEMPTS", 5)
DEFAULT_QUIET_HOURS_START: str = _get_str("DEFAULT_QUIET_HOURS_START", "01:00")
DEFAULT_QUIET_HOURS_END: str = _get_str("DEFAULT_QUIET_HOURS_END", "07:00")
