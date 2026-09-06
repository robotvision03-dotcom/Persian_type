"""Paginated daily auction/bid ledgers for office and buyers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..booking import is_office_open
from ..jalali import MONTHS_FA, format_jalali, jalali_month_matrix, to_jalali
from .db import get_conn
from .privacy import public_bid

PAGE_SIZE_MAX = 50
DEFAULT_PAGE_SIZE = 20
OFFICE_HOUR_START = 7
OFFICE_HOUR_END = 22


def parse_day(value: str | None, fallback: date | None = None) -> date:
    if value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return fallback or date.today()


def clamp_page(page: int | str | None, page_size: int | str | None) -> tuple[int, int, int]:
    try:
        page_n = int(page or 1)
    except (TypeError, ValueError):
        page_n = 1
    try:
        size_n = int(page_size or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        size_n = DEFAULT_PAGE_SIZE
    page_n = max(1, page_n)
    size_n = min(PAGE_SIZE_MAX, max(1, size_n))
    return page_n, size_n, (page_n - 1) * size_n


def day_window(day: date) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def ledger_day_of(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "")
    if len(text) >= 10:
        return text[:10]
    return date.today().isoformat()


def office_hours() -> list[str]:
    return [f"{hour:02d}" for hour in range(OFFICE_HOUR_START, OFFICE_HOUR_END + 1)]


def office_minutes() -> list[str]:
    return ["00", "15", "30", "45"]


def office_time_slots() -> list[str]:
    slots: list[str] = []
    last_hour = f"{OFFICE_HOUR_END:02d}"
    for hour in office_hours():
        for minute in office_minutes():
            if hour == last_hour and minute != "00":
                continue
            slots.append(f"{hour}:{minute}")
    return slots


def office_month_calendar(jy: int | None = None, jm: int | None = None) -> dict[str, Any]:
    today = date.today()
    if jy is None or jm is None:
        jy, jm, _jd = to_jalali(today)
    weeks = []
    for week in jalali_month_matrix(int(jy), int(jm)):
        row = []
        for day in week:
            if day is None:
                row.append(None)
                continue
            _jy, _jm, jd = to_jalali(day)
            row.append(
                {
                    "date": day.isoformat(),
                    "jalali": format_jalali(day),
                    "jalali_day": jd,
                    "today": day == today,
                    "friday": day.weekday() == 4,
                    "customer_open": is_office_open(day),
                    "off_hours_day": not is_office_open(day),
                }
            )
        weeks.append(row)
    return {
        "year": int(jy),
        "month": int(jm),
        "month_name": MONTHS_FA[int(jm) - 1],
        "weeks": weeks,
        "hours": office_hours(),
        "minutes": office_minutes(),
        "times": office_time_slots(),
        "today": today.isoformat(),
        "today_jalali": format_jalali(today),
    }


def _day_clause() -> str:
    return "auctions.ledger_day = ?"


def _office_bid(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "auction_id": row["auction_id"],
        "amount": row["amount"],
        "bid_type": row["bid_type"],
        "created_at": row["created_at"],
        "status": row["status"],
        "buyer_id": row["buyer_id"],
        "buyer_name": row["buyer_name"] or "",
        "buyer_phone": row["buyer_phone"] or "",
    }


def list_bids_page(
    auction_id: int,
    *,
    office: bool = False,
    viewer_buyer_id: int | None = None,
    page: int | str | None = 1,
    page_size: int | str | None = DEFAULT_PAGE_SIZE,
    db_path: Path | None = None,
) -> dict[str, Any]:
    page_n, size_n, offset = clamp_page(page, page_size)
    with get_conn(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM bids WHERE auction_id = ?", (auction_id,)).fetchone()["n"]
        if office:
            rows = conn.execute(
                """
                SELECT bids.*, buyer_profiles.contact_person AS buyer_name, buyer_profiles.phone AS buyer_phone
                FROM bids
                JOIN buyer_profiles ON buyer_profiles.id = bids.buyer_id
                WHERE bids.auction_id = ?
                ORDER BY bids.id ASC
                LIMIT ? OFFSET ?
                """,
                (auction_id, size_n, offset),
            ).fetchall()
            items = [_office_bid(row) for row in rows]
        else:
            rows = conn.execute(
                """
                SELECT * FROM bids WHERE auction_id = ?
                ORDER BY id ASC LIMIT ? OFFSET ?
                """,
                (auction_id, size_n, offset),
            ).fetchall()
            items = [public_bid(dict(row), viewer_buyer_id) for row in rows]
    return {
        "items": items,
        "total": int(total),
        "page": page_n,
        "page_size": size_n,
        "pages": max(1, (int(total) + size_n - 1) // size_n),
    }


def day_report(
    day: date,
    *,
    office: bool,
    buyer_id: int | None = None,
    page: int | str | None = 1,
    page_size: int | str | None = DEFAULT_PAGE_SIZE,
    db_path: Path | None = None,
) -> dict[str, Any]:
    page_n, size_n, offset = clamp_page(page, page_size)
    day_s = day.isoformat()
    buyer_filter = ""
    params: list[Any] = [day_s]
    if not office:
        buyer_filter = """
          AND auctions.id IN (
            SELECT auction_id FROM bids WHERE buyer_id = ?
            UNION
            SELECT auction_id FROM auction_winners WHERE buyer_id = ?
          )
        """
        params.extend([buyer_id, buyer_id])
    with get_conn(db_path) as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM auctions WHERE {_day_clause()} {buyer_filter}",
            params,
        ).fetchone()["n"]
        bid_total = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM bids
            JOIN auctions ON auctions.id = bids.auction_id
            WHERE {_day_clause()} {buyer_filter}
            """,
            params,
        ).fetchone()["n"]
        appt_total = 0
        if office:
            appt_total = conn.execute(
                "SELECT COUNT(*) AS n FROM marketplace_appointments WHERE date = ?",
                (day_s,),
            ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT auctions.*, vehicles.brand, vehicles.model, vehicles.year, vehicles.status AS vehicle_status
            FROM auctions
            JOIN vehicles ON vehicles.id = auctions.vehicle_id
            WHERE {_day_clause()} {buyer_filter}
            ORDER BY auctions.end_time DESC, auctions.id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, size_n, offset),
        ).fetchall()
        auctions = []
        for row in rows:
            auction = dict(row)
            counts = conn.execute(
                "SELECT COUNT(*) AS n FROM bids WHERE auction_id = ?",
                (auction["id"],),
            ).fetchone()
            winner = conn.execute(
                """
                SELECT auction_winners.*, buyer_profiles.contact_person AS buyer_name
                FROM auction_winners
                JOIN buyer_profiles ON buyer_profiles.id = auction_winners.buyer_id
                WHERE auction_winners.auction_id = ?
                """,
                (auction["id"],),
            ).fetchone()
            winner_payload = None
            if winner:
                winner_payload = {
                    "buyer_id": winner["buyer_id"] if office else None,
                    "buyer_name": winner["buyer_name"] if office else None,
                    "final_price": winner["final_price"],
                    "reserve_met": bool(winner["reserve_met"]),
                    "status": winner["status"],
                    "is_mine": buyer_id is not None and int(winner["buyer_id"]) == int(buyer_id),
                }
            auctions.append(
                {
                    "id": auction["id"],
                    "status": auction["status"],
                    "end_time": auction.get("end_time"),
                    "start_time": auction.get("start_time"),
                    "current_price": auction.get("current_price"),
                    "bid_count": int(counts["n"]),
                    "vehicle": {
                        "id": auction["vehicle_id"],
                        "brand": auction.get("brand"),
                        "model": auction.get("model"),
                        "year": auction.get("year"),
                        "status": auction.get("vehicle_status"),
                    },
                    "winner": winner_payload,
                }
            )
    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    return {
        "day": day_s,
        "jalali": format_jalali(day),
        "prev_day": prev_day.isoformat(),
        "next_day": next_day.isoformat(),
        "page": page_n,
        "page_size": size_n,
        "pages": max(1, (int(total) + size_n - 1) // size_n),
        "total_auctions": int(total),
        "total_bids": int(bid_total),
        "total_appointments": int(appt_total),
        "auctions": auctions,
    }
