"""Buyer-facing serializers. Seller and office-only fields never leave here."""

from __future__ import annotations

import json
from typing import Any

from .engine import minimum_next_bid

HIDDEN_VEHICLE_KEYS = (
    "customer_name",
    "customer_phone",
    "customer_address",
    "vin",
    "plate",
)

HIDDEN_APPOINTMENT_KEYS = (
    "customer_name",
    "customer_phone",
    "booking_appointment_id",
)


def _photos(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [value]
    return []


def safe_appointment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": row.get("date"),
        "time": row.get("time"),
        "status": row.get("status") or "SCHEDULED",
    }


def buyer_can_see_vehicle(vehicle: dict[str, Any], auction: dict[str, Any] | None = None) -> bool:
    status = vehicle.get("status")
    if status == "BIDDING_ACTIVE":
        return True
    if status == "READY_FOR_BIDDING" and vehicle.get("published_for_bidding"):
        return True
    if status == "BIDDING_ENDED" and auction and auction.get("status") in {"ENDED", "ACTIVE"}:
        return True
    return False


def public_vehicle(vehicle: dict[str, Any], auction: dict[str, Any] | None = None) -> dict[str, Any]:
    if not buyer_can_see_vehicle(vehicle, auction):
        raise PermissionError("vehicle_hidden")
    payload = {
        "id": vehicle["id"],
        "status": vehicle.get("status"),
        "brand": vehicle.get("brand"),
        "model": vehicle.get("model"),
        "year": vehicle.get("year"),
        "mileage": vehicle.get("mileage"),
        "transmission": vehicle.get("transmission"),
        "color": vehicle.get("color"),
        "body_type": vehicle.get("body_type"),
        "body_condition": vehicle.get("body_condition"),
        "inspection_summary": vehicle.get("inspection_summary"),
        "photos": _photos(vehicle.get("photos")),
    }
    if auction:
        increment = int(auction.get("bid_increment") or 0)
        current = int(auction.get("current_price") or 0)
        has_winner = auction.get("current_winner_id") is not None
        payload["auction"] = {
            "id": auction["id"],
            "status": auction.get("status"),
            "current_price": current,
            "minimum_next_bid": minimum_next_bid(current, increment, has_winner),
            "bid_increment": increment,
            "end_time": auction.get("end_time"),
            "start_time": auction.get("start_time"),
        }
    return payload


def public_bid(row: dict[str, Any], viewer_buyer_id: int | None) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "auction_id": row["auction_id"],
        "amount": row["amount"],
        "bid_type": row["bid_type"],
        "created_at": row["created_at"],
        "status": row.get("status"),
        "is_mine": viewer_buyer_id is not None and int(row["buyer_id"]) == int(viewer_buyer_id),
    }
    return item


def strip_seller(payload: dict[str, Any]) -> dict[str, Any]:
    extra = dict(payload)
    for key in HIDDEN_VEHICLE_KEYS + HIDDEN_APPOINTMENT_KEYS:
        extra.pop(key, None)
    extra.pop("max_bid", None)
    return extra
