"""Marketplace application service: auth, office pipeline, and bidding."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..booking import list_appointments
from .catalog import empty_report, inspection_catalog, normalize_report, public_report
from .db import get_conn, init_marketplace
from .engine import (
    DEFAULT_MIN_INCREMENT,
    extend_end,
    live_increment,
    parse_dt,
    reserve_met,
    resolve_price,
    should_extend,
)
from .matching import match_score
from .privacy import buyer_can_see_vehicle, public_bid, public_vehicle, safe_appointment

PBKDF_ROUNDS = 180_000
SESSION_DAYS = 7
RESET_HOURS = 1
DEFAULT_INCREMENT = DEFAULT_MIN_INCREMENT
DEFAULT_DURATION_SECONDS = 60
MATCH_THRESHOLD = 60
LIVE_KEY = "live_revision"
STAFF = {
    "office@center.local": ("Office123!", "OFFICE"),
    "admin@center.local": ("Admin123!", "ADMIN"),
}


class MarketplaceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def now_iso(now: datetime | str | None = None) -> str:
    return parse_dt(now).isoformat(timespec="seconds")


def hash_password(password: str, salt: str | None = None) -> str:
    used = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), used.encode("utf-8"), PBKDF_ROUNDS)
    return f"{used}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, _digest = stored.split("$", 1)
    return secrets.compare_digest(hash_password(password, salt), stored)


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def bootstrap(db_path: Path | None = None) -> Path:
    path = init_marketplace(db_path)
    ensure_staff_users(path)
    return path


def _live_value(conn: Any) -> int:
    row = conn.execute("SELECT value FROM marketplace_settings WHERE key = ?", (LIVE_KEY,)).fetchone()
    return int(row["value"]) if row else 0


def bump_live(conn: Any) -> int:
    nxt = _live_value(conn) + 1
    conn.execute(
        "INSERT INTO marketplace_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (LIVE_KEY, str(nxt)),
    )
    return nxt


def live_state(db_path: Path | None = None) -> dict[str, int]:
    with get_conn(db_path) as conn:
        return {"revision": _live_value(conn)}


def ensure_staff_users(db_path: Path | None = None) -> None:
    created = now_iso()
    with get_conn(db_path) as conn:
        for email, (password, role) in STAFF.items():
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (?, ?, ?, 'ACTIVE', ?)",
                (email, hash_password(password), role, created),
            )


def get_user(user_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def user_by_email(email: str, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _row(conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone())


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_phone(phone: str) -> str:
    digits = _digits(phone)
    if digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    return digits


def normalize_buyer_identity(name: str = "", phone: str = "", national_id: str = "", required: bool = False) -> tuple[str, str, str]:
    clean_name = str(name or "").strip()
    clean_phone = normalize_phone(phone)
    clean_id = _digits(national_id)
    if required:
        if len(clean_name) < 2:
            raise MarketplaceError("نام خریدار را وارد کنید.", 400)
        if len(clean_phone) < 10:
            raise MarketplaceError("شماره تلفن معتبر نیست.", 400)
        if len(clean_id) != 10:
            raise MarketplaceError("کد ملی / شماره شناسایی باید ۱۰ رقم باشد.", 400)
    return clean_name, clean_phone, clean_id


def register_buyer(
    email: str,
    password: str,
    business_name: str = "",
    contact_person: str = "",
    phone: str = "",
    national_id: str = "",
    require_identity: bool = False,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    clean = email.lower().strip()
    if not clean or "@" not in clean:
        raise MarketplaceError("ایمیل معتبر نیست.", 400)
    if len(password) < 6:
        raise MarketplaceError("رمز عبور حداقل ۶ کاراکتر باشد.", 400)
    if user_by_email(clean, db_path):
        raise MarketplaceError("این ایمیل قبلاً ثبت شده است.", 409)
    contact_person, phone, national_id = normalize_buyer_identity(contact_person, phone, national_id, required=require_identity)
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, role, status, created_at) VALUES (?, ?, 'BUYER', 'ACTIVE', ?)",
            (clean, hash_password(password), stamp),
        )
        user_id = int(cur.lastrowid)
        cur = conn.execute(
            """
            INSERT INTO buyer_profiles
                (user_id, business_name, contact_person, phone, national_id, email, status, verification_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 'UNVERIFIED', ?, ?)
            """,
            (user_id, business_name, contact_person, phone, national_id, clean, stamp, stamp),
        )
        buyer_id = int(cur.lastrowid)
        conn.execute("INSERT INTO buyer_preferences (buyer_id) VALUES (?)", (buyer_id,))
        bump_live(conn)
    return get_buyer_profile(buyer_id, db_path)


def login(email: str, password: str, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    user = user_by_email(email, db_path)
    if user is None or not verify_password(password, user["password_hash"]):
        raise MarketplaceError("ایمیل یا رمز عبور نادرست است.", 401)
    if user["status"] != "ACTIVE":
        raise MarketplaceError("حساب کاربری فعال نیست.", 403)
    stamp = parse_dt(now)
    token = secrets.token_urlsafe(32)
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user["id"], stamp.isoformat(timespec="seconds"), (stamp + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")),
        )
    return {"token": token, "user": public_user(user, db_path)}


def logout(token: str, db_path: Path | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def session_user(token: str | None, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, stamp),
        ).fetchone()
    return _row(row)


def forgot_password(email: str, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    user = user_by_email(email, db_path)
    payload = {"ok": True}
    if user is None:
        return payload
    token = secrets.token_urlsafe(24)
    stamp = parse_dt(now)
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO password_resets (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user["id"], stamp.isoformat(timespec="seconds"), (stamp + timedelta(hours=RESET_HOURS)).isoformat(timespec="seconds")),
        )
    payload["reset_token"] = token
    return payload


def reset_password(token: str, password: str, db_path: Path | None = None, now: datetime | str | None = None) -> None:
    if len(password) < 6:
        raise MarketplaceError("رمز عبور حداقل ۶ کاراکتر باشد.", 400)
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE token = ? AND used_at IS NULL AND expires_at > ?",
            (token, stamp),
        ).fetchone()
        if row is None:
            raise MarketplaceError("لینک بازیابی معتبر نیست.", 400)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), row["user_id"]))
        conn.execute("UPDATE password_resets SET used_at = ? WHERE token = ?", (stamp, token))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))


def public_user(user: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    payload = {"id": user["id"], "email": user["email"], "role": user["role"], "status": user["status"]}
    if user["role"] == "BUYER":
        buyer = buyer_by_user(user["id"], db_path)
        if buyer:
            payload["buyer"] = buyer
    return payload


def buyer_by_user(user_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _row(conn.execute("SELECT * FROM buyer_profiles WHERE user_id = ?", (user_id,)).fetchone())


def get_buyer_profile(buyer_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _row(conn.execute("SELECT * FROM buyer_profiles WHERE id = ?", (buyer_id,)).fetchone())


def require_buyer(user: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    if user["role"] != "BUYER":
        raise MarketplaceError("فقط خریدار به این بخش دسترسی دارد.", 403)
    buyer = buyer_by_user(user["id"], db_path)
    if buyer is None:
        raise MarketplaceError("پروفایل خریدار پیدا نشد.", 404)
    return buyer


def require_staff(user: dict[str, Any]) -> None:
    if user["role"] not in {"OFFICE", "ADMIN"}:
        raise MarketplaceError("فقط دفتر به این بخش دسترسی دارد.", 403)


def update_buyer_profile(buyer_id: int, fields: dict[str, Any], db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    allowed = {
        "business_name",
        "contact_person",
        "phone",
        "national_id",
        "email",
        "city",
        "address",
        "dealer_type",
        "tax_id",
    }
    updates = {key: fields[key] for key in allowed if key in fields}
    if "contact_person" in updates or "phone" in updates or "national_id" in updates:
        current = get_buyer_profile(buyer_id, db_path) or {}
        name, phone, national_id = normalize_buyer_identity(
            str(updates.get("contact_person", current.get("contact_person") or "")),
            str(updates.get("phone", current.get("phone") or "")),
            str(updates.get("national_id", current.get("national_id") or "")),
            required=False,
        )
        if "contact_person" in updates:
            updates["contact_person"] = name
        if "phone" in updates:
            updates["phone"] = phone
        if "national_id" in updates:
            updates["national_id"] = national_id
    if not updates:
        profile = get_buyer_profile(buyer_id, db_path)
        if profile is None:
            raise MarketplaceError("پروفایل پیدا نشد.", 404)
        return profile
    updates["updated_at"] = now_iso(now)
    sets = ", ".join(f"{key} = ?" for key in updates)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE buyer_profiles SET {sets} WHERE id = ?", (*updates.values(), buyer_id))
    profile = get_buyer_profile(buyer_id, db_path)
    if profile is None:
        raise MarketplaceError("پروفایل پیدا نشد.", 404)
    return profile


def set_buyer_status(
    buyer_id: int,
    status: str | None = None,
    verification_status: str | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    parts = ["updated_at = ?"]
    values: list[Any] = [now_iso(now)]
    if status:
        parts.append("status = ?")
        values.append(status)
    if verification_status:
        parts.append("verification_status = ?")
        values.append(verification_status)
    values.append(buyer_id)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE buyer_profiles SET {', '.join(parts)} WHERE id = ?", values)
        bump_live(conn)
    profile = get_buyer_profile(buyer_id, db_path)
    if profile is None:
        raise MarketplaceError("پروفایل پیدا نشد.", 404)
    return profile


def activate_buyer(buyer_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    return set_buyer_status(buyer_id, status="ACTIVE", verification_status="VERIFIED", db_path=db_path, now=now)


def can_bid(buyer: dict[str, Any]) -> bool:
    return buyer.get("status") == "ACTIVE" and buyer.get("verification_status") == "VERIFIED"


def get_preferences(buyer_id: int, db_path: Path | None = None) -> dict[str, Any]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM buyer_preferences WHERE buyer_id = ?", (buyer_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO buyer_preferences (buyer_id) VALUES (?)", (buyer_id,))
            row = conn.execute("SELECT * FROM buyer_preferences WHERE buyer_id = ?", (buyer_id,)).fetchone()
    item = dict(row)
    for key in ("preferred_brands", "preferred_models", "preferred_cities", "preferred_body_types"):
        try:
            item[key] = json.loads(item[key])
        except (TypeError, json.JSONDecodeError):
            item[key] = []
    return item


def update_preferences(buyer_id: int, fields: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    current = get_preferences(buyer_id, db_path)
    current.update({key: fields[key] for key in fields if key != "buyer_id"})
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE buyer_preferences SET
                preferred_brands = ?, preferred_models = ?, min_year = ?, max_year = ?,
                min_budget = ?, max_budget = ?, preferred_cities = ?,
                preferred_transmission = ?, preferred_body_types = ?, active = ?
            WHERE buyer_id = ?
            """,
            (
                json.dumps(current.get("preferred_brands") or [], ensure_ascii=False),
                json.dumps(current.get("preferred_models") or [], ensure_ascii=False),
                current.get("min_year"),
                current.get("max_year"),
                current.get("min_budget"),
                current.get("max_budget"),
                json.dumps(current.get("preferred_cities") or [], ensure_ascii=False),
                current.get("preferred_transmission") or "",
                json.dumps(current.get("preferred_body_types") or [], ensure_ascii=False),
                1 if current.get("active", True) else 0,
                buyer_id,
            ),
        )
    return get_preferences(buyer_id, db_path)


