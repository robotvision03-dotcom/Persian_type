"""Deterministic buyer-to-vehicle matching. No LLM."""

from __future__ import annotations

import json
from typing import Any


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                return _list(parsed)
            except json.JSONDecodeError:
                return [text]
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def match_score(vehicle: dict[str, Any], preferences: dict[str, Any] | None) -> int:
    """Score 0–100. Stable for the same vehicle + preference inputs."""
    if not preferences or not int(preferences.get("active") or 0):
        return 50
    score = 0
    brands = {item.lower() for item in _list(preferences.get("preferred_brands"))}
    models = {item.lower() for item in _list(preferences.get("preferred_models"))}
    cities = {item.lower() for item in _list(preferences.get("preferred_cities"))}
    bodies = {item.lower() for item in _list(preferences.get("preferred_body_types"))}
    brand = str(vehicle.get("brand") or "").lower()
    model = str(vehicle.get("model") or "").lower()
    if brands:
        score += 25 if brand in brands else 0
    else:
        score += 12
    if models:
        score += 20 if model in models else 0
    else:
        score += 10
    year = vehicle.get("year")
    min_year = preferences.get("min_year")
    max_year = preferences.get("max_year")
    if year is None or (min_year is None and max_year is None):
        score += 8
    else:
        low = int(min_year) if min_year is not None else int(year)
        high = int(max_year) if max_year is not None else int(year)
        score += 15 if low <= int(year) <= high else 0
    price = int(vehicle.get("starting_price") or 0)
    min_budget = preferences.get("min_budget")
    max_budget = preferences.get("max_budget")
    if not price or (min_budget is None and max_budget is None):
        score += 10
    else:
        low = int(min_budget or 0)
        high = int(max_budget or price)
        score += 20 if low <= price <= high else 0
    city = str(vehicle.get("city") or preferences.get("vehicle_city") or "").lower()
    if cities:
        score += 10 if city in cities or not city else 0
    else:
        score += 5
    trans_pref = str(preferences.get("preferred_transmission") or "").lower()
    trans = str(vehicle.get("transmission") or "").lower()
    if trans_pref:
        score += 5 if trans_pref == trans else 0
    else:
        score += 3
    body = str(vehicle.get("body_type") or "").lower()
    if bodies:
        score += 5 if body in bodies else 0
    else:
        score += 2
    return max(0, min(100, score))
