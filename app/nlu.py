"""Fast local slot-filling NLU for short ask–answer voice turns.

Rule-based extraction (no LLM wait) so the agent can take the next
unfilled slot as soon as an utterance is endpointed. This matches
frame-based / overanswering dialogue used in task-oriented voice agents:
the user may fill more than the asked slot in one turn.
"""

from __future__ import annotations

import re
from typing import Any

from .cars import match_vehicle
from .iranian_names import match_person_name
from .numbers import digitize_text, extract_ints, parse_int

PHASE_ASK_CAR = "ask_car"
PHASE_ASK_MODEL = "ask_model"
PHASE_ASK_KM = "ask_km"
PHASE_ASK_NAME = "ask_name"
PHASE_ASK_SLOT = "ask_slot"
PHASE_AWAIT_CALENDAR = "await_calendar"
PHASE_BOOKED = "booked"

YES_WORDS = ("بله", "آره", "اره", "باشه", "باشِ", "موافقم", "چشم", "حتما", "اوکی", "ok", "yes")
NO_WORDS = ("نه", "نخیر", "خیر", "نمیخوام", "نمی‌خوام", "no")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_PUNCT = re.compile(r"[،,.!?؟:;\"'`]+")
ZERO_WORDS = ("صفر", "نو", "صفر کیلومتر", "کارخانه")


def parse_km(text: str) -> int | None:
    if not text:
        return None
    values = extract_ints(text)
    large = [item for item in values if item >= 1000]
    if large:
        return max(large)
    spoken = parse_int(text)
    if spoken is not None:
        return spoken
    spaced = digitize_text(text).translate(_DIGITS).replace(",", "").replace("٬", "")
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


def parse_slots(text: str, phase: str = PHASE_ASK_CAR, prefer_brand: str = "") -> dict[str, Any]:
    """Extract every booking slot present in one short customer turn."""
    raw = (text or "").strip()
    slots: dict[str, Any] = {
        "car_name": None,
        "car_model": None,
        "km": None,
        "customer_name": None,
        "confirm": None,
        "candidates": [],
        "origin": "",
    }
    if not raw:
        return slots

    normalized = normalize_utterance(raw)
    lowered = normalized.lower()

    if any(word in raw for word in YES_WORDS) or re.search(r"\byes\b|\bok\b", lowered):
        slots["confirm"] = True
    if any(word in raw for word in NO_WORDS) and not slots["confirm"]:
        slots["confirm"] = False

    if phase != PHASE_ASK_NAME:
        hit = match_vehicle(raw, prefer_brand=prefer_brand or None)
        if hit.brand:
            slots["car_name"] = hit.brand
            slots["origin"] = hit.origin
        if hit.model:
            slots["car_model"] = hit.model
        if hit.candidates:
            slots["candidates"] = hit.candidates

    km = parse_km(raw)
    km_mentioned = "کیلومتر" in raw or "کیلومتر" in normalized or "km" in lowered
    if any(word in raw for word in ZERO_WORDS):
        slots["km"] = 0
    elif phase == PHASE_ASK_KM:
        slots["km"] = km
    elif km is not None and (km >= 1000 or km_mentioned):
        slots["km"] = km
        if slots["car_model"] and str(slots["car_model"]).isdigit() and int(slots["car_model"]) == km:
            slots["car_model"] = None

    if phase == PHASE_ASK_MODEL and not slots["car_model"]:
        leftover = normalized
        if slots["car_name"]:
            leftover = leftover.replace(slots["car_name"], "").strip()
        if leftover and leftover.lower() not in {"مدل", "ماشین", "خودرو"}:
            slots["car_model"] = leftover

    if phase == PHASE_ASK_NAME:
        person = match_person_name(raw)
        name = person.full or normalized
        if slots["confirm"] is not None and len(name) <= 4:
            name = ""
        if len(name) >= 2:
            slots["customer_name"] = name
        if person.candidates:
            slots["candidates"] = person.candidates

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
    return PHASE_AWAIT_CALENDAR
