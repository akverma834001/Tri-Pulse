"""Safety copy, templates, and disclaimers for Project Pulse.

All user-facing copy lives here to ensure safety compliance and easy auditing.
"""

from typing import Dict, Any, List

# --- Core Disclaimers ---
GENERAL_DISCLAIMER = (
    "Project Pulse is a wellness and behavioral-support tool. "
    "It is not a medical device and does not diagnose or treat medical conditions."
)

CAMERA_PULSE_DISCLAIMER = (
    "Camera pulse is an experimental wellness estimate and is not a medical measurement."
)

FOOD_CLASSIFICATION_DISCLAIMER = (
    "This is a behavioral classification, not a nutritional diagnosis."
)

BP_HELPER_TEXT = (
    "Rest 5 minutes, sit with your back supported, use a validated upper-arm monitor."
)

BP_URGENT_TEXT = (
    "This reading is very high. Recheck after resting and seek urgent medical care "
    "if the reading remains very high or you have concerning symptoms."
)

SAFETY_PAGE_EMERGENCY_TEXT = (
    "Seek urgent medical care for chest pain, trouble breathing, fainting, "
    "confusion, or severe headache."
)

SAFETY_PAGE_HELPLINE_TEXT = (
    "Anyone experiencing emotional distress can contact local emergency or "
    "mental-health services (India: Tele-MANAS 14416)."
)

EATING_CARE_NOTE = (
    "If you're hungry, eating is fine. This is just a pause to check in with yourself."
)

INSUFFICIENT_DATA_MESSAGE = (
    "Not enough data yet. Continue using Pulse to establish your baseline."
)

# --- Insight Templates ---
INSIGHT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "A": {
        "title": "Late-night routine pattern",
        "explanation": "You have had several late-night food orders this week.",
        "recommended_action": "Try a 5-minute wind-down before placing another late-night order.",
        "category": "routine",
        "severity": "notice",
    },
    "B": {
        "title": "Repeated elevated readings",
        "explanation": "Your recent BP readings have been higher than your usual range.",
        "recommended_action": "Continue monitoring and consider discussing repeated elevated readings with a healthcare professional.",
        "category": "vital",
        "severity": "notice",
    },
    "C": {
        "title": "Late-night routine and typing rhythm",
        "explanation": "Your typing rhythm is slower than your usual baseline during a week with late-night orders.",
        "recommended_action": "Consider taking a short mental break or trying a breathing session.",
        "category": "behavior",
        "severity": "info",
    },
    "D": {
        "title": "Late-night routine and pulse trend",
        "explanation": "Your recent late-night routine coincided with a higher-than-usual pulse.",
        "recommended_action": "Try taking a pause to wind down before bed.",
        "category": "routine",
        "severity": "info",
    },
    "E": {
        "title": "Pulse above baseline",
        "explanation": "Your recent pulse is above your personal baseline.",
        "recommended_action": "Take a few minutes to pause or try a guided breathing session.",
        "category": "vital",
        "severity": "info",
    },
    "F": {
        "title": "Typing rhythm variation",
        "explanation": "Your typing rhythm is currently slower than your personal baseline.",
        "recommended_action": "Take a brief pause or step away for a gentle stretch.",
        "category": "behavior",
        "severity": "info",
    },
    "G": {
        "title": "Combined late-day pattern",
        "explanation": "Your recent late-day routine shows repeated late-night ordering alongside higher-than-usual physiological and behavioral signals.",
        "recommended_action": "Try a 5-minute wind-down before placing another late-night order.",
        "category": "composite",
        "severity": "attention",
    },
    "URGENT_BP": {
        "title": "Very high blood pressure reading",
        "explanation": BP_URGENT_TEXT,
        "recommended_action": "Recheck after resting. Seek urgent medical care if readings remain high or symptoms persist.",
        "category": "vital",
        "severity": "urgent",
    },
}

# --- Intervention Details ---
INTERVENTions_INFO: Dict[str, Dict[str, Any]] = {
    "breathing_4min": {
        "title": "Guided Breathing",
        "subtitle": "4-minute centering exercise",
        "planned_seconds": 240,
        "instructions": "Follow the pacing circle. Breathe in gently as it expands, hold, and breathe out slowly as it contracts. Stop if you feel dizzy or unwell.",
        "safety_note": "Stop if you feel dizzy or unwell.",
    },
    "winddown_5min": {
        "title": "Evening Wind-Down",
        "subtitle": "5-minute gentle transition",
        "planned_seconds": 300,
        "instructions": "Put your phone aside, take 5 slow breaths, drink a glass of water, and dim your lights before sleep.",
        "safety_note": "Stop if you feel dizzy or unwell.",
    },
    "order_delay_10min": {
        "title": "Pre-Order Pause",
        "subtitle": "10-minute mindful pause",
        "planned_seconds": 600,
        "instructions": EATING_CARE_NOTE,
        "safety_note": "Eating is normal and healthy. Take this moment simply to notice how you are feeling.",
    },
    "movement_5min": {
        "title": "Gentle Movement",
        "subtitle": "5-minute movement break",
        "planned_seconds": 300,
        "instructions": "Take a light 5-minute walk around your home or office to refresh your posture.",
        "safety_note": "Stop if you feel dizzy or unwell.",
    },
}

# --- Banned Phrases for Safety Auditing ---
BANNED_PHRASES: List[str] = [
    "depress",
    "hypertensi",
    "diabet",
    "cortisol",
    "insulin",
    "dopamine",
    "caused",
    "diagnos",
    "disease",
    "treat",
]

# Explicit whitelisted substrings for audit testing
WHITELISTED_PHRASES: List[str] = [
    "does not diagnose or treat medical conditions",
    "behavioral classification, not a nutritional diagnosis",
]
