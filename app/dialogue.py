"""Call-simulator dialogue for car-dealership appointment booking."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from . import booking
from .ollama import OllamaError, extract_answer

PHASE_ASK_CAR = "ask_car"
PHASE_ASK_MODEL = "ask_model"
PHASE_ASK_KM = "ask_km"
PHASE_ASK_NAME = "ask_name"
PHASE_ASK_SLOT = "ask_slot"
PHASE_BOOKED = "booked"

GREETING = "سلام وقت بخیر. لطفا اسم خودروی خود را بگویی."
ASK_MODEL = "مدل خودروی شما چیست؟"
ASK_KM = "کارکرد خودرو به کیلومتر."
ASK_NAME = "نام و نام خانوادگی چیست؟"
ASK_REPEAT = "متوجه نشدم. لطفا کوتاه‌تر بفرمایید."

YES_WORDS = ("بله", "آره", "اره", "باشه", "باشِ", "موافقم", "چشم", "حتما", "اوکی", "ok", "yes")
NO_WORDS = ("نه", "نخیر", "خیر", "نمیخوام", "نمی‌خوام", "no")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclass
class CallSession:
    session_id: str
    phase: str = PHASE_ASK_CAR
    car_name: str = ""
    car_model: str = ""
    km: int | None = None
    customer_name: str = ""
    offered_slots: list[dict[str, str]] = field(default_factory=list)
    appointment_id: int | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


class DialogueManager:
    def __init__(self, db_path=None) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, CallSession] = {}
        self.db_path = db_path

    def start(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = CallSession(session_id=session_id)
            session.messages.append({"role": "agent", "content": GREETING})
            self._sessions[session_id] = session
            return self._payload(session, GREETING)

    def get(self, session_id: str) -> CallSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def handle(self, session_id: str, user_text: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = CallSession(session_id=session_id)
                self._sessions[session_id] = session
        text = (user_text or "").strip()
        if not text:
            return self._reply(session, "", ASK_REPEAT)
        session.messages.append({"role": "user", "content": text})
        if session.phase == PHASE_BOOKED:
            return self._reply(session, text, "نوبت شما ثبت شده است. برای نوبت تازه، تماس جدید بزنید.")
        if session.phase == PHASE_ASK_CAR:
            return self._on_car(session, text)
        if session.phase == PHASE_ASK_MODEL:
            return self._on_model(session, text)
        if session.phase == PHASE_ASK_KM:
            return self._on_km(session, text)
        if session.phase == PHASE_ASK_NAME:
            return self._on_name(session, text)
        if session.phase == PHASE_ASK_SLOT:
            return self._on_slot(session, text)
        return self._on_car(session, text)

    def _clean(self, phase: str, text: str) -> str:
        try:
            cleaned = extract_answer(phase, text)
            return cleaned or text
        except OllamaError:
            return text

    def _on_car(self, session: CallSession, text: str) -> dict[str, Any]:
        value = self._clean("car", text)
        if len(value) < 2:
            return self._reply(session, text, ASK_REPEAT)
        session.car_name = value
        session.phase = PHASE_ASK_MODEL
        return self._reply(session, text, ASK_MODEL)

    def _on_model(self, session: CallSession, text: str) -> dict[str, Any]:
        value = self._clean("model", text)
        if len(value) < 1:
            return self._reply(session, text, ASK_REPEAT)
        session.car_model = value
        session.phase = PHASE_ASK_KM
        return self._reply(session, text, ASK_KM)

    def _on_km(self, session: CallSession, text: str) -> dict[str, Any]:
        cleaned = self._clean("km", text)
        km = parse_km(cleaned) or parse_km(text)
        if km is None:
            return self._reply(session, text, "کارکرد را به کیلومتر بگویید. مثلاً ۸۰۰۰۰.")
        session.km = km
        session.phase = PHASE_ASK_NAME
        return self._reply(session, text, ASK_NAME)

    def _on_name(self, session: CallSession, text: str) -> dict[str, Any]:
        value = self._clean("name", text)
        if len(value) < 2:
            return self._reply(session, text, ASK_REPEAT)
        session.customer_name = value
        slots = booking.next_open_slots(limit=3, db_path=self.db_path)
        session.offered_slots = slots
        session.phase = PHASE_ASK_SLOT
        if not slots:
            return self._reply(session, text, "در روزهای کاری نوبت خالی پیدا نشد.")
        labels = "، ".join(item["label"] for item in slots)
        reply = (
            f"{session.customer_name} عزیز، نوبت‌های خالی دفتر از دوشنبه تا جمعه ساعت ۹ تا ۱۷ این‌هاست: "
            f"{labels}. اگر اولین وقت مناسب است بگویید بله."
        )
        return self._reply(session, text, reply)

    def _on_slot(self, session: CallSession, text: str) -> dict[str, Any]:
        lowered = text.replace("‌", "").replace(" ", "")
        if any(word in text for word in NO_WORDS) and not any(word in text for word in YES_WORDS):
            slots = booking.next_open_slots(limit=6, db_path=self.db_path)
            session.offered_slots = slots[3:] or slots
            if not session.offered_slots:
                return self._reply(session, text, "وقت خالی دیگری نیست.")
            labels = "، ".join(item["label"] for item in session.offered_slots[:3])
            return self._reply(session, text, f"وقت‌های بعدی: {labels}. اگر موافقید بگویید بله.")
        if any(word in text for word in YES_WORDS) or "بله" in lowered:
            if not session.offered_slots:
                return self._reply(session, text, "وقتی برای تأیید ندارم. تماس را از نو شروع کنید.")
            return self._book(session, session.offered_slots[0], text)
        cleaned = self._clean("slot", text)
        picked = None
        for item in session.offered_slots:
            if item["time"] in cleaned or item["time"] in text or item["date"] in text:
                picked = item
                break
            if item["label"] in text:
                picked = item
                break
        if picked is None and session.offered_slots:
            # fall back to first slot if the customer just confirmed vaguely
            if any(word in cleaned for word in YES_WORDS):
                picked = session.offered_slots[0]
        if picked is None:
            return self._reply(
                session,
                text,
                "کدام ساعت را می‌خواهید؟ بگویید بله تا اولین وقت ثبت شود.",
            )
        return self._book(session, picked, text)

    def _book(self, session: CallSession, slot: dict[str, str], text: str) -> dict[str, Any]:
        try:
            appt_id = booking.book_appointment(
                session.customer_name,
                session.car_name,
                session.car_model,
                session.km,
                slot["date"],
                slot["time"],
                db_path=self.db_path,
            )
        except ValueError as extra:
            return self._reply(session, text, str(extra))
        session.appointment_id = appt_id
        session.phase = PHASE_BOOKED
        reply = (
            f"نوبت ثبت شد. {session.customer_name}، {session.car_name} {session.car_model} "
            f"با کارکرد {session.km} کیلومتر، {slot['label']}."
        )
        return self._reply(session, text, reply)

    def _reply(self, session: CallSession, user_text: str, reply: str) -> dict[str, Any]:
        if reply:
            session.messages.append({"role": "agent", "content": reply})
        return self._payload(session, reply)

    def _payload(self, session: CallSession, reply: str) -> dict[str, Any]:
        return {
            "reply": reply,
            "phase": session.phase,
            "appointment_id": session.appointment_id,
            "offered_slots": session.offered_slots,
            "customer": {
                "name": session.customer_name,
                "car_name": session.car_name,
                "car_model": session.car_model,
                "km": session.km,
            },
            "messages": list(session.messages),
        }


def parse_km(text: str) -> int | None:
    if not text:
        return None
    normalized = text.translate(_DIGITS).replace(",", "").replace("٬", "").replace(" ", "")
    numbers = re.findall(r"\d+", normalized)
    if not numbers:
        return None
    value = int(numbers[0])
    if "هزار" in text or "هزار" in normalized:
        if value < 1000:
            value *= 1000
    return value if value >= 0 else None
