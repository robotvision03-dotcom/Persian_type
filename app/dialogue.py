"""Call-simulator dialogue for car-dealership appointment booking.

Short ask–answer turns: one missing slot per question, but a customer
utterance may over-answer (fill several slots). The next prompt is always
the first unfilled slot, so “peugeot 206” skips the model question.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from . import booking
from .cars import brand_models
from .nlu import (
    NO_WORDS,
    PHASE_ASK_CAR,
    PHASE_ASK_KM,
    PHASE_ASK_MODEL,
    PHASE_ASK_NAME,
    PHASE_ASK_SLOT,
    PHASE_BOOKED,
    YES_WORDS,
    next_missing_phase,
    parse_km,
    parse_slots,
)

GREETING = "سلام وقت بخیر. لطفا اسم خودروی خود را بگویید."
ASK_CAR = GREETING
ASK_MODEL = "کدام مدل را برای خرید می‌خواهید؟"
ASK_KM = "خودرو صفر است یا کارکرد دارد؟ اگر کارکرد دارد کیلومتر را بگویید."
ASK_NAME = "نام و نام خانوادگی چیست؟"
ASK_REPEAT = "متوجه نشدم. لطفا نام خودرو را از خودروهای موجود بگویید."

PROMPTS = {
    PHASE_ASK_CAR: ASK_CAR,
    PHASE_ASK_MODEL: ASK_MODEL,
    PHASE_ASK_KM: ASK_KM,
    PHASE_ASK_NAME: ASK_NAME,
}


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
    live: bool = False


class DialogueManager:
    def __init__(self, db_path=None) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, CallSession] = {}
        self.db_path = db_path

    def start(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = CallSession(session_id=session_id, live=True)
            session.offered_slots = booking.next_open_slots(limit=12, db_path=self.db_path)
            session.messages.append({"role": "agent", "content": GREETING})
            self._sessions[session_id] = session
            return self._payload(session, GREETING)

    def hangup(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            session.live = False
            return self._payload(session, "")

    def get(self, session_id: str) -> CallSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def handle(self, session_id: str, user_text: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = CallSession(session_id=session_id, live=True)
                self._sessions[session_id] = session
        text = (user_text or "").strip()
        if not text:
            return self._reply(session, "", ASK_REPEAT)
        session.messages.append({"role": "user", "content": text})
        if session.phase == PHASE_BOOKED:
            return self._reply(session, text, "نوبت شما ثبت شده است. برای نوبت تازه، تماس جدید بزنید.")
        if session.phase == PHASE_ASK_SLOT:
            return self._on_slot(session, text)

        slots = parse_slots(text, session.phase, prefer_brand=session.car_name)
        if session.phase == PHASE_ASK_CAR and slots.get("candidates") and not slots.get("car_name"):
            names = " یا ".join(slots["candidates"])
            return self._reply(session, text, f"کدام خودرو را می‌گویید؟ {names}.")
        self._fill_slots(session, slots, text)
        return self._prompt_next(session, text)

    def _fill_slots(self, session: CallSession, slots: dict[str, Any], text: str) -> None:
        if slots.get("car_name"):
            session.car_name = str(slots["car_name"]).strip()
        if session.car_name and not session.car_model and not brand_models(session.car_name):
            session.car_model = "استاندارد"

        if slots.get("car_model"):
            session.car_model = str(slots["car_model"]).strip()
        elif session.phase == PHASE_ASK_MODEL and not session.car_model:
            value = text.strip()
            if len(value) >= 1:
                session.car_model = value

        if slots.get("km") is not None:
            session.km = int(slots["km"])
        elif session.phase == PHASE_ASK_KM and session.km is None:
            km = parse_km(text)
            if km is not None:
                session.km = km

        if slots.get("customer_name"):
            session.customer_name = str(slots["customer_name"]).strip()
        elif session.phase == PHASE_ASK_NAME and not session.customer_name:
            value = text.strip()
            if len(value) >= 2:
                session.customer_name = value

    def _prompt_next(self, session: CallSession, text: str) -> dict[str, Any]:
        nxt = next_missing_phase(
            session.car_name, session.car_model, session.km, session.customer_name
        )
        if nxt == session.phase:
            if session.phase == PHASE_ASK_KM:
                return self._reply(session, text, "کارکرد را به کیلومتر بگویید. مثلاً ۸۰۰۰۰.")
            return self._reply(session, text, ASK_REPEAT)

        session.phase = nxt
        if nxt == PHASE_ASK_SLOT:
            return self._offer_slots(session, text)
        if nxt == PHASE_ASK_MODEL:
            models = brand_models(session.car_name)
            if models:
                listed = "، ".join(models[:6])
                return self._reply(
                    session,
                    text,
                    f"{session.car_name} ثبت شد. کدام مدل را برای خرید می‌خواهید؟ مثلاً {listed}.",
                )
        return self._reply(session, text, PROMPTS[nxt])

    def _offer_slots(self, session: CallSession, text: str) -> dict[str, Any]:
        slots = booking.next_open_slots(limit=3, db_path=self.db_path)
        session.offered_slots = slots
        session.phase = PHASE_ASK_SLOT
        if not slots:
            return self._reply(session, text, "در روزهای کاری نوبت خالی پیدا نشد.")
        labels = "، ".join(item["label"] for item in slots)
        reply = (
            f"{session.customer_name} عزیز، برای بازدید و خرید {session.car_name} {session.car_model} "
            f"وقت‌های خالی شنبه تا پنجشنبه ساعت ۹ تا ۱۷ این‌هاست: {labels}. "
            "اگر اولین وقت مناسب است بگویید بله."
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
        picked = None
        for item in session.offered_slots:
            if item["time"] in text or item["date"] in text or item["label"] in text:
                picked = item
                break
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
        session.live = False
        km_label = "صفر" if session.km == 0 else f"{session.km} کیلومتر"
        reply = (
            f"نوبت بازدید و خرید ثبت شد. {session.customer_name}، {session.car_name} {session.car_model} "
            f"({km_label})، {slot['label']}."
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
            "live": session.live,
            "hours": booking.hours_panel(db_path=self.db_path),
        }
