"""Rule-based food classification service for Project Pulse.

Classifies food items into behavioral categories (not nutritional diagnosis).
"""

from typing import List
from backend.copy import FOOD_CLASSIFICATION_DISCLAIMER

KEYWORD_MAP = {
    "high_calorie": [
        "biryani",
        "mutton",
        "butter chicken",
        "paratha",
        "naan",
        "lasagna",
        "creamy",
        "heavy",
        "loaded",
        "cheese burst",
    ],
    "fast_food": [
        "pizza",
        "burger",
        "wrap",
        "roll",
        "taco",
        "sandwich",
        "nuggets",
        "hot dog",
        "sub",
        "momos",
        "chowmein",
        "noodles",
    ],
    "fried": [
        "fries",
        "french fries",
        "pakora",
        "samosa",
        "bhajiya",
        "fried chicken",
        "crispy",
        "vada",
        "puri",
        "bhature",
    ],
    "sugary": [
        "cake",
        "pastry",
        "ice cream",
        "gulab jamun",
        "jalebi",
        "brownie",
        "shake",
        "coke",
        "pepsi",
        "dessert",
        "waffle",
        "halwa",
        "rasgulla",
    ],
    "balanced": [
        "salad",
        "dal",
        "thali",
        "roti",
        "phulka",
        "idli",
        "dosa",
        "upma",
        "poha",
        "khichdi",
        "soup",
        "curd",
        "sprouts",
        "grilled chicken",
        "steamed",
        "sabzi",
    ],
}


def classify_food_items(items: List[str]) -> List[str]:
    """Return a deduplicated list of categories matched across items."""
    matched = set()
    combined_text = " ".join(items).lower()

    for category, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in combined_text:
                matched.add(category)
                break

    if not matched:
        return ["unknown"]

    return sorted(list(matched))


def get_classification_disclaimer() -> str:
    return FOOD_CLASSIFICATION_DISCLAIMER