def notify(
    user_id: int,
    event: str,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
    conn=None,
) -> None:
    params = (user_id, event, title, body, json.dumps(payload or {}, ensure_ascii=False), now_iso(now))
    sql = "INSERT INTO notifications (user_id, event, title, body, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)"
    if conn is not None:
        conn.execute(sql, params)
        return
    with get_conn(db_path) as owned:
        owned.execute(sql, params)


def list_notifications(user_id: int, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 80",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_appointment(date: str, time: str, customer_name: str = "", customer_phone: str = "", db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO marketplace_appointments (customer_name, customer_phone, date, time, status, created_at)
            VALUES (?, ?, ?, ?, 'SCHEDULED', ?)
            """,
            (customer_name, customer_phone, date, time, stamp),
        )
        appt_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO vehicles (appointment_id, status, customer_name, customer_phone, created_at, updated_at)
            VALUES (?, 'APPOINTMENT_SCHEDULED', ?, ?, ?, ?)
            """,
            (appt_id, customer_name, customer_phone, stamp, stamp),
        )
        bump_live(conn)
    return get_appointment(appt_id, db_path)


def get_appointment(appointment_id: int, db_path: Path | None = None) -> dict[str, Any]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM marketplace_appointments WHERE id = ?", (appointment_id,)).fetchone()
    if row is None:
        raise MarketplaceError("نوبت پیدا نشد.", 404)
    return dict(row)


