"""FastAPI server for Persian dictation model comparison."""

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
from .discovery import ModelInfo, find_models_dir, scan_models
from .engines import Engine, TranscriptionError, load_engine

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class SelectBody(BaseModel):
    model_id: str = Field(..., min_length=1)


class AppState:
    def __init__(self, models_dir: str | Path | None = None) -> None:
        self.lock = threading.RLock()
        self.models_dir = find_models_dir(models_dir)
        self.models: list[ModelInfo] = []
        self.active_id: str | None = None
        self.engine: Engine | None = None
        self.loading = False
        self.status = "آماده"
        self.last_audio: np.ndarray | None = None
        self.results: dict[str, dict[str, Any]] = {}
        self.refresh()

    def refresh(self) -> None:
        self.models_dir, self.models = scan_models(self.models_dir)

    def model_map(self) -> dict[str, ModelInfo]:
        return {item.id: item for item in self.models}

    def public_models(self) -> list[dict[str, Any]]:
        payload = []
        for item in self.models:
            payload.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "name_fa": item.name_fa,
                    "engine": item.engine,
                    "usable": item.usable,
                    "note": item.note,
                    "active": item.id == self.active_id,
                    "last_text": (self.results.get(item.id) or {}).get("text", ""),
                    "last_ms": (self.results.get(item.id) or {}).get("ms"),
                }
            )
        return payload

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "models_dir": str(self.models_dir),
                "models": self.public_models(),
                "active_id": self.active_id,
                "loading": self.loading,
                "status": self.status,
                "has_last_audio": self.last_audio is not None and self.last_audio.size > 0,
            }

    def select(self, model_id: str) -> dict[str, Any]:
        with self.lock:
            info = self.model_map().get(model_id)
            if info is None:
                raise HTTPException(status_code=404, detail="مدل پیدا نشد.")
            if not info.usable:
                raise HTTPException(status_code=400, detail=info.note)
            if self.active_id == model_id and self.engine is not None:
                self.status = f"مدل فعال: {info.name_fa}"
                return self.snapshot()
            self.loading = True
            self.status = f"در حال بارگذاری {info.name_fa}..."
            previous = self.engine
            self.engine = None

        if previous is not None:
            try:
                previous.close()
            except Exception:
                pass

        try:
            engine = load_engine(info)
        except TranscriptionError as exc:
            with self.lock:
                self.loading = False
                self.active_id = None
                self.status = str(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            message = f"بارگذاری مدل ناموفق بود: {exc}"
            with self.lock:
                self.loading = False
                self.active_id = None
                self.status = message
            raise HTTPException(status_code=500, detail=message) from exc

        with self.lock:
            self.engine = engine
            self.active_id = model_id
            self.loading = False
            self.status = f"مدل آماده است: {info.name_fa}"
            return self.snapshot()

    def remember_audio(self, audio: np.ndarray) -> None:
        with self.lock:
            self.last_audio = np.asarray(audio, dtype=np.float32).copy()

    def transcribe_current(self, audio: np.ndarray | None = None) -> dict[str, Any]:
        with self.lock:
            engine = self.engine
            active_id = self.active_id
            info = self.model_map().get(active_id) if active_id else None
            if audio is None:
                audio = self.last_audio
            if engine is None or info is None:
                raise HTTPException(status_code=400, detail="ابتدا یک مدل را با دکمه رادیویی انتخاب کنید.")
            if audio is None or audio.size == 0:
                raise HTTPException(status_code=400, detail="صوتی برای رونویسی وجود ندارد.")
            self.status = f"در حال رونویسی با {info.name_fa}..."

        started = time.perf_counter()
        try:
            text = engine.transcribe(audio, TARGET_RATE)
        except Exception as exc:
            with self.lock:
                self.status = f"خطا در رونویسی: {exc}"
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        with self.lock:
            self.results[active_id] = {
                "text": text,
                "ms": elapsed_ms,
                "model": info.name_fa,
            }
            self.status = "رونویسی تمام شد."
            return {
                "model_id": active_id,
                "model": info.name_fa,
                "text": text,
                "ms": elapsed_ms,
                "state": self.snapshot(),
            }


state = AppState()
app = FastAPI(title="تایپ گفتاری فارسی", version="1.0.0")


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


@app.post("/api/refresh")
def refresh_models() -> dict[str, Any]:
    state.refresh()
    return state.snapshot()


@app.post("/api/select")
def select_model(body: SelectBody) -> dict[str, Any]:
    return state.select(body.model_id)


@app.post("/api/transcribe")
async def transcribe_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="فایل خالی است.")
    try:
        audio = load_audio_file(data, file.filename or "audio.wav")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state.remember_audio(audio)
    return state.transcribe_current(audio)


@app.post("/api/transcribe-last")
def transcribe_last() -> dict[str, Any]:
    return state.transcribe_current()


@app.websocket("/ws/stream")
async def stream_transcription(websocket: WebSocket) -> None:
    await websocket.accept()
    chunks: list[np.ndarray] = []
    engine: Engine | None = None
    with state.lock:
        engine = state.engine
        if engine is None:
            await websocket.send_json({"type": "error", "message": "ابتدا یک مدل را انتخاب کنید."})
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
        final_text = ""
        if engine is not None:
            try:
                if engine.supports_stream:
                    streamed = engine.end_stream()
                    final_text = streamed
                if full.size:
                    result = state.transcribe_current(full)
                    final_text = result["text"]
                    await websocket.send_json(
                        {
                            "type": "final",
                            "text": final_text,
                            "ms": result["ms"],
                            "model_id": result["model_id"],
                            "model": result["model"],
                            "state": result["state"],
                        }
                    )
                else:
                    await websocket.send_json({"type": "final", "text": final_text, "ms": 0})
            except HTTPException as exc:
                try:
                    await websocket.send_json({"type": "error", "message": exc.detail})
                except Exception:
                    pass
            except Exception as exc:
                try:
                    await websocket.send_json({"type": "error", "message": str(exc)})
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
