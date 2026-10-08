"""Deterministic, regex-based receipt and order parser for Project Pulse.

Extracts delivery time, restaurant, food items, amount, and platform from pasted text.
Never fabricates missing fields.
"""

from datetime import datetime, date, time as dt_time, timedelta, timezone
import re
from typing import Dict, Any, List, Optional, Tuple
from zoneinfo import ZoneInfo
from backend.config import SUPPORTED_PLATFORMS, DEFAULT_LATE_NIGHT_START, DEFAULT_LATE_NIGHT_END
from backend.services.food_classifier import classify_food_items
from backend.clock import get_clock, to_utc, to_local


# --- Regex Patterns ---
PLATFORM_PATTERNS = {
    p.lower(): re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE)
    for p in SUPPORTED_PLATFORMS
}

CURRENCY_REGEX = re.compile(
    r"(?:₹|Rs\.?|INR)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)

# 11:48 PM, 11.48pm, 23:48, 8 PM, 8:00 AM
TIME_REGEX = re.compile(
    r"\b((?:[01]?\d|2[0-3])(?::|\.)[0-5]\d\s*(?:AM|PM|am|pm)?|[1-9]\s*(?:AM|PM|am|pm)|1[0-2]\s*(?:AM|PM|am|pm))\b"
)

# Dates: 12 Oct, 12 Oct 2026, 12/10/2026, 2026-10-12, today, yesterday
DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s+(\d{4}))?\b", re.IGNORECASE), "d_mon_y"),
    (re.compile(r"\btoday\b", re.IGNORECASE), "today"),
    (re.compile(r"\byesterday\b", re.IGNORECASE), "yesterday"),
]

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

RESTAURANT_REGEXES = [
    re.compile(r"(?:order|ordered|delivered)\s+from\s+([A-Za-z0-9\s'&’]+?)(?=(?:\s+(?:has|worth|for|was|is|placed|delivered|at|on)|\.|\,|$))", re.IGNORECASE),
    re.compile(r"from\s+([A-Za-z0-9\s'&’]+?)(?=(?:\s+(?:has|worth|for|was|is|placed|delivered|at|on)|\.|\,|$))", re.IGNORECASE),
    re.compile(r"restaurant:\s*([A-Za-z0-9\s'&’]+?)(?=(?:\s+(?:at|on)|\.|\,|$))", re.IGNORECASE),
]

ITEM_COUNT_REGEX = re.compile(
    r"(?:(\d+)\s*[xX]\s*([A-Za-z0-9\s'&-]+)|([A-Za-z0-9\s'&-]+)\s*[xX]\s*(\d+))"
)

IGNORE_ITEM_WORDS = {
    "subtotal", "total", "taxes", "gst", "delivery fee", "delivery charge",
    "tip", "discount", "packaging charge", "invoice", "paid via", "order id",
    "payment", "order summary", "items", "item", "bill",
}


def parse_time_str(time_str: str) -> Optional[dt_time]:
    """Parse time string into datetime.time object."""
    clean = time_str.strip().upper().replace(".", ":")
    # Handle single digit hour + AM/PM like "8 PM"
    m_hour_only = re.match(r"^(\d+)\s*(AM|PM)$", clean)
    if m_hour_only:
        h = int(m_hour_only.group(1))
        meridiem = m_hour_only.group(2)
        if meridiem == "PM" and h < 12:
            h += 12
        elif meridiem == "AM" and h == 12:
            h = 0
        return dt_time(hour=h, minute=0)

    # Handle HH:MM AM/PM or HH:MM
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(clean, fmt).time()
        except ValueError:
            continue
    return None


def is_late_night_time(
    dt: datetime,
    start_str: str = DEFAULT_LATE_NIGHT_START,
    end_str: str = DEFAULT_LATE_NIGHT_END,
    user_tz: str = "Asia/Kolkata",
) -> bool:
    """Check if datetime is within the configured late-night window in user's timezone.
    Boundaries: inclusive at start, exclusive at end.
    Example: 22:30 - 05:00 -> 22:29 False, 22:30 True, 04:59 True, 05:00 False.
    """
    local_dt = to_local(dt, user_tz)
    cur_time = local_dt.time()

    sh, sm = map(int, start_str.split(":"))
    eh, em = map(int, end_str.split(":"))
    start_t = dt_time(sh, sm)
    end_t = dt_time(eh, em)

    if start_t > end_t:
        # Crosses midnight: e.g. 22:30 to 05:00
        return cur_time >= start_t or cur_time < end_t
    else:
        # Same day window: e.g. 01:00 to 05:00
        return start_t <= cur_time < end_t


