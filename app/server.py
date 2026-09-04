"""FastAPI server: Persian call simulator + Jalali calendar + Shenava ASR."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio import TARGET_RATE, concat, int16_bytes_to_float32
from .booking import (
    available_slots,
    book_appointment,
    init_db,
    is_office_open,
    list_appointments,
    month_calendar,
    slot_times,
)
from .dialogue import DialogueManager
from .discovery import ModelInfo, find_models_dir, find_shenava_ctc, scan_models
from .engines import Engine, TranscriptionError, load_engine
from .jalali import to_jalali
from datetime import date

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class StartBody(BaseModel):
    session_id: str = ""


class HangupBody(BaseModel):
    session_id: str = Field(..., min_length=1)


class TurnBody(BaseModel):
    session_id: str = Field(..., min_length=1)
    text: str = ""


class BookBody(BaseModel):
    customer_name: str = Field(..., min_length=1)
    car_name: str = Field(..., min_length=1)
    car_model: str = Field(..., min_length=1)
    km: int | None = None
    date: str
    time: str


class AppState:
    def __init__(self, models_dir: str | Path | None = None, db_path: Path | None = None) -> None:
        self.lock = threading.RLock()
        self.models_dir = find_models_dir(models_dir)
        self.models: list[ModelInfo] = []
        self.asr: ModelInfo | None = None
        self.engine: Engine | None = None
        self.loading = False
        self.status = "آماده"
        self.dialogue = DialogueManager(db_path=db_path)
        self.db_path = db_path
        init_db(db_path)
        self.refresh()

    def refresh(self) -> None:
        self.models_dir, self.models = scan_models(self.models_dir)
        self.asr = find_shenava_ctc(self.models)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            asr = self.asr
            today = date.today()
            jy, jm, _jd = to_jalali(today)
            return {
                "models_dir": str(self.models_dir),
                "asr": None
                if asr is None
                else {
                    "id": asr.id,
                    "name_fa": asr.name_fa,
                    "engine": asr.engine,
                    "note": asr.note,
                },
                "ready": self.engine is not None,
                "loading": self.loading,
                "status": self.status,
                "llm_model": "llama3.2:3b",
                "hours": "۰۹:۰۰ تا ۱۷:۰۰",
                "open_days": "دوشنبه تا جمعه",
                "today_jalali": {"year": jy, "month": jm},
            }

    def boot(self) -> dict[str, Any]:
        with self.lock:
            self.refresh()
            info = self.asr
            if info is None:
                self.status = "شنوا کوچیک CTC پیدا نشد؛ تماس متنی فعال است."
                return self.snapshot()
            if self.engine is not None:
                self.status = f"مدل آماده است: {info.name_fa}"
                return self.snapshot()
            self.loading = True
            self.status = f"در حال بارگذاری {info.name_fa}..."

        try:
            engine = load_engine(info)
        except TranscriptionError as extra:
            with self.lock:
                self.loading = False
                self.engine = None
                self.status = str(extra)
            return self.snapshot()
        except Exception as extra:
            with self.lock:
                self.loading = False
                self.engine = None
                self.status = f"بارگذاری مدل ناموفق بود: {extra}"
            return self.snapshot()

        with self.lock:
            self.engine = engine
            self.loading = False
            self.status = f"مدل آماده است: {info.name_fa}"
            return self.snapshot()

    def transcribe(self, audio) -> str:
        with self.lock:
            engine = self.engine
        if engine is None:
            raise HTTPException(status_code=400, detail="مدل شنوا برای تماس صوتی بارگذاری نشده است.")
        return engine.transcribe(audio, TARGET_RATE)


state = AppState()
app = FastAPI(title="رزرو نوبت نمایندگی خودرو", version="2.0.0")


def reset_state(models_dir: str | Path | None = None, db_path: Path | None = None) -> AppState:
    global state
    state = AppState(models_dir, db_path=db_path)
    return state


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    state.refresh()
    return state.snapshot()


@app.post("/api/boot")
def boot_asr() -> dict[str, Any]:
    return state.boot()


@app.post("/api/call/start")
def call_start(body: StartBody | None = None) -> dict[str, Any]:
    session_id = (body.session_id if body and body.session_id else None) or str(uuid4())
    payload = state.dialogue.start(session_id)
    payload["session_id"] = session_id
    return payload


@app.post("/api/call/turn")
def call_turn(body: TurnBody) -> dict[str, Any]:
    payload = state.dialogue.handle(body.session_id, body.text)
    payload["session_id"] = body.session_id
    return payload


@app.post("/api/call/hangup")
def call_hangup(body: HangupBody) -> dict[str, Any]:
    payload = state.dialogue.hangup(body.session_id) or {
        "reply": "",
        "phase": "ended",
        "live": False,
        "messages": [],
        "customer": {},
        "offered_slots": [],
        "appointment_id": None,
    }
    payload["session_id"] = body.session_id
    return payload


@app.get("/api/calendar")
def get_calendar(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    return month_calendar(year, month, db_path=state.db_path)


@app.get("/api/slots")
def get_slots(date: str) -> dict[str, Any]:
    from datetime import date as date_cls

    parsed = date_cls.fromisoformat(date)
    return {
        "date": date,
        "all": slot_times() if is_office_open(parsed) else [],
        "slots": available_slots(date, db_path=state.db_path),
        "open": is_office_open(parsed),
    }


@app.get("/api/appointments")
def get_appointments() -> list[dict[str, Any]]:
    return list_appointments(db_path=state.db_path)


@app.post("/api/book")
def post_book(body: BookBody) -> dict[str, Any]:
    try:
        appt_id = book_appointment(
            body.customer_name,
            body.car_name,
            body.car_model,
            body.km,
            body.date,
            body.time,
            db_path=state.db_path,
        )
    except ValueError as extra:
        raise HTTPException(status_code=409, detail=str(extra)) from extra
    return {"ok": True, "id": appt_id, "message": "نوبت در فهرست مشتریان ثبت شد."}


@app.websocket("/ws/stream")
async def stream_call(websocket: WebSocket) -> None:
    """Persistent duplex call: keep listening; each VAD endpoint is one short turn."""
    await websocket.accept()
    chunks: list = []
    session_id = ""
    engine: Engine | None = None
    with state.lock:
        engine = state.engine
        if engine is None:
            await websocket.send_json(
                {"type": "error", "message": "مدل شنوا برای تماس صوتی آماده نیست. متن را تایپ کنید."}
            )
            await websocket.close()
            return
        if engine.supports_stream:
            engine.start_stream()

    async def commit_utterance() -> None:
        nonlocal chunks
        full = concat(chunks)
        chunks = []
        if engine is not None and engine.supports_stream:
            try:
                engine.end_stream()
                engine.start_stream()
            except Exception:
                pass
        if full.size < TARGET_RATE * 0.18:
            await websocket.send_json({"type": "ignore"})
            return
        try:
            text_out = await asyncio.to_thread(state.transcribe, full)
        except Exception as extra:
            await websocket.send_json({"type": "error", "message": str(extra)})
            return
        text_out = (text_out or "").strip()
        if not text_out or not session_id:
            await websocket.send_json({"type": "ignore", "text": text_out})
            return
        turn = await asyncio.to_thread(state.dialogue.handle, session_id, text_out)
        await websocket.send_json({"type": "assistant", "text": text_out, "turn": turn})

    try:
        await websocket.send_json({"type": "status", "message": "گوش می‌دهم..."})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            text = message.get("text")
            if text:
                raw = text.strip()
                payload: dict[str, Any] = {}
                if raw.startswith("{"):
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except json.JSONDecodeError:
                        payload = {}
                session_id = str(payload.get("session_id") or session_id)
                kind = str(payload.get("type") or raw.lower())
                if kind in {"hangup", "stop", "end"}:
                    break
                if kind == "endpoint":
                    await commit_utterance()
                continue
            if not data:
                continue
            audio = int16_bytes_to_float32(data)
            if audio.size == 0:
                continue
            chunks.append(audio)
            if engine.supports_stream:
                partial = engine.feed(audio, TARGET_RATE)
                if partial:
                    await websocket.send_json({"type": "partial", "text": partial})
    except WebSocketDisconnect:
        pass
    finally:
        if engine is not None and engine.supports_stream:
            try:
                engine.end_stream()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
