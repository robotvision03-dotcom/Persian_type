"""Deterministic bid engine. No LLM, no hidden randomness."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def parse_dt(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def resolve_price(
    starting_price: int,
    increment: int,
    maxes: list[tuple[int, int, str]],
) -> tuple[int | None, int]:
    """Return (winner_buyer_id, current_price).

    highest_max wins. Price is min(second_highest + increment, highest_max),
    but never below starting_price. Earlier created_at wins a tie.
    """
    if increment <= 0:
        raise ValueError("bid_increment must be positive")
    if not maxes:
        return None, int(starting_price)
    ranked = sorted(maxes, key=lambda item: (-int(item[1]), str(item[2]), int(item[0])))
    winner_id, highest, _created = ranked[0]
    if len(ranked) == 1:
        return int(winner_id), int(starting_price)
    second = int(ranked[1][1])
    target = second + int(increment)
    current = min(target, int(highest))
    return int(winner_id), max(int(starting_price), current)


def minimum_next_bid(current_price: int, increment: int, has_bid: bool) -> int:
    if not has_bid:
        return int(current_price)
    return int(current_price) + int(increment)


def should_extend(
    now: datetime,
    end_time: datetime,
    enabled: bool,
    window_seconds: int,
    used: int,
    maximum: int,
) -> bool:
    if not enabled or used >= maximum:
        return False
    remaining = (end_time - now).total_seconds()
    return 0 < remaining <= window_seconds


def extend_end(end_time: datetime, extension_seconds: int) -> datetime:
    return end_time + timedelta(seconds=int(extension_seconds))


def reserve_met(current_price: int, reserve_price: int | None) -> bool:
    if reserve_price is None:
        return True
    return int(current_price) >= int(reserve_price)


def public_auction_view(auction: dict[str, Any], increment: int | None = None) -> dict[str, Any]:
    step = int(increment if increment is not None else auction.get("bid_increment") or 0)
    has_winner = auction.get("current_winner_id") is not None
    current = int(auction.get("current_price") or 0)
    return {
        "id": auction["id"],
        "status": auction.get("status"),
        "current_price": current,
        "minimum_next_bid": minimum_next_bid(current, step, has_winner),
        "bid_increment": step,
        "end_time": auction.get("end_time"),
        "start_time": auction.get("start_time"),
    }