def parse_order_text(
    text: str,
    user_tz_name: str = "Asia/Kolkata",
    late_night_start: str = DEFAULT_LATE_NIGHT_START,
    late_night_end: str = DEFAULT_LATE_NIGHT_END,
) -> Dict[str, Any]:
    """Deterministic extraction of order attributes from raw text."""
    now_utc = get_clock().now()
    now_local = to_local(now_utc, user_tz_name)

    # 1. Platform Detection
    found_platform = "unknown"
    for p_name, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(text):
            # Map canonical case
            for orig in SUPPORTED_PLATFORMS:
                if orig.lower() == p_name:
                    found_platform = orig
                    break
            break

    # 2. Amount Extraction
    amount_val = None
    currency_match = CURRENCY_REGEX.search(text)
    if currency_match:
        raw_amt = currency_match.group(1).replace(",", "")
        try:
            amount_val = round(float(raw_amt), 2)
        except ValueError:
            pass

    # 3. Restaurant Extraction
    restaurant_val = "unknown"
    for r_regex in RESTAURANT_REGEXES:
        m = r_regex.search(text)
        if m:
            candidate = m.group(1).strip()
            # Clean trailing punctuation
            candidate = re.sub(r"[\.,]$", "", candidate).strip()
            if candidate and candidate.lower() not in ("your", "a", "the", "an"):
                restaurant_val = candidate
                break

    # 4. Food Items Extraction
    items: List[str] = []
    # Check "Item x1" or "2 x Item"
    for m in ITEM_COUNT_REGEX.finditer(text):
        if m.group(1) and m.group(2):
            count = m.group(1)
            name = m.group(2).strip()
        else:
            name = m.group(3).strip()
            count = m.group(4)
        if name.lower() not in IGNORE_ITEM_WORDS and len(name) > 2:
            items.append(f"{name} x{count}")

    if not items:
        # Check comma or "and" separated lists if present
        # Look for phrases following 'ordered' or 'items:'
        items_match = re.search(r"(?:items|ordered):\s*([^\n\.]+)", text, re.IGNORECASE)
        if items_match:
            raw_list = re.split(r",|\band\b", items_match.group(1))
            for raw_it in raw_list:
                cleaned = raw_it.strip()
                if cleaned and cleaned.lower() not in IGNORE_ITEM_WORDS:
                    items.append(cleaned)

    # 5. Time Extraction
    parsed_time: Optional[dt_time] = None
    time_match = TIME_REGEX.search(text)
    if time_match:
        parsed_time = parse_time_str(time_match.group(1))

    # 6. Date Extraction
    parsed_date: Optional[date] = None
    date_assumed = False

    for pat, pat_type in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            if pat_type == "today":
                parsed_date = now_local.date()
            elif pat_type == "yesterday":
                parsed_date = now_local.date() - timedelta(days=1)
            elif pat_type == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    parsed_date = date(y, mo, d)
                except ValueError:
                    pass
            elif pat_type == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                try:
                    parsed_date = date(y, mo, d)
                except ValueError:
                    pass
            elif pat_type == "d_mon_y":
                d = int(m.group(1))
                mo_str = m.group(2).lower()[:3]
                mo = MONTH_MAP.get(mo_str, 1)
                y = int(m.group(3)) if m.group(3) else now_local.year
                try:
                    parsed_date = date(y, mo, d)
                except ValueError:
                    pass
            if parsed_date:
                break

    # If date was missing: assume today, or if time is in future relative to now_local, assume yesterday
    target_time = parsed_time if parsed_time else now_local.time()
    if not parsed_date:
        candidate_dt = datetime.combine(now_local.date(), target_time)
        # If in the future, assume yesterday
        if candidate_dt > now_local.replace(tzinfo=None):
            parsed_date = now_local.date() - timedelta(days=1)
        else:
            parsed_date = now_local.date()
        date_assumed = True

    # Combine local date and time and convert to UTC
    local_event_dt = datetime.combine(parsed_date, target_time)
    utc_event_dt = to_utc(local_event_dt, user_tz_name)

    # Confidence calculation
    score = 0.0
    if found_platform != "unknown":
        score += 0.2
    if amount_val is not None:
        score += 0.25
    if restaurant_val != "unknown":
        score += 0.25
    if items:
        score += 0.2
    if parsed_time is not None:
        score += 0.1
    confidence = round(min(score, 1.0), 2)

    # Categories
    categories = classify_food_items(items) if items else ["unknown"]
    # Late night check
    late_night = is_late_night_time(utc_event_dt, late_night_start, late_night_end, user_tz_name)

    return {
        "restaurant": {"value": restaurant_val, "found": restaurant_val != "unknown"},
        "food_items": {"value": items, "found": len(items) > 0},
        "amount": {"value": amount_val, "found": amount_val is not None},
        "delivery_time": {"value": target_time.strftime("%H:%M"), "found": parsed_time is not None},
        "delivery_date": {"value": parsed_date.isoformat(), "found": not date_assumed},
        "source": {"value": found_platform, "found": found_platform != "unknown"},
        "date_assumed": date_assumed,
        "parse_confidence": confidence,
        "suggested_categories": categories,
        "is_late_night": late_night,
        "normalized_event_time": utc_event_dt.isoformat(),
    }
