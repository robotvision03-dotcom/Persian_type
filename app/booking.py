"""Monday–Friday 09:00–17:00 appointment calendar and customer list."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, time as dtime
from pathlib import Path
from typing import Any, Iterator

from .jalali import MONTHS_FA, format_jalali, jalali_month_matrix, to_jalali

OFFICE_START = "09:00"
OFFICE_END = "17:00"
SLOT_MINUTES = 30
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "bookings.sqlite"


def default_db_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                car_name TEXT NOT NULL,
                car_model TEXT NOT NULL,
                km INTEGER,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'booked'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_appt_slot
                ON appointments(date, time) WHERE status = 'booked';
            """
        )


def is_office_open(day: date) -> bool:
    """Open Monday to Friday (دوشنبه تا جمعه غربی). Saturday and Sunday are closed."""
    return day.weekday() < 5


def slot_times() -> list[str]:
    start = dtime(9, 0)
    end = dtime(17, 0)
    out: list[str] = []
    cur = datetime.combine(date.today(), start)
    limit = datetime.combine(date.today(), end)
    while cur < limit:
        out.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=SLOT_MINUTES)
    return out


def taken_times(day: str, db_path: Path | None = None) -> set[str]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT time FROM appointments WHERE date = ? AND status = 'booked'",
            (day,),
        ).fetchall()
    return {row["time"] for row in rows}


def available_slots(day: str, db_path: Path | None = None) -> list[str]:
    parsed = date.fromisoformat(day)
    if not is_office_open(parsed):
        return []
    taken = taken_times(day, db_path)
    now = datetime.now()
    slots = []
    for hhmm in slot_times():
        if hhmm in taken:
            continue
        if parsed == now.date():
            hour, minute = map(int, hhmm.split(":"))
            if datetime.combine(parsed, dtime(hour, minute)) <= now:
                continue
        slots.append(hhmm)
    return slots


def next_open_slots(limit: int = 3, db_path: Path | None = None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    start = date.today()
    for offset in range(60):
        day = start + timedelta(days=offset)
        iso = day.isoformat()
        for hhmm in available_slots(iso, db_path):
            found.append(
                {
                    "date": iso,
                    "time": hhmm,
                    "label": f"{format_jalali(day)} ساعت {hhmm}",
                }
            )
            if len(found) >= limit:
                return found
    return found


def month_calendar(jy: int | None = None, jm: int | None = None, db_path: Path | None = None) -> dict[str, Any]:
    today = date.today()
    if jy is None or jm is None:
        jy, jm, _jd = to_jalali(today)
    weeks = []
    for week in jalali_month_matrix(jy, jm):
        row = []
        for day in week:
            if day is None:
                row.append(None)
                continue
            iso = day.isoformat()
            free = available_slots(iso, db_path) if day >= today else []
            row.append(
                {
                    "date": iso,
                    "jalali_day": to_jalali(day)[2],
                    "open": is_office_open(day) and day >= today,
                    "free_count": len(free),
                    "weekday": day.weekday(),
                    "today": day == today,
                }
            )
        weeks.append(row)
    return {
        "year": jy,
        "month": jm,
        "month_name": MONTHS_FA[jm - 1],
        "weeks": weeks,
        "hours": f"{OFFICE_START} تا {OFFICE_END}",
        "open_days": "دوشنبه تا جمعه",
    }


def book_appointment(
    customer_name: str,
    car_name: str,
    car_model: str,
    km: int | None,
    day: str,
    time: str,
    db_path: Path | None = None,
) -> int:
    init_db(db_path)
    if time not in available_slots(day, db_path):
        raise ValueError("این ساعت خالی نیست. وقت دیگری انتخاب کنید.")
    created = datetime.now().isoformat(timespec="seconds")
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO appointments
                (customer_name, car_name, car_model, km, date, time, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'booked')
            """,
            (customer_name, car_name, car_model, km, day, time, created),
        )
        return int(cur.lastrowid)


def list_appointments(db_path: Path | None = None, limit: int = 80) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM appointments
            ORDER BY date ASC, time ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["jalali"] = format_jalali(date.fromisoformat(item["date"]))
        except ValueError:
            item["jalali"] = item["date"]
        out.append(item)
    return out
