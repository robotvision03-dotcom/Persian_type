"""OpenAI Realtime voice-agent helpers for Persian dealership booking."""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable

from .cars import catalog_payload
from .dialogue import DialogueManager

DEFAULT_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
DEFAULT_VOICE = os.environ.get("OPENAI_REALTIME_VOICE", "alloy")
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"


def api_key() -> str:
    return (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY") or "").strip()


def is_configured() -> bool:
    return bool(api_key())


def status_payload() -> dict[str, Any]:
    configured = is_configured()
    return {
        "enabled": configured,
        "provider": "openai_realtime" if configured else None,
        "model": DEFAULT_MODEL if configured else None,
        "voice": DEFAULT_VOICE if configured else None,
        "message": (
            "عامل صوتی ابری آماده است (OpenAI Realtime)."
            if configured
            else "کلید OPENAI_API_KEY تنظیم نشده؛ تماس متنی / مدل محلی فعال است."
        ),
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
    return {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": system_instructions(),
            "voice": DEFAULT_VOICE,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 650,
            },
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",
            "temperature": 0.6,
        },
    }


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
    return {
        "Authorization": f"Bearer {key}",
        "OpenAI-Beta": "realtime=v1",
    }


def realtime_ws_url(model: str | None = None) -> str:
    chosen = model or DEFAULT_MODEL
    return f"{OPENAI_REALTIME_URL}?model={chosen}"


def pcm16_b64(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("ascii")


def b64_to_bytes(value: str) -> bytes:
    return base64.b64decode(value)
