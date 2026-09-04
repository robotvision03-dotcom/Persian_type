"""FastAPI server for Shenava CTC dictation and Ollama LLM tests."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audio import TARGET_RATE, concat, int16_bytes_to_float32, load_audio_file
from .discovery import ModelInfo, find_models_dir, find_shenava_ctc, scan_models
from .engines import Engine, TranscriptionError, load_engine
from .ollama import OllamaError, configured_models, test_models

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class LlmTestBody(BaseModel):
    text: str = Field(..., min_length=1)


class AppState:
    def __init__(self, models_dir: str | Path | None = None) -> None:
        self.lock = threading.RLock()
        self.models_dir = find_models_dir(models_dir)
        self.models: list[ModelInfo] = []
        self.asr: ModelInfo | None = None
        self.engine: Engine | None = None
        self.loading = False
        self.status = "آماده"
        self.last_audio: np.ndarray | None = None
        self.last_transcript = ""
        self.last_asr_ms: int | None = None
        self.llm_results: dict[str, Any] | None = None
        self.refresh()

    def refresh(self) -> None:
        self.models_dir, self.models = scan_models(self.models_dir)
        self.asr = find_shenava_ctc(self.models)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            asr = self.asr
            return {
                "models_dir": str(self.models_dir),
                "asr": None
                if asr is None
                else {
                    "id": asr.id,
                    "name": asr.name,
                    "name_fa": asr.name_fa,
                    "engine": asr.engine,
                    "note": asr.note,
                },
                "ready": self.engine is not None,
                "loading": self.loading,
                "status": self.status,
                "has_last_audio": self.last_audio is not None and self.last_audio.size > 0,
                "last_transcript": self.last_transcript,
                "last_asr_ms": self.last_asr_ms,
                "llm": self.llm_results,
                "ollama_models": configured_models(),
            }

    def boot(self) -> dict[str, Any]:
        with self.lock:
            self.refresh()
            info = self.asr
            if info is None:
                self.status = "پوشه shenava-koochik-ctc پیدا نشد."
                raise HTTPException(
                    status_code=404,
                    detail="مدل شنوا کوچیک CTC پیدا نشد. پوشه shenava-koochik-ctc را در models بگذارید.",
                )
            if self.engine is not None:
                self.status = f"مدل آماده است: {info.name_fa}"
                return self.snapshot()
            self.loading = True
            self.status = f"در حال بارگذاری {info.name_fa}..."
            previous = self.engine

        if previous is not None:
            try:
                previous.close()
            except Exception:
                pass

        try:
            engine = load_engine(info)
        except TranscriptionError as extra:
            with self.lock:
                self.loading = False
                self.engine = None
                self.status = str(extra)
            raise HTTPException(status_code=500, detail=str(extra)) from extra
        except Exception as extra:
            message = f"بارگذاری مدل ناموفق بود: {extra}"
            with self.lock:
                self.loading = False
                self.engine = None
                self.status = message
            raise HTTPException(status_code=500, detail=message) from extra

        with self.lock:
            self.engine = engine
            self.loading = False
            self.status = f"مدل آماده است: {info.name_fa}"
            return self.snapshot()

    def remember_audio(self, audio: np.ndarray) -> None:
        with self.lock:
            self.last_audio = np.asarray(audio, dtype=np.float32).copy()

    def transcribe_current(self, audio: np.ndarray | None = None) -> dict[str, Any]:
        with self.lock:
            engine = self.engine
            info = self.asr
            if audio is None:
                audio = self.last_audio
            if engine is None or info is None:
                raise HTTPException(status_code=400, detail="مدل شنوا کوچیک CTC هنوز بارگذاری نشده است.")
            if audio is None or audio.size == 0:
                raise HTTPException(status_code=400, detail="صوتی برای رونویسی وجود ندارد.")
            self.status = f"در حال رونویسی با {info.name_fa}..."

        started = time.perf_counter()
        try:
            text = engine.transcribe(audio, TARGET_RATE)
        except Exception as extra:
            with self.lock:
                self.status = f"خطا در رونویسی: {extra}"
            raise HTTPException(status_code=500, detail=str(extra)) from extra
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        with self.lock:
            self.last_transcript = text
            self.last_asr_ms = elapsed_ms
            self.status = "رونویسی تمام شد."
            return {
                "model_id": info.id,
                "model": info.name_fa,
                "text": text,
                "ms": elapsed_ms,
                "state": self.snapshot(),
            }

    def run_llm_test(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="متنی برای آزمایش LLM وجود ندارد.")
        with self.lock:
            self.status = "در حال آزمایش مدل‌های Ollama..."
            self.last_transcript = cleaned
        try:
            payload = test_models(cleaned)
        except OllamaError as extra:
            with self.lock:
                self.status = str(extra)
            raise HTTPException(status_code=503, detail=str(extra)) from extra
        with self.lock:
            self.llm_results = payload
            self.status = "آزمایش LLM تمام شد."
            return {"llm": payload, "state": self.snapshot()}


state = AppState()
app = FastAPI(title="تایپ گفتاری فارسی", version="1.1.0")


def reset_state(models_dir: str | Path | None = None) -> AppState:
    global state
    state = AppState(models_dir)
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


@app.post("/api/transcribe")
async def transcribe_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="فایل خالی است.")
    try:
        audio = load_audio_file(data, file.filename or "audio.wav")
    except RuntimeError as extra:
        raise HTTPException(status_code=400, detail=str(extra)) from extra
    state.remember_audio(audio)
    return state.transcribe_current(audio)


@app.post("/api/transcribe-last")
def transcribe_last() -> dict[str, Any]:
    return state.transcribe_current()


@app.post("/api/llm-test")
def llm_test(body: LlmTestBody) -> dict[str, Any]:
    return state.run_llm_test(body.text)


@app.websocket("/ws/stream")
async def stream_transcription(websocket: WebSocket) -> None:
    await websocket.accept()
    chunks: list[np.ndarray] = []
    engine: Engine | None = None
    with state.lock:
        engine = state.engine
        if engine is None:
            await websocket.send_json({"type": "error", "message": "مدل شنوا هنوز بارگذاری نشده است."})
            await websocket.close()
            return
        engine.start_stream()
        state.status = "در حال گوش دادن..."

    try:
        await websocket.send_json({"type": "status", "message": "گوش می‌دهم..."})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            text = message.get("text")
            if text:
                payload = text.strip().lower()
                if payload in {"stop", "end"}:
                    break
                continue
            if not data:
                continue
            audio = int16_bytes_to_float32(data)
            if audio.size == 0:
                continue
            chunks.append(audio)
            if engine.supports_stream:
                partial = engine.feed(audio, TARGET_RATE)
                await websocket.send_json({"type": "partial", "text": partial})
    except WebSocketDisconnect:
        pass
    finally:
        full = concat(chunks)
        if full.size:
            state.remember_audio(full)
        if engine is not None:
            try:
                if engine.supports_stream:
                    engine.end_stream()
                if full.size:
                    result = state.transcribe_current(full)
                    await websocket.send_json(
                        {
                            "type": "final",
                            "text": result["text"],
                            "ms": result["ms"],
                            "model_id": result["model_id"],
                            "model": result["model"],
                            "state": result["state"],
                        }
                    )
                else:
                    await websocket.send_json({"type": "final", "text": "", "ms": 0})
            except HTTPException as extra:
                try:
                    await websocket.send_json({"type": "error", "message": extra.detail})
                except Exception:
                    pass
            except Exception as extra:
                try:
                    await websocket.send_json({"type": "error", "message": str(extra)})
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
