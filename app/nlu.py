"""Fast local slot-filling NLU for short ask–answer voice turns.

Rule-based extraction (no LLM wait) so the agent can take the next
unfilled slot as soon as an utterance is endpointed. This matches
frame-based / overanswering dialogue used in task-oriented voice agents:
the user may fill more than the asked slot in one turn.
"""

from __future__ import annotations

import re
from typing import Any

PHASE_ASK_CAR = "ask_car"
PHASE_ASK_MODEL = "ask_model"
PHASE_ASK_KM = "ask_km"
PHASE_ASK_NAME = "ask_name"
PHASE_ASK_SLOT = "ask_slot"
PHASE_BOOKED = "booked"

YES_WORDS = ("بله", "آره", "اره", "باشه", "باشِ", "موافقم", "چشم", "حتما", "اوکی", "ok", "yes")
NO_WORDS = ("نه", "نخیر", "خیر", "نمیخوام", "نمی‌خوام", "no")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# Longer aliases first when matching.
BRAND_ALIASES: tuple[tuple[str, str], ...] = (
    ("peugeot", "پژو"),
    ("peugeote", "پژو"),
    ("peugeut", "پژو"),
    ("peguete", "پژو"),
    ("pegete", "پژو"),
    ("پژو", "پژو"),
    ("samand", "سمند"),
    ("سمند", "سمند"),
    ("pride", "پراید"),
    ("پراید", "پراید"),
    ("tiba", "تیبا"),
    ("تیبا", "تیبا"),
    ("dena", "دنا"),
    ("دنا", "دنا"),
    ("quick", "کوییک"),
    ("کوییک", "کوییک"),
    ("renault", "رنو"),
    ("رنو", "رنو"),
    ("toyota", "تویوتا"),
    ("تویوتا", "تویوتا"),
    ("hyundai", "هیوندای"),
    ("هیوندای", "هیوندای"),
    ("mercedes", "بنز"),
    ("benz", "بنز"),
    ("بنز", "بنز"),
    ("bmw", "بی‌ام‌و"),
    ("بی ام و", "بی‌ام‌و"),
    ("بی‌ام‌و", "بی‌ام‌و"),
    ("mazda", "مزدا"),
    ("مزدا", "مزدا"),
    ("nissan", "نیسان"),
    ("نیسان", "نیسان"),
    ("kia", "کیا"),
    ("کیا", "کیا"),
    ("jac", "جک"),
    ("جک", "جک"),
    ("chery", "چری"),
    ("چری", "چری"),
)

KNOWN_MODELS = {
    "206",
    "207",
    "208",
    "301",
    "405",
    "407",
    "508",
    "2008",
    "3008",
    "5008",
    "pars",
    "پارس",
    "elx",
    "glx",
    "slx",
    "tu5",
    "tu3",
    "lx",
}

_PUNCT = re.compile(r"[،,.!?؟:;\"'`]+")


def parse_km(text: str) -> int | None:
    if not text:
        return None
    spaced = text.translate(_DIGITS).replace(",", "").replace("٬", "")
    numbers = [int(item) for item in re.findall(r"\d+", spaced)]
    if not numbers:
        return None
    if "هزار" in text or "هزار" in spaced.replace(" ", ""):
        value = numbers[0]
        if value < 1000:
            value *= 1000
        return value
    large = [item for item in numbers if item >= 1000]
    if large:
        return large[0]
    return numbers[0]


def normalize_utterance(text: str) -> str:
    value = (text or "").strip().translate(_DIGITS)
    value = value.replace("‌", " ")
    value = _PUNCT.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip()


def _find_brand(lowered: str) -> tuple[str | None, str]:
    for alias, brand in sorted(BRAND_ALIASES, key=lambda item: len(item[0]), reverse=True):
        needle = alias.lower()
        if needle and needle in lowered:
            remainder = lowered.replace(needle, " ", 1)
            remainder = re.sub(r"\s+", " ", remainder).strip()
            return brand, remainder
    return None, lowered


def _find_model(remainder: str, original: str) -> str | None:
    lowered = remainder.lower()
    for token in sorted(KNOWN_MODELS, key=len, reverse=True):
        if token.isdigit():
            if re.search(rf"\b{token}\b", lowered) or token in original.translate(_DIGITS):
                return token
            continue
        if token in lowered or token in original:
            if token == "pars":
                return "پارس"
            return token
    numbers = re.findall(r"\b(\d{2,4})\b", lowered)
    for number in numbers:
        value = int(number)
        if number in KNOWN_MODELS or value < 1000:
            return str(value)
    return None


def parse_slots(text: str, phase: str = PHASE_ASK_CAR) -> dict[str, Any]:
    """Extract every booking slot present in one short customer turn."""
    raw = (text or "").strip()
    slots: dict[str, Any] = {
        "car_name": None,
        "car_model": None,
        "km": None,
        "customer_name": None,
        "confirm": None,
    }
    if not raw:
        return slots

    normalized = normalize_utterance(raw)
    lowered = normalized.lower()

    if any(word in raw for word in YES_WORDS) or re.search(r"\byes\b|\bok\b", lowered):
        slots["confirm"] = True
    if any(word in raw for word in NO_WORDS) and not slots["confirm"]:
        slots["confirm"] = False

    brand, remainder = _find_brand(lowered)
    if brand:
        slots["car_name"] = brand

    model = _find_model(remainder if brand else lowered, raw)
    km = parse_km(raw)
    km_mentioned = "کیلومتر" in raw or "کیلومتر" in normalized or "km" in lowered

    if phase == PHASE_ASK_KM:
        slots["km"] = km
    elif km is not None and (km >= 1000 or km_mentioned):
        slots["km"] = km
        if model and model.isdigit() and int(model) == km:
            model = None
    elif model and km is not None and str(km) == str(model):
        km = None

    if model and not (slots["km"] is not None and model.isdigit() and int(model) == slots["km"]):
        slots["car_model"] = model

    if phase == PHASE_ASK_CAR and not slots["car_name"]:
        leftover = normalized
        if slots["car_model"]:
            leftover = re.sub(rf"\b{re.escape(str(slots['car_model']))}\b", " ", leftover, flags=re.I)
            leftover = leftover.strip()
        if leftover and leftover.lower() not in {"مدل", "ماشین", "خودرو"}:
            slots["car_name"] = leftover

    if phase == PHASE_ASK_MODEL and not slots["car_model"]:
        candidate = remainder if brand else normalized
        if candidate and slots["km"] is None:
            slots["car_model"] = candidate

    if phase == PHASE_ASK_NAME:
        name = normalized
        if slots["confirm"] is not None and len(name) <= 4:
            name = ""
        if len(name) >= 2:
            slots["customer_name"] = name

    return slots


def next_missing_phase(car_name: str, car_model: str, km: int | None, customer_name: str) -> str:
    if not car_name:
        return PHASE_ASK_CAR
    if not car_model:
        return PHASE_ASK_MODEL
    if km is None:
        return PHASE_ASK_KM
    if not customer_name:
        return PHASE_ASK_NAME
    return PHASE_ASK_SLOT