def set_appointment_status(appointment_id: int, status: str, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    mapping = {
        "ARRIVED": ("CUSTOMER_ARRIVED", "CUSTOMER_ARRIVED"),
        "CUSTOMER_ARRIVED": ("CUSTOMER_ARRIVED", "CUSTOMER_ARRIVED"),
        "INSPECTION_IN_PROGRESS": ("INSPECTION_IN_PROGRESS", "INSPECTION_IN_PROGRESS"),
        "INSPECTION_COMPLETED": ("INSPECTION_COMPLETED", "INSPECTION_COMPLETED"),
        "CANCELLED": ("CANCELLED", "CANCELLED"),
    }
    appt_status, vehicle_status = mapping.get(status, (status, None))
    with get_conn(db_path) as conn:
        conn.execute("UPDATE marketplace_appointments SET status = ? WHERE id = ?", (appt_status, appointment_id))
        if vehicle_status:
            conn.execute(
                "UPDATE vehicles SET status = ?, updated_at = ? WHERE appointment_id = ?",
                (vehicle_status, now_iso(now), appointment_id),
            )
        bump_live(conn)
    return get_appointment(appointment_id, db_path)


def office_appointments(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM marketplace_appointments ORDER BY date, time").fetchall()
    out = [dict(row) for row in rows]
    for item in list_appointments(db_path):
        out.append(
            {
                "id": None,
                "booking_appointment_id": item.get("id"),
                "customer_name": item.get("customer_name"),
                "customer_phone": item.get("phone") or "",
                "date": item.get("date"),
                "time": item.get("time"),
                "status": "SCHEDULED",
                "source": "booking",
            }
        )
    out.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("time") or "")))
    return out


def buyer_appointments(db_path: Path | None = None) -> list[dict[str, Any]]:
    return [safe_appointment(row) for row in office_appointments(db_path) if row.get("status") != "CANCELLED"]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return [part.strip() for part in value.replace("\n", "،").split("،") if part.strip()]
    return []


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _inspection_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    report = normalize_report(_json_obj(data.get("report_json")))
    data["report"] = report
    data["public_report"] = public_report(report)
    return data


def _latest_inspection_row(conn: Any, vehicle_id: int) -> Any:
    return conn.execute(
        "SELECT * FROM inspections WHERE vehicle_id = ? ORDER BY id DESC LIMIT 1",
        (vehicle_id,),
    ).fetchone()


