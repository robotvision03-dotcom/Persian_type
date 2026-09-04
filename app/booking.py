"""Persian-week appointment calendar: Saturday–Thursday 09:00–17:00, Friday closed."""

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
            CREATE TABLE IF NOT EXISTS booking_invites (
                token TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                car_name TEXT NOT NULL,
                car_model TEXT NOT NULL,
                km INTEGER,
                phone TEXT NOT NULL,
                session_id TEXT,
                created_at TEXT NOT NULL,
                appointment_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                reminder_count INTEGER NOT NULL DEFAULT 0,
                last_reminder_at TEXT,
                next_reminder_at TEXT
            );
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(appointments)")}
        if "phone" not in columns:
            conn.execute("ALTER TABLE appointments ADD COLUMN phone TEXT")
        if "invite_token" not in columns:
            conn.execute("ALTER TABLE appointments ADD COLUMN invite_token TEXT")
        invite_columns = {row[1] for row in conn.execute("PRAGMA table_info(booking_invites)")}
        if "reminder_count" not in invite_columns:
            conn.execute(
                "ALTER TABLE booking_invites ADD COLUMN reminder_count INTEGER NOT NULL DEFAULT 0"
            )
        if "last_reminder_at" not in invite_columns:
            conn.execute("ALTER TABLE booking_invites ADD COLUMN last_reminder_at TEXT")
        if "next_reminder_at" not in invite_columns:
            conn.execute("ALTER TABLE booking_invites ADD COLUMN next_reminder_at TEXT")
        pending = conn.execute(
            """
            SELECT token, created_at, reminder_count
            FROM booking_invites
            WHERE status = 'pending'
              AND (next_reminder_at IS NULL OR next_reminder_at = '')
            """
        ).fetchall()
        for row in pending:
            created = parse_when(row["created_at"])
            nxt = next_reminder_time(created, int(row["reminder_count"] or 0))
            if nxt is not None:
                conn.execute(
                    "UPDATE booking_invites SET next_reminder_at = ? WHERE token = ?",
                    (nxt.isoformat(timespec="seconds"), row["token"]),
                )


def is_office_open(day: date) -> bool:
    """Iranian week: Friday is the weekend. Saturday through Thursday are working days."""
    return day.weekday() != 4


def next_open_date(start: date | None = None) -> date:
    day = start or date.today()
    for _offset in range(14):
        if is_office_open(day):
            return day
        day += timedelta(days=1)
    return day


def hours_panel(day: date | None = None, db_path: Path | None = None) -> dict[str, Any]:
    """Always-visible empty hours for the next working day (or a chosen day)."""
    target = day or next_open_date()
    iso = target.isoformat()
    open_ = is_office_open(target)
    return {
        "date": iso,
        "jalali": format_jalali(target),
        "open": open_,
        "all": slot_times() if open_ else [],
        "slots": available_slots(iso, db_path) if open_ else [],
        "hours": f"{OFFICE_START} تا {OFFICE_END}",
        "open_days": "شنبه تا پنجشنبه",
        "weekend": "جمعه",
    }


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
        "open_days": "شنبه تا پنجشنبه",
        "weekend": "جمعه",
        "focus": hours_panel(next_open_date(), db_path),
    }


DEFAULT_WHATSAPP = "+989032901549"
REMINDER_OFFSETS = (
    timedelta(hours=1),
    timedelta(hours=5),
    timedelta(days=1),
    timedelta(days=2),
    timedelta(days=3),
)
MAX_REMINDERS = len(REMINDER_OFFSETS)


