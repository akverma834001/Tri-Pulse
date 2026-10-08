"""Typing rhythm signal service for Project Pulse.

Focuses purely on rhythm metrics (speed, pauses, error rate).
Never processes or stores typed text content.
"""

from typing import List, Dict, Any, Tuple
from fastapi import HTTPException, status
from backend.config import (
    TYPING_MIN_KEYSTROKES,
    TYPING_MIN_DURATION_SECONDS,
    TYPING_MAX_DURATION_SECONDS,
    TYPING_MAX_WPM_CAP,
)

# Fixed pool of 12 neutral sentences of comparable complexity
NEUTRAL_TYPING_PROMPTS: List[str] = [
    "The morning sunlight filtered gently through the large glass window onto the quiet desk.",
    "A steady rhythm and clear focus help navigate through a busy afternoon at the workplace.",
    "Several green plants lined the balcony railing, swaying softly in the mild evening breeze.",
    "The local library opened early today, offering a calm and peaceful space to read and reflect.",
    "Walking briskly along the park pathway refreshed both the mind and the tired muscles.",
    "Careful planning and consistent daily habits contribute significantly to long term balance.",
    "The distant hum of evening traffic faded as rain began to fall gently outside the building.",
    "Organizing notes and setting simple priorities creates a sense of clarity for tomorrow.",
    "A cup of warm water with lemon provides a refreshing pause before resuming computer work.",
    "Taking regular moments to breathe and stretch allows energy levels to remain steady.",
    "Clear communication and patience make working alongside teammates a smoother experience.",
    "The calm stillness of the early morning offers an ideal time for quiet contemplation.",
]


def get_typing_prompt(prompt_id: int = 0) -> str:
    """Return a neutral sentence prompt by index."""
    idx = prompt_id % len(NEUTRAL_TYPING_PROMPTS)
    return NEUTRAL_TYPING_PROMPTS[idx]


def evaluate_typing_session(
    duration_seconds: float,
    keystrokes: int,
    backspaces: int,
    pause_count: int,
) -> Tuple[float, float, float]:
    """Validate and compute typing rhythm metrics.
    Returns: (typing_speed_wpm, error_rate, pause_frequency)
    Raises 422 if invalid.
    """
    if duration_seconds < TYPING_MIN_DURATION_SECONDS or keystrokes < TYPING_MIN_KEYSTROKES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "session_too_short",
                "message": "Session too short. Try typing a bit longer (at least 30 seconds and 40 keystrokes).",
            },
        )

    if duration_seconds > (TYPING_MAX_DURATION_SECONDS + 30):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "session_too_long",
                "message": "Session duration exceeded maximum allowable test time.",
            },
        )

    minutes = duration_seconds / 60.0
    net_keystrokes = max(0, keystrokes - backspaces)
    wpm = round((net_keystrokes / 5.0) / minutes, 1)

    if wpm > TYPING_MAX_WPM_CAP:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "implausible_speed",
                "message": "Recorded typing speed exceeds plausible limits.",
            },
        )

    error_rate = round(backspaces / max(1, keystrokes), 3)
    pause_freq = round(pause_count / minutes, 1)

    return wpm, error_rate, pause_freq