def _hydrate_vehicle(row: Any, inspection: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(row)
    data["strengths"] = _json_list(data.get("strengths"))
    data["inspection"] = inspection
    return data


def get_inspection(vehicle_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _inspection_from_row(_latest_inspection_row(conn, vehicle_id))


def get_vehicle(vehicle_id: int, db_path: Path | None = None) -> dict[str, Any]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        inspection = _inspection_from_row(_latest_inspection_row(conn, vehicle_id)) if row else None
    if row is None:
        raise MarketplaceError("خودرو پیدا نشد.", 404)
    return _hydrate_vehicle(row, inspection)


def list_vehicles(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM vehicles ORDER BY id DESC").fetchall()
        inspections = {
            item["vehicle_id"]: _inspection_from_row(item)
            for item in conn.execute(
                """
                SELECT * FROM inspections WHERE id IN (
                    SELECT MAX(id) FROM inspections GROUP BY vehicle_id
                )
                """
            ).fetchall()
        }
    return [_hydrate_vehicle(row, inspections.get(row["id"])) for row in rows]


def update_vehicle(vehicle_id: int, fields: dict[str, Any], db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    allowed = {
        "brand",
        "model",
        "year",
        "mileage",
        "transmission",
        "color",
        "body_type",
        "body_condition",
        "paint_status",
        "cabin_condition",
        "technical_condition",
        "fuel_type",
        "engine",
        "document_type",
        "insurance_months",
        "strengths",
        "inspection_summary",
        "photos",
        "starting_price",
        "reserve_price",
        "customer_name",
        "customer_phone",
        "customer_address",
        "vin",
        "plate",
        "status",
    }
    updates = {key: fields[key] for key in allowed if key in fields}
    if "photos" in updates and not isinstance(updates["photos"], str):
        updates["photos"] = json.dumps(updates["photos"], ensure_ascii=False)
    if "strengths" in updates and not isinstance(updates["strengths"], str):
        updates["strengths"] = json.dumps(_json_list(updates["strengths"]), ensure_ascii=False)
    updates["updated_at"] = now_iso(now)
    sets = ", ".join(f"{key} = ?" for key in updates)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE vehicles SET {sets} WHERE id = ?", (*updates.values(), vehicle_id))
    return get_vehicle(vehicle_id, db_path)


def start_inspection(vehicle_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    stamp = now_iso(now)
    report = json.dumps(empty_report(), ensure_ascii=False)
    with get_conn(db_path) as conn:
        existing = _latest_inspection_row(conn, vehicle_id)
        if existing is None:
            conn.execute(
                """
                INSERT INTO inspections (vehicle_id, status, summary, report_json, created_at)
                VALUES (?, 'IN_PROGRESS', '', ?, ?)
                """,
                (vehicle_id, report, stamp),
            )
        elif existing["status"] != "IN_PROGRESS":
            conn.execute(
                """
                INSERT INTO inspections (vehicle_id, status, summary, report_json, created_at)
                VALUES (?, 'IN_PROGRESS', '', ?, ?)
                """,
                (vehicle_id, existing["report_json"] or report, stamp),
            )
        conn.execute(
            "UPDATE vehicles SET status = 'INSPECTION_IN_PROGRESS', updated_at = ? WHERE id = ?",
            (stamp, vehicle_id),
        )
        conn.execute(
            "UPDATE marketplace_appointments SET status = 'INSPECTION_IN_PROGRESS' WHERE id = (SELECT appointment_id FROM vehicles WHERE id = ?)",
            (vehicle_id,),
        )
    return get_vehicle(vehicle_id, db_path)


def save_inspection(
    vehicle_id: int,
    report: dict[str, Any] | None = None,
    summary: str = "",
    notes: str = "",
    finalize: bool = False,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    stamp = now_iso(now)
    normalized = normalize_report(report)
    text = (summary or normalized.get("summary") or "").strip()
    payload = json.dumps(normalized, ensure_ascii=False)
    with get_conn(db_path) as conn:
        row = _latest_inspection_row(conn, vehicle_id)
        if row is None:
            conn.execute(
                """
                INSERT INTO inspections (vehicle_id, status, summary, notes, report_json, created_at)
                VALUES (?, 'IN_PROGRESS', ?, ?, ?, ?)
                """,
                (vehicle_id, text, notes, payload, stamp),
            )
        else:
            conn.execute(
                """
                UPDATE inspections SET summary = ?, notes = ?, report_json = ?
                WHERE id = ?
                """,
                (text or row["summary"], notes if notes else row["notes"], payload, row["id"]),
            )
            vehicle = conn.execute(
                "SELECT status, published_for_bidding FROM vehicles WHERE id = ?",
                (vehicle_id,),
            ).fetchone()
            if vehicle and not vehicle["published_for_bidding"] and vehicle["status"] not in {"BIDDING_ACTIVE", "SOLD", "CANCELLED"}:
                conn.execute(
                    "UPDATE vehicles SET status = 'INSPECTION_IN_PROGRESS', updated_at = ? WHERE id = ?",
                    (stamp, vehicle_id),
                )
    if finalize:
        return finalize_inspection(vehicle_id, text, report=normalized, db_path=db_path, now=now)
    return get_vehicle(vehicle_id, db_path)


def finalize_inspection(
    vehicle_id: int,
    summary: str = "",
    report: dict[str, Any] | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    stamp = now_iso(now)
    normalized = normalize_report(report) if report is not None else None
    text = (summary or (normalized or {}).get("summary") or "").strip()
    with get_conn(db_path) as conn:
        row = _latest_inspection_row(conn, vehicle_id)
        if row is None:
            conn.execute(
                """
                INSERT INTO inspections (vehicle_id, status, summary, report_json, finalized_at, created_at)
                VALUES (?, 'COMPLETED', ?, ?, ?, ?)
                """,
                (vehicle_id, text, json.dumps(normalized or empty_report(), ensure_ascii=False), stamp, stamp),
            )
        else:
            stored = normalize_report(normalized or _json_obj(row["report_json"]))
            conn.execute(
                """
                UPDATE inspections SET status = 'COMPLETED', summary = ?, report_json = ?, finalized_at = ?
                WHERE id = ?
                """,
                (text or row["summary"], json.dumps(stored, ensure_ascii=False), stamp, row["id"]),
            )
            normalized = stored
        strengths = json.dumps((normalized or empty_report()).get("strengths") or [], ensure_ascii=False)
        conn.execute(
            """
            UPDATE vehicles SET status = 'PENDING_OFFICE_APPROVAL', inspection_completed = 1,
                inspection_summary = COALESCE(NULLIF(?, ''), inspection_summary),
                strengths = CASE WHEN strengths IN ('', '[]') THEN ? ELSE strengths END,
                updated_at = ?
            WHERE id = ?
            """,
            (text, strengths, stamp, vehicle_id),
        )
        conn.execute(
            "UPDATE marketplace_appointments SET status = 'INSPECTION_COMPLETED' WHERE id = (SELECT appointment_id FROM vehicles WHERE id = ?)",
            (vehicle_id,),
        )
    return get_vehicle(vehicle_id, db_path)


def approve_vehicle(vehicle_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    vehicle = get_vehicle(vehicle_id, db_path)
    if not vehicle["inspection_completed"]:
        raise MarketplaceError("اول کارشناسی باید تمام شود.", 409)
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE vehicles SET status = 'READY_FOR_BIDDING', office_approved = 1, updated_at = ? WHERE id = ?",
            (stamp, vehicle_id),
        )
        bump_live(conn)
    return get_vehicle(vehicle_id, db_path)


def _eligible_buyers(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM buyer_profiles WHERE status = 'ACTIVE' AND verification_status = 'VERIFIED'"
        ).fetchall()
    return [dict(row) for row in rows]


def publish_vehicle(
    vehicle_id: int,
    duration_seconds: int = DEFAULT_DURATION_SECONDS,
    increment: int = DEFAULT_INCREMENT,
    participant_policy: str = "ALL_VERIFIED_BUYERS",
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    vehicle = get_vehicle(vehicle_id, db_path)
    if not vehicle["inspection_completed"] or not vehicle["office_approved"]:
        raise MarketplaceError("خودرو باید کارشناسی شده و تأیید دفتر باشد.", 409)
    stamp = parse_dt(now)
    start = stamp
    end = stamp + timedelta(seconds=int(duration_seconds))
    starting = int(vehicle.get("starting_price") or 0)
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE vehicles SET status = 'BIDDING_ACTIVE', published_for_bidding = 1, office_approved = 1, updated_at = ?
            WHERE id = ?
            """,
            (stamp.isoformat(timespec="seconds"), vehicle_id),
        )
        cur = conn.execute(
            """
            INSERT INTO auctions (
                vehicle_id, status, start_time, end_time, starting_price, reserve_price, bid_increment,
                current_price, published_at, participant_policy, created_at, updated_at
            ) VALUES (?, 'ACTIVE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle_id,
                start.isoformat(timespec="seconds"),
                end.isoformat(timespec="seconds"),
                starting,
                vehicle.get("reserve_price"),
                increment,
                starting,
                stamp.isoformat(timespec="seconds"),
                participant_policy,
                stamp.isoformat(timespec="seconds"),
                stamp.isoformat(timespec="seconds"),
            ),
        )
        auction_id = int(cur.lastrowid)
        bump_live(conn)
    invite_buyers(auction_id, vehicle_id, participant_policy, db_path=db_path, now=stamp)
    return get_auction(auction_id, db_path)


def invite_buyers(auction_id: int, vehicle_id: int, policy: str, db_path: Path | None = None, now: datetime | str | None = None) -> list[dict[str, Any]]:
    vehicle = get_vehicle(vehicle_id, db_path)
    invited = []
    stamp = now_iso(now)
    for buyer in _eligible_buyers(db_path):
        prefs = get_preferences(buyer["id"], db_path)
        score = match_score(vehicle, prefs)
        if policy == "MATCHED_BUYERS_ONLY" and score < MATCH_THRESHOLD:
            continue
        with get_conn(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO auction_participants (auction_id, buyer_id, match_score, invited_at, status)
                VALUES (?, ?, ?, ?, 'INVITED')
                """,
                (auction_id, buyer["id"], score, stamp),
            )
        notify(
            buyer["user_id"],
            "VEHICLE_PUBLISHED",
            "خودروی جدید برای مزایده",
            f"{vehicle.get('brand')} {vehicle.get('model')} — مزایده شروع شد.",
            {"auction_id": auction_id, "vehicle_id": vehicle_id, "match_score": score},
            db_path=db_path,
            now=now,
        )
        notify(buyer["user_id"], "AUCTION_STARTED", "مزایده شروع شد", "", {"auction_id": auction_id}, db_path=db_path, now=now)
        invited.append({"buyer_id": buyer["id"], "match_score": score})
    return invited


def get_auction(auction_id: int, db_path: Path | None = None) -> dict[str, Any]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
    if row is None:
        raise MarketplaceError("مزایده پیدا نشد.", 404)
    return dict(row)


def auction_for_vehicle(vehicle_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM auctions
            WHERE vehicle_id = ? AND status != 'CANCELLED'
            ORDER BY id DESC LIMIT 1
            """,
            (vehicle_id,),
        ).fetchone()
    return _row(row)


def collect_maxes(conn, auction_id: int) -> list[tuple[int, int, str]]:
    limits = conn.execute(
        "SELECT buyer_id, max_bid, created_at FROM auto_bid_limits WHERE auction_id = ? AND status = 'ACTIVE'",
        (auction_id,),
    ).fetchall()
    manuals = conn.execute(
        """
        SELECT buyer_id, MAX(amount) AS amount, MIN(created_at) AS created_at
        FROM bids WHERE auction_id = ? AND status = 'ACCEPTED' AND bid_type = 'MANUAL'
        GROUP BY buyer_id
        """,
        (auction_id,),
    ).fetchall()
    by_buyer: dict[int, tuple[int, int, str]] = {}
    for row in manuals:
        by_buyer[int(row["buyer_id"])] = (int(row["buyer_id"]), int(row["amount"]), row["created_at"])
    for row in limits:
        buyer_id = int(row["buyer_id"])
        current = by_buyer.get(buyer_id)
        max_bid = int(row["max_bid"])
        if current is None or max_bid > current[1]:
            by_buyer[buyer_id] = (buyer_id, max_bid, row["created_at"])
    return list(by_buyer.values())


def _record_bid(conn, auction_id: int, buyer_id: int, amount: int, bid_type: str, request_id: str | None, created: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO bids (auction_id, buyer_id, amount, bid_type, created_at, status, request_id)
        VALUES (?, ?, ?, ?, ?, 'ACCEPTED', ?)
        """,
        (auction_id, buyer_id, amount, bid_type, created, request_id),
    )
    conn.execute("UPDATE buyer_profiles SET total_bids = total_bids + 1 WHERE id = ?", (buyer_id,))
    return int(cur.lastrowid)


def _existing_request(conn, request_id: str | None) -> dict[str, Any] | None:
    if not request_id:
        return None
    row = conn.execute("SELECT * FROM bids WHERE request_id = ?", (request_id,)).fetchone()
    return _row(row)


def _apply_resolution(conn, auction: dict[str, Any], created: str) -> dict[str, Any]:
    maxes = collect_maxes(conn, auction["id"])
    step = live_increment(int(auction["current_price"]), auction.get("bid_increment"))
    winner_id, price = resolve_price(int(auction["starting_price"]), step, maxes)
    previous_price = int(auction["current_price"])
    previous_winner = auction.get("current_winner_id")
    conn.execute(
        "UPDATE auctions SET current_price = ?, current_winner_id = ?, updated_at = ? WHERE id = ?",
        (price, winner_id, created, auction["id"]),
    )
    if winner_id is not None and (price != previous_price or winner_id != previous_winner):
        exists = conn.execute(
            "SELECT id FROM bids WHERE auction_id = ? AND buyer_id = ? AND amount = ? AND bid_type IN ('AUTO', 'SYSTEM')",
            (auction["id"], winner_id, price),
        ).fetchone()
        if exists is None and price != previous_price:
            _record_bid(conn, auction["id"], winner_id, price, "AUTO", None, created)
    auction["current_price"] = price
    auction["current_winner_id"] = winner_id
    return auction


def _ensure_participant(conn, auction: dict[str, Any], buyer: dict[str, Any], created: str) -> None:
    row = conn.execute(
        "SELECT * FROM auction_participants WHERE auction_id = ? AND buyer_id = ?",
        (auction["id"], buyer["id"]),
    ).fetchone()
    if row and row["status"] in {"REMOVED", "BLOCKED"}:
        raise MarketplaceError("شما مجاز به شرکت در این مزایده نیستید.", 403)
    if row is None:
        if auction.get("participant_policy") == "MATCHED_BUYERS_ONLY":
            raise MarketplaceError("شما به این مزایده دعوت نشده‌اید.", 403)
        conn.execute(
            """
            INSERT INTO auction_participants (auction_id, buyer_id, match_score, invited_at, joined_at, status)
            VALUES (?, ?, 50, ?, ?, 'ACTIVE')
            """,
            (auction["id"], buyer["id"], created, created),
        )
    elif row["joined_at"] is None or row["status"] == "INVITED":
        conn.execute(
            "UPDATE auction_participants SET joined_at = ?, status = 'ACTIVE' WHERE id = ?",
            (created, row["id"]),
        )


def close_if_expired(auction_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    stamp = parse_dt(now)
    with get_conn(db_path, immediate=True) as conn:
        row = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
        if row is None:
            raise MarketplaceError("مزایده پیدا نشد.", 404)
        auction = dict(row)
        if auction["status"] != "ACTIVE":
            return auction
        if parse_dt(auction["end_time"]) > stamp:
            return auction
        _finish_auction(conn, auction, stamp.isoformat(timespec="seconds"), db_path)
        return dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())


def _finish_auction(conn, auction: dict[str, Any], created: str, db_path: Path | None = None) -> None:
    winner_id = auction.get("current_winner_id")
    price = int(auction["current_price"])
    met = 1 if reserve_met(price, auction.get("reserve_price")) else 0
    conn.execute("UPDATE auctions SET status = 'ENDED', updated_at = ? WHERE id = ?", (created, auction["id"]))
    conn.execute(
        "UPDATE vehicles SET status = 'BIDDING_ENDED', updated_at = ? WHERE id = ?",
        (created, auction["vehicle_id"]),
    )
    bump_live(conn)
    if winner_id:
        conn.execute(
            """
            INSERT OR IGNORE INTO auction_winners (auction_id, buyer_id, final_price, reserve_met, status, created_at)
            VALUES (?, ?, ?, ?, 'PENDING_OFFICE_CONFIRMATION', ?)
            """,
            (auction["id"], winner_id, price, met, created),
        )
        buyer = conn.execute("SELECT * FROM buyer_profiles WHERE id = ?", (winner_id,)).fetchone()
        if buyer:
            notify(buyer["user_id"], "YOU_WON" if met else "AUCTION_ENDED", "مزایده تمام شد", "", {"auction_id": auction["id"], "reserve_met": bool(met)}, db_path=db_path, conn=conn)
            conn.execute("UPDATE buyer_profiles SET winning_bids = winning_bids + 1 WHERE id = ?", (winner_id,))
        others = conn.execute(
            "SELECT DISTINCT buyer_id FROM bids WHERE auction_id = ? AND buyer_id != ?",
            (auction["id"], winner_id),
        ).fetchall()
        for other in others:
            profile = conn.execute("SELECT user_id FROM buyer_profiles WHERE id = ?", (other["buyer_id"],)).fetchone()
            if profile:
                notify(profile["user_id"], "YOU_LOST", "مزایده را از دست دادید", "", {"auction_id": auction["id"]}, db_path=db_path, conn=conn)
    else:
        users = conn.execute(
            "SELECT user_id FROM buyer_profiles WHERE id IN (SELECT buyer_id FROM auction_participants WHERE auction_id = ?)",
            (auction["id"],),
        ).fetchall()
        for user in users:
            notify(user["user_id"], "AUCTION_ENDED", "مزایده بدون برنده تمام شد", "", {"auction_id": auction["id"]}, db_path=db_path, conn=conn)


def place_manual_bid(
    auction_id: int,
    buyer: dict[str, Any],
    amount: int,
    request_id: str | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    if not can_bid(buyer):
        raise MarketplaceError("فقط خریدار فعال و تأییدشده می‌تواند پیشنهاد بدهد.", 403)
    stamp = parse_dt(now)
    created = stamp.isoformat(timespec="seconds")
    with get_conn(db_path, immediate=True) as conn:
        existing = _existing_request(conn, request_id)
        if existing:
            return {"ok": True, "duplicate": True, "bid": existing, "auction": dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())}
        row = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
        if row is None:
            raise MarketplaceError("مزایده پیدا نشد.", 404)
        auction = dict(row)
        if auction["status"] != "ACTIVE":
            raise MarketplaceError("این مزایده فعال نیست.", 409)
        if parse_dt(auction["end_time"]) <= stamp:
            _finish_auction(conn, auction, created, db_path)
            raise MarketplaceError("مزایده تمام شده است.", 409)
        _ensure_participant(conn, auction, buyer, created)
        has_winner = auction.get("current_winner_id") is not None
        current = int(auction["current_price"])
        step = live_increment(current, auction.get("bid_increment"))
        minimum = current if not has_winner else current + step
        if int(amount) < minimum:
            raise MarketplaceError(f"پیشنهاد باید حداقل {minimum} باشد.", 409)
        bid_id = _record_bid(conn, auction_id, buyer["id"], int(amount), "MANUAL", request_id, created)
        previous_winner = auction.get("current_winner_id")
        auction = _apply_resolution(conn, auction, created)
        if should_extend(stamp, parse_dt(auction["end_time"]), bool(auction["anti_sniping_enabled"]), int(auction["extension_window_seconds"]), int(auction["extensions_used"]), int(auction["maximum_extensions"])):
            new_end = extend_end(parse_dt(auction["end_time"]), int(auction["extension_seconds"]))
            conn.execute(
                "UPDATE auctions SET end_time = ?, extensions_used = extensions_used + 1, updated_at = ? WHERE id = ?",
                (new_end.isoformat(timespec="seconds"), created, auction_id),
            )
            auction["end_time"] = new_end.isoformat(timespec="seconds")
        if previous_winner and auction.get("current_winner_id") != previous_winner:
            prev = conn.execute("SELECT user_id FROM buyer_profiles WHERE id = ?", (previous_winner,)).fetchone()
            if prev:
                notify(prev["user_id"], "OUTBID", "پیشنهاد شما بالاتر زده شد", "", {"auction_id": auction_id}, db_path=db_path, conn=conn)
        notify(buyer["user_id"], "BID_PLACED", "پیشنهاد ثبت شد", "", {"auction_id": auction_id, "amount": int(amount)}, db_path=db_path, conn=conn)
        bid = dict(conn.execute("SELECT * FROM bids WHERE id = ?", (bid_id,)).fetchone())
        auction = dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())
        bump_live(conn)
    return {"ok": True, "bid": bid, "auction": auction}


def set_auto_bid(
    auction_id: int,
    buyer: dict[str, Any],
    max_bid: int,
    request_id: str | None = None,
    db_path: Path | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    if not can_bid(buyer):
        raise MarketplaceError("فقط خریدار فعال و تأییدشده می‌تواند پیشنهاد خودکار بگذارد.", 403)
    stamp = parse_dt(now)
    created = stamp.isoformat(timespec="seconds")
    with get_conn(db_path, immediate=True) as conn:
        existing = _existing_request(conn, request_id)
        if existing:
            return {"ok": True, "duplicate": True, "bid": existing, "auction": dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())}
        row = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
        if row is None:
            raise MarketplaceError("مزایده پیدا نشد.", 404)
        auction = dict(row)
        if auction["status"] != "ACTIVE":
            raise MarketplaceError("این مزایده فعال نیست.", 409)
        if parse_dt(auction["end_time"]) <= stamp:
            _finish_auction(conn, auction, created, db_path)
            raise MarketplaceError("مزایده تمام شده است.", 409)
        _ensure_participant(conn, auction, buyer, created)
        minimum = int(auction["current_price"])
        if int(max_bid) < minimum:
            raise MarketplaceError("سقف پیشنهاد از قیمت فعلی کمتر است.", 409)
        conn.execute(
            """
            INSERT INTO auto_bid_limits (auction_id, buyer_id, max_bid, status, created_at, updated_at)
            VALUES (?, ?, ?, 'ACTIVE', ?, ?)
            ON CONFLICT(auction_id, buyer_id) DO UPDATE SET max_bid = excluded.max_bid, status = 'ACTIVE', updated_at = excluded.updated_at
            """,
            (auction_id, buyer["id"], int(max_bid), created, created),
        )
        previous_winner = auction.get("current_winner_id")
        previous_price = int(auction["current_price"])
        auction = _apply_resolution(conn, auction, created)
        if should_extend(stamp, parse_dt(auction["end_time"]), bool(auction["anti_sniping_enabled"]), int(auction["extension_window_seconds"]), int(auction["extensions_used"]), int(auction["maximum_extensions"])) and auction["current_price"] != previous_price:
            new_end = extend_end(parse_dt(auction["end_time"]), int(auction["extension_seconds"]))
            conn.execute(
                "UPDATE auctions SET end_time = ?, extensions_used = extensions_used + 1, updated_at = ? WHERE id = ?",
                (new_end.isoformat(timespec="seconds"), created, auction_id),
            )
        if previous_winner and auction.get("current_winner_id") != previous_winner:
            prev = conn.execute("SELECT user_id FROM buyer_profiles WHERE id = ?", (previous_winner,)).fetchone()
            if prev:
                notify(prev["user_id"], "OUTBID", "پیشنهاد شما بالاتر زده شد", "", {"auction_id": auction_id}, db_path=db_path, conn=conn)
        if request_id and _existing_request(conn, request_id) is None:
            _record_bid(conn, auction_id, buyer["id"], int(auction["current_price"]), "AUTO", request_id, created)
        auction = dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())
        limit = dict(
            conn.execute(
                "SELECT id, auction_id, buyer_id, status, created_at, updated_at FROM auto_bid_limits WHERE auction_id = ? AND buyer_id = ?",
                (auction_id, buyer["id"]),
            ).fetchone()
        )
        limit["has_max"] = True
        bump_live(conn)
    return {"ok": True, "auto_bid": limit, "auction": auction}


def clear_auto_bid(auction_id: int, buyer: dict[str, Any], db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    created = now_iso(now)
    with get_conn(db_path, immediate=True) as conn:
        conn.execute(
            "UPDATE auto_bid_limits SET status = 'CANCELLED', updated_at = ? WHERE auction_id = ? AND buyer_id = ?",
            (created, auction_id, buyer["id"]),
        )
        row = conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone()
        if row and row["status"] == "ACTIVE":
            _apply_resolution(conn, dict(row), created)
        auction = dict(conn.execute("SELECT * FROM auctions WHERE id = ?", (auction_id,)).fetchone())
    return {"ok": True, "auction": auction}


def list_bids(auction_id: int, viewer_buyer_id: int | None = None, office: bool = False, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM bids WHERE auction_id = ? ORDER BY id ASC", (auction_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if office:
            out.append(item)
        else:
            out.append(public_bid(item, viewer_buyer_id))
    return out


def my_auto_bid(auction_id: int, buyer_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM auto_bid_limits WHERE auction_id = ? AND buyer_id = ?",
            (auction_id, buyer_id),
        ).fetchone()
    return _row(row)


def buyer_visible_auctions(buyer: dict[str, Any], db_path: Path | None = None, now: datetime | str | None = None) -> list[dict[str, Any]]:
    stamp = now_iso(now)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT auctions.* FROM auctions
            JOIN vehicles ON vehicles.id = auctions.vehicle_id
            WHERE auctions.status = 'ACTIVE' AND vehicles.status = 'BIDDING_ACTIVE'
              AND auctions.end_time > ?
            ORDER BY auctions.end_time ASC
            """,
            (stamp,),
        ).fetchall()
    visible = []
    for row in rows:
        auction = dict(row)
        if not buyer_may_see_auction(buyer, auction, db_path):
            continue
        vehicle = get_vehicle(auction["vehicle_id"], db_path)
        visible.append(public_vehicle(vehicle, auction))
    return visible


def buyer_may_see_auction(buyer: dict[str, Any], auction: dict[str, Any], db_path: Path | None = None) -> bool:
    if auction.get("participant_policy") != "MATCHED_BUYERS_ONLY":
        return True
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM auction_participants WHERE auction_id = ? AND buyer_id = ?",
            (auction["id"], buyer["id"]),
        ).fetchone()
    return bool(row) and row["status"] not in {"REMOVED", "BLOCKED"}


def buyer_auction_detail(auction_id: int, buyer: dict[str, Any], db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    close_if_expired(auction_id, db_path=db_path, now=now)
    auction = get_auction(auction_id, db_path)
    vehicle = get_vehicle(auction["vehicle_id"], db_path)
    if not buyer_can_see_vehicle(vehicle, auction) or not buyer_may_see_auction(buyer, auction, db_path):
        raise MarketplaceError("این مزایده برای شما قابل مشاهده نیست.", 404)
    payload = public_vehicle(vehicle, auction)
    payload["bids"] = list_bids(auction_id, viewer_buyer_id=buyer["id"], db_path=db_path)
    mine = my_auto_bid(auction_id, buyer["id"], db_path)
    payload["my_auto_bid"] = {"active": bool(mine and mine["status"] == "ACTIVE")} if mine else {"active": False}
    payload["i_am_winning"] = auction.get("current_winner_id") == buyer["id"]
    return payload


def buyer_bid_history(buyer_id: int, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM bids WHERE buyer_id = ? ORDER BY id DESC", (buyer_id,)).fetchall()
    return [dict(row) for row in rows]


def buyer_auction_history(buyer_id: int, db_path: Path | None = None) -> dict[str, Any]:
    with get_conn(db_path) as conn:
        active = conn.execute(
            """
            SELECT DISTINCT auctions.id FROM auctions
            JOIN bids ON bids.auction_id = auctions.id
            WHERE bids.buyer_id = ? AND auctions.status = 'ACTIVE'
            """,
            (buyer_id,),
        ).fetchall()
        won = conn.execute("SELECT * FROM auction_winners WHERE buyer_id = ?", (buyer_id,)).fetchall()
        lost = conn.execute(
            """
            SELECT auctions.id FROM auctions
            JOIN bids ON bids.auction_id = auctions.id
            WHERE bids.buyer_id = ? AND auctions.status = 'ENDED'
              AND auctions.current_winner_id != ?
            GROUP BY auctions.id
            """,
            (buyer_id, buyer_id),
        ).fetchall()
    return {
        "active": [row["id"] for row in active],
        "winning": [dict(row) for row in won],
        "lost": [row["id"] for row in lost],
    }


def cancel_auction(auction_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    created = now_iso(now)
    auction = get_auction(auction_id, db_path)
    with get_conn(db_path) as conn:
        vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (auction["vehicle_id"],)).fetchone()
        if vehicle and vehicle["inspection_completed"] and vehicle["office_approved"]:
            next_status = "READY_FOR_BIDDING"
        elif vehicle and vehicle["inspection_completed"]:
            next_status = "PENDING_OFFICE_APPROVAL"
        else:
            next_status = "APPOINTMENT_SCHEDULED"
        conn.execute("UPDATE auctions SET status = 'CANCELLED', updated_at = ? WHERE id = ?", (created, auction_id))
        conn.execute(
            "UPDATE auto_bid_limits SET status = 'CANCELLED', updated_at = ? WHERE auction_id = ?",
            (created, auction_id),
        )
        conn.execute(
            """
            UPDATE vehicles SET status = ?, published_for_bidding = 0, updated_at = ?
            WHERE id = ?
            """,
            (next_status, created, auction["vehicle_id"]),
        )
        bump_live(conn)
    return get_auction(auction_id, db_path)


def set_auction_status(auction_id: int, status: str, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    if status == "CANCELLED":
        return cancel_auction(auction_id, db_path=db_path, now=now)
    created = now_iso(now)
    auction = get_auction(auction_id, db_path)
    vehicle_status = {
        "ENDED": "BIDDING_ENDED",
        "ACTIVE": "BIDDING_ACTIVE",
        "SCHEDULED": "READY_FOR_BIDDING",
    }.get(status)
    with get_conn(db_path) as conn:
        conn.execute("UPDATE auctions SET status = ?, updated_at = ? WHERE id = ?", (status, created, auction_id))
        if vehicle_status:
            conn.execute("UPDATE vehicles SET status = ?, updated_at = ? WHERE id = ?", (vehicle_status, created, auction["vehicle_id"]))
        bump_live(conn)
    return get_auction(auction_id, db_path)


def accept_winner(auction_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    created = now_iso(now)
    auction = close_if_expired(auction_id, db_path=db_path, now=now)
    if auction["status"] == "ACTIVE":
        with get_conn(db_path, immediate=True) as conn:
            _finish_auction(conn, auction, created, db_path)
    with get_conn(db_path) as conn:
        winner = conn.execute("SELECT * FROM auction_winners WHERE auction_id = ?", (auction_id,)).fetchone()
        if winner is None:
            raise MarketplaceError("برنده‌ای ثبت نشده است.", 409)
        if not winner["reserve_met"]:
            raise MarketplaceError("قیمت رزرو تأمین نشده؛ فروش خودکار ممکن نیست.", 409)
        conn.execute("UPDATE auction_winners SET status = 'ACCEPTED' WHERE auction_id = ?", (auction_id,))
        conn.execute("UPDATE vehicles SET status = 'SOLD', updated_at = ? WHERE id = ?", (created, auction["vehicle_id"]))
        buyer = conn.execute("SELECT * FROM buyer_profiles WHERE id = ?", (winner["buyer_id"],)).fetchone()
        if buyer:
            conn.execute("UPDATE buyer_profiles SET completed_transactions = completed_transactions + 1 WHERE id = ?", (buyer["id"],))
            notify(buyer["user_id"], "OFFICE_ACCEPTED", "دفتر برنده را تأیید کرد", "", {"auction_id": auction_id}, db_path=db_path)
        return dict(conn.execute("SELECT * FROM auction_winners WHERE auction_id = ?", (auction_id,)).fetchone())


def reject_winner(auction_id: int, db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    created = now_iso(now)
    with get_conn(db_path) as conn:
        winner = conn.execute("SELECT * FROM auction_winners WHERE auction_id = ?", (auction_id,)).fetchone()
        if winner is None:
            raise MarketplaceError("برنده‌ای ثبت نشده است.", 409)
        conn.execute("UPDATE auction_winners SET status = 'REJECTED' WHERE auction_id = ?", (auction_id,))
        conn.execute("UPDATE vehicles SET status = 'BIDDING_ENDED', updated_at = ? WHERE id = ?", (created, get_auction(auction_id, db_path)["vehicle_id"]))
        buyer = conn.execute("SELECT * FROM buyer_profiles WHERE id = ?", (winner["buyer_id"],)).fetchone()
        if buyer:
            conn.execute("UPDATE buyer_profiles SET cancelled_transactions = cancelled_transactions + 1 WHERE id = ?", (buyer["id"],))
            notify(buyer["user_id"], "OFFICE_REJECTED", "دفتر برنده را رد کرد", "", {"auction_id": auction_id}, db_path=db_path)
        return dict(conn.execute("SELECT * FROM auction_winners WHERE auction_id = ?", (auction_id,)).fetchone())


def office_dashboard(db_path: Path | None = None, now: datetime | str | None = None) -> dict[str, Any]:
    for auction in list_auctions(db_path):
        if auction["status"] == "ACTIVE":
            close_if_expired(auction["id"], db_path=db_path, now=now)
    return {
        "appointments": office_appointments(db_path),
        "vehicles": list_vehicles(db_path),
        "auctions": list_auctions(db_path),
        "winners": list_winners(db_path),
        "buyers": list_buyers(db_path),
    }


def list_auctions(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM auctions ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def list_winners(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM auction_winners ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def list_buyers(db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM buyer_profiles ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def list_participants(auction_id: int, db_path: Path | None = None) -> list[dict[str, Any]]:
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM auction_participants WHERE auction_id = ? ORDER BY match_score DESC", (auction_id,)).fetchall()
    return [dict(row) for row in rows]


def get_winner(auction_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with get_conn(db_path) as conn:
        return _row(conn.execute("SELECT * FROM auction_winners WHERE auction_id = ?", (auction_id,)).fetchone())