def parse_when(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def next_reminder_time(created_at: datetime, reminder_count: int) -> datetime | None:
    if reminder_count >= MAX_REMINDERS:
        return None
    return created_at + REMINDER_OFFSETS[reminder_count]


def whatsapp_digits(phone: str | None = None) -> str:
    raw = phone or DEFAULT_WHATSAPP
    return "".join(char for char in raw if char.isdigit())


def whatsapp_send_url(text: str, phone: str | None = None) -> str:
    from urllib.parse import quote

    return f"https://wa.me/{whatsapp_digits(phone)}?text={quote(text)}"


def decorate_invite(item: dict[str, Any]) -> dict[str, Any]:
    extra = dict(item)
    token = extra["token"]
    extra["calendar_path"] = f"/book/{token}"
    count = int(extra.get("reminder_count") or 0)
    status = extra.get("status") or "pending"
    if status == "booked":
        extra["followup_label"] = "نوبت ثبت شد"
        extra["needs_admin_call"] = False
    elif status == "stopped":
        extra["followup_label"] = "یادآوری‌ها تمام شد — تماس ادمین"
        extra["needs_admin_call"] = True
    elif count == 0:
        extra["followup_label"] = "منتظر انتخاب وقت"
        extra["needs_admin_call"] = False
    else:
        extra["followup_label"] = f"{count} یادآوری ارسال شد"
        extra["needs_admin_call"] = False
    return extra


def create_invite(
    customer_name: str,
    car_name: str,
    car_model: str,
    km: int | None,
    session_id: str = "",
    phone: str | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    import secrets

    init_db(db_path)
    token = secrets.token_urlsafe(8).replace("_", "").replace("-", "")[:12]
    created_dt = parse_when(now)
    created = created_dt.isoformat(timespec="seconds")
    nxt = next_reminder_time(created_dt, 0)
    number = phone or DEFAULT_WHATSAPP
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO booking_invites
                (token, customer_name, car_name, car_model, km, phone, session_id,
                 created_at, status, reminder_count, next_reminder_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
            """,
            (
                token,
                customer_name,
                car_name,
                car_model,
                km,
                number,
                session_id,
                created,
                nxt.isoformat(timespec="seconds") if nxt else None,
            ),
        )
    return get_invite(token, db_path)


def get_invite(token: str, db_path: Path | None = None) -> dict[str, Any] | None:
    init_db(db_path)
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM booking_invites WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    return decorate_invite(dict(row))


def list_unbooked_invites(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM booking_invites
            WHERE status IN ('pending', 'stopped')
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [decorate_invite(dict(row)) for row in rows]


def due_reminders(
    now: datetime | str | None = None, db_path: Path | None = None
) -> list[dict[str, Any]]:
    when = parse_when(now)
    init_db(db_path)
    stamp = when.isoformat(timespec="seconds")
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM booking_invites
            WHERE status = 'pending'
              AND next_reminder_at IS NOT NULL
              AND next_reminder_at <= ?
            ORDER BY next_reminder_at ASC
            """,
            (stamp,),
        ).fetchall()
    return [decorate_invite(dict(row)) for row in rows]


def mark_reminder_sent(
    token: str,
    now: datetime | str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    invite = get_invite(token, db_path)
    if invite is None or invite["status"] != "pending":
        return invite
    when = parse_when(now)
    created = parse_when(invite["created_at"])
    count = int(invite.get("reminder_count") or 0) + 1
    nxt = next_reminder_time(created, count)
    status = "stopped" if nxt is None else "pending"
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE booking_invites
            SET reminder_count = ?, last_reminder_at = ?, next_reminder_at = ?, status = ?
            WHERE token = ? AND status = 'pending'
            """,
            (
                count,
                when.isoformat(timespec="seconds"),
                nxt.isoformat(timespec="seconds") if nxt else None,
                status,
                token,
            ),
        )
    return get_invite(token, db_path)


def book_invite(token: str, day: str, time: str, db_path: Path | None = None) -> dict[str, Any]:
    invite = get_invite(token, db_path)
    if invite is None:
        raise ValueError("این لینک تقویم معتبر نیست.")
    if invite["status"] == "booked" and invite.get("appointment_id"):
        raise ValueError("از این لینک قبلاً نوبت گرفته شده است.")
    appt_id = book_appointment(
        invite["customer_name"],
        invite["car_name"],
        invite["car_model"],
        invite["km"],
        day,
        time,
        db_path=db_path,
        phone=invite["phone"],
        invite_token=token,
    )
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE booking_invites
            SET status = 'booked', appointment_id = ?, next_reminder_at = NULL
            WHERE token = ?
            """,
            (appt_id, token),
        )
    slot_day = date.fromisoformat(day)
    return {
        "ok": True,
        "id": appt_id,
        "token": token,
        "date": day,
        "time": time,
        "jalali": format_jalali(slot_day),
        "customer_name": invite["customer_name"],
        "car_name": invite["car_name"],
        "car_model": invite["car_model"],
        "phone": invite["phone"],
        "message": "نوبت از روی تقویم واتساپ ثبت شد.",
    }


def book_appointment(
    customer_name: str,
    car_name: str,
    car_model: str,
    km: int | None,
    day: str,
    time: str,
    db_path: Path | None = None,
    phone: str | None = None,
    invite_token: str | None = None,
) -> int:
    init_db(db_path)
    if time not in available_slots(day, db_path):
        raise ValueError("این ساعت خالی نیست. وقت دیگری انتخاب کنید.")
    created = datetime.now().isoformat(timespec="seconds")
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO appointments
                (customer_name, car_name, car_model, km, date, time, created_at, status, phone, invite_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'booked', ?, ?)
            """,
            (customer_name, car_name, car_model, km, day, time, created, phone, invite_token),
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
