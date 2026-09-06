"""OpenAI Realtime (GA) voice-agent helpers for Persian dealership booking."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable

from .cars import catalog_payload
from .dialogue import DialogueManager

DEFAULT_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime")
DEFAULT_VOICE = os.environ.get("OPENAI_REALTIME_VOICE", "alloy")
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
_PLACEHOLDER_KEYS = {"sk-...", "sk-xxx", "your-key", "changeme", "replace-me"}


def api_key() -> str:
    raw = (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY") or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    lowered = raw.lower()
    if raw in _PLACEHOLDER_KEYS or lowered in _PLACEHOLDER_KEYS:
        return ""
    # Real OpenAI secret keys are long (sk-... / sk-proj-...).
    if len(raw) < 40 or not raw.startswith("sk-"):
        return ""
    if raw.endswith("_KEY") or "YOUR" in raw.upper() or "REAL" in raw.upper() or "REPLACE" in raw.upper():
        return ""
    return raw


def is_configured() -> bool:
    return bool(api_key())


def status_payload() -> dict[str, Any]:
    configured = is_configured()
    raw = (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY") or "").strip()
    if configured:
        message = "عامل صوتی ابری آماده است (OpenAI Realtime GA)."
    elif raw:
        message = (
            "کلید OPENAI_API_KEY نامعتبر است (مثلاً sk-... نمونه). "
            "یک کلید واقعی از platform.openai.com بگذارید."
        )
    else:
        message = "کلید OPENAI_API_KEY تنظیم نشده؛ تماس متنی / مدل محلی فعال است."
    return {
        "enabled": configured,
        "provider": "openai_realtime" if configured else None,
        "model": DEFAULT_MODEL if configured else None,
        "voice": DEFAULT_VOICE if configured else None,
        "message": message,
    }


def system_instructions() -> str:
    cars = catalog_payload()
    brands: list[str] = []
    for item in cars[:40]:
        if isinstance(item, dict):
            name = item.get("name") or item.get("brand") or item.get("id")
            if name:
                brands.append(str(name))
        else:
            brands.append(str(item))
    brand_text = "، ".join(brands[:30]) if brands else "پژو، سمند، پراید، تیبا، دنا"
    return f"""
شما منشی تلفنی فارسی یک نمایشگاه خودرو در ایران هستید.
فقط فارسی صحبت کنید. کوتاه، مودب و واضح باشید.

هدف: گرفتن اطلاعات لازم برای رزرو نوبت بازدید خرید خودرو، سپس فرستادن لینک تقویم واتساپ.

اطلاعات لازم به ترتیب:
1) نام خودرو / برند
2) مدل
3) کیلومتر (صفر یا عدد کارکرد)
4) نام و نام خانوادگی مشتری

قوانین مهم:
- بعد از شنیدن جواب مشتری، ابزار process_customer_utterance را با همان متن مشتری صدا بزن.
- پاسخ رسمی مرحله بعد را فقط از خروجی ابزار بگیر و همان را به مشتری بگو.
- خودت نوبت نهایی ثبت نکن؛ لینک تقویم توسط سیستم ارسال می‌شود.
- اگر مشتری نامفهوم گفت، مودبانه دوباره بپرس.
- ساعات کاری: شنبه تا پنجشنبه ۹ تا ۱۷؛ جمعه تعطیل.
- خودروهای نمونه: {brand_text}
""".strip()


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "process_customer_utterance",
        "description": "متن گفته‌شده مشتری را به موتور رزرو بده و پاسخ مرحله بعد را بگیر.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "متن فارسی مشتری در این نوبت گفتار",
                }
            },
            "required": ["text"],
        },
    },
    {
        "type": "function",
        "name": "list_available_cars",
        "description": "فهرست برند/خودروهای قابل فروش را برگردان.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_office_hours",
        "description": "ساعات کاری و روزهای باز دفتر را برگردان.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def session_update_event() -> dict[str, Any]:
    """GA Realtime session.update payload (no beta fields)."""
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": DEFAULT_MODEL,
            "instructions": system_instructions(),
            "output_modalities": ["audio"],
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "gpt-4o-mini-transcribe"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 650,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": DEFAULT_VOICE,
                },
            },
        },
    }


def response_create_event(instructions: str | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {"output_modalities": ["audio"]}
    if instructions:
        response["instructions"] = instructions
    return {"type": "response.create", "response": response}


def run_tool(
    name: str,
    arguments: dict[str, Any] | str | None,
    *,
    session_id: str,
    dialogue: DialogueManager,
    origin: str = "",
    deliver_invite: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    arguments = arguments or {}

    if name == "list_available_cars":
        return {"ok": True, "cars": catalog_payload()}

    if name == "get_office_hours":
        from . import booking

        return {"ok": True, "hours": booking.hours_panel(db_path=dialogue.db_path)}

    if name == "process_customer_utterance":
        text = str(arguments.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "متن خالی بود."}
        turn = dialogue.handle(session_id, text)
        if turn.get("invite") and deliver_invite is not None and origin:
            turn = dict(turn)
            turn["invite"] = deliver_invite(turn["invite"], origin)
        reply = turn.get("reply") or ""
        return {
            "ok": True,
            "reply": reply,
            "speak": reply,
            "phase": turn.get("phase"),
            "customer": turn.get("customer") or {},
            "invite": turn.get("invite"),
            "end_call": bool(turn.get("end_call")),
            "live": turn.get("live"),
        }

    return {"ok": False, "error": f"ابزار ناشناخته: {name}"}


def openai_headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing")
    # GA Realtime: do NOT send OpenAI-Beta: realtime=v1
    return {"Authorization": f"Bearer {key}"}


def realtime_ws_url(model: str | None = None) -> str:
    chosen = model or DEFAULT_MODEL
    return f"{OPENAI_REALTIME_URL}?model={chosen}"


def humanize_openai_error(detail: str) -> str:
    text = detail or ""
    lowered = text.lower()
    if "invalid_api_key" in lowered:
        return (
            "کلید OpenAI نامعتبر است. یک کلید واقعی از "
            "https://platform.openai.com/api-keys بگذارید."
        )
    if "insufficient_quota" in lowered or "credit_balance_exhausted" in lowered or "no credits" in lowered:
        return (
            "اعتبار حساب OpenAI تمام شده است. از "
            "https://platform.openai.com/settings/organization/billing "
            "اعتبار اضافه کنید، بعد دوباره شروع تماس بزنید."
        )
    if "beta_api_shape_disabled" in lowered:
        return "نسخه قدیمی Realtime غیرفعال است؛ سرور را به نسخه GA به‌روز کنید."
    return text


def pcm16_b64(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("ascii")


def b64_to_bytes(value: str) -> bytes:
    return base64.b64decode(value)
