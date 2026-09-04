"""Send calendar and follow-up texts from the software WhatsApp line."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .booking import DEFAULT_WHATSAPP, whatsapp_digits

SOFTWARE_WHATSAPP = DEFAULT_WHATSAPP
CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "whatsapp.json"


def software_number() -> str:
    raw = os.environ.get("WHATSAPP_FROM") or SOFTWARE_WHATSAPP
    digits = whatsapp_digits(raw)
    return f"+{digits}" if digits else SOFTWARE_WHATSAPP


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cfg(*names: str) -> str:
    file_cfg = load_config()
    for name in names:
        value = os.environ.get(name) or file_cfg.get(name) or ""
        if str(value).strip():
            return str(value).strip()
    return ""


def public_origin(origin: str = "", invite: dict[str, Any] | None = None) -> str:
    env = (os.environ.get("PUBLIC_BASE_URL") or load_config().get("public_base_url") or "").strip()
    if env:
        return str(env).rstrip("/")
    if origin:
        return origin.rstrip("/")
    if invite and invite.get("public_origin"):
        return str(invite["public_origin"]).rstrip("/")
    return "http://127.0.0.1:8000"


def calendar_text(invite: dict[str, Any], calendar_url: str) -> str:
    return (
        f"سلام {invite['customer_name']} عزیز\n"
        f"برای بازدید و خرید {invite['car_name']} {invite['car_model']} "
        f"این لینک تقویم نوبت‌های خالی است:\n{calendar_url}\n"
        "لطفاً وقت آزاد را انتخاب کنید و ثبت را تأیید کنید."
    )


def reminder_text(invite: dict[str, Any], calendar_url: str) -> str:
    return (
        f"سلام {invite['customer_name']} عزیز\n"
        "یادآوری نوبت بازدید: هنوز وقت خود را از تقویم انتخاب و تأیید نکرده‌اید.\n"
        f"برای {invite['car_name']} {invite['car_model']}:\n"
        f"{calendar_url}\n"
        "لطفاً وقت آزاد را انتخاب کنید و ثبت را تأیید کنید."
    )


def attach_message(
    invite: dict[str, Any] | None,
    origin: str = "",
    kind: str = "invite",
) -> dict[str, Any] | None:
    if not invite:
        return None
    extra = dict(invite)
    calendar_url = f"{public_origin(origin, extra)}{extra.get('calendar_path') or '/book/' + extra['token']}"
    extra["from_number"] = software_number()
    extra["calendar_url"] = calendar_url
    extra["call_url"] = f"tel:{extra.get('phone') or software_number()}"
    if kind == "reminder":
        extra["whatsapp_text"] = reminder_text(extra, calendar_url)
        extra["reminder_number"] = int(extra.get("reminder_count") or 0) + 1
    else:
        extra["whatsapp_text"] = calendar_text(extra, calendar_url)
    return extra


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[bool, str]:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return _read_response(request)


def _post_form(url: str, payload: dict[str, Any]) -> tuple[bool, str]:
    raw = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST")
    return _read_response(request)


def _read_response(request: urllib.request.Request) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            ok = 200 <= getattr(response, "status", 200) < 300
            return ok, body
    except urllib.error.HTTPError as extra:
        err = extra.read().decode("utf-8", errors="replace")
        return False, err or str(extra)
    except Exception as extra:
        return False, str(extra)


def send_text(to: str | None, text: str) -> dict[str, Any]:
    """Push a WhatsApp text from the software line to the customer."""
    dest = whatsapp_digits(to or software_number())
    source = whatsapp_digits(software_number())
    result = {
        "from": f"+{source}" if source else software_number(),
        "to": f"+{dest}" if dest else "",
        "provider": None,
        "ok": False,
        "error": "",
    }
    if not dest:
        result["error"] = "شماره مشتری خالی است."
        return result
    if not (text or "").strip():
        result["error"] = "متن پیام خالی است."
        return result

    ultramsg_id = _cfg("ULTRAMSG_INSTANCE", "ultramsg_instance")
    ultramsg_token = _cfg("ULTRAMSG_TOKEN", "ultramsg_token")
    if ultramsg_id and ultramsg_token:
        ok, body = _post_form(
            f"https://api.ultramsg.com/{ultramsg_id}/messages/chat",
            {"token": ultramsg_token, "to": f"+{dest}", "body": text},
        )
        result["provider"] = "ultramsg"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال اولترا ناموفق بود.")
        return result

    green_id = _cfg("GREEN_API_INSTANCE", "green_api_instance")
    green_token = _cfg("GREEN_API_TOKEN", "green_api_token")
    if green_id and green_token:
        ok, body = _post_json(
            f"https://api.green-api.com/waInstance{green_id}/sendMessage/{green_token}",
            {"chatId": f"{dest}@c.us", "message": text},
        )
        result["provider"] = "green-api"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال گرین ناموفق بود.")
        return result

    cloud_token = _cfg("WHATSAPP_TOKEN", "cloud_token")
    phone_id = _cfg("WHATSAPP_PHONE_NUMBER_ID", "cloud_phone_id")
    if cloud_token and phone_id:
        ok, body = _post_json(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            {
                "messaging_product": "whatsapp",
                "to": dest,
                "type": "text",
                "text": {"preview_url": True, "body": text},
            },
            headers={"Authorization": f"Bearer {cloud_token}"},
        )
        result["provider"] = "cloud"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال کلاد ناموفق بود.")
        return result

    webhook = _cfg("WHATSAPP_API_URL", "api_url")
    if webhook:
        ok, body = _post_json(
            webhook,
            {"from": result["from"], "to": result["to"], "text": text},
        )
        result["provider"] = "webhook"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال وب‌هوک ناموفق بود.")
        return result

    result["error"] = "واتساپ نرم‌افزار برای ارسال خودکار تنظیم نشده است."
    return result
