"""Audio helpers for 16 kHz mono float32 PCM."""

from __future__ import annotations

import io
from typing import Iterable

import numpy as np

TARGET_RATE = 16000


def to_mono(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1:
        return samples.astype(np.float32, copy=False)
    return samples.mean(axis=1).astype(np.float32)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int = TARGET_RATE) -> np.ndarray:
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    duration = samples.size / float(source_rate)
    target_count = max(1, int(round(duration * target_rate)))
    old_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    new_x = np.linspace(0.0, 1.0, num=target_count, endpoint=False)
    return np.interp(new_x, old_x, samples.astype(np.float64)).astype(np.float32)


def int16_bytes_to_float32(data: bytes) -> np.ndarray:
    if not data:
        return np.zeros(0, dtype=np.float32)
    pcm = np.frombuffer(data, dtype=np.int16)
    return (pcm.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


def float32_to_int16_bytes(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples.astype(np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def normalize_audio(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    mono = to_mono(np.asarray(samples))
    if mono.dtype == np.int16:
        mono = mono.astype(np.float32) / 32768.0
    elif np.issubdtype(mono.dtype, np.integer):
        info = np.iinfo(mono.dtype)
        scale = float(max(abs(info.min), info.max)) or 1.0
        mono = mono.astype(np.float32) / scale
    else:
        mono = mono.astype(np.float32)
    audio = resample_linear(mono, sample_rate, TARGET_RATE)
    return np.clip(audio, -1.0, 1.0)


def concat(chunks: Iterable[np.ndarray]) -> np.ndarray:
    parts = [np.asarray(chunk, dtype=np.float32) for chunk in chunks if np.asarray(chunk).size]
    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts)


def wav_bytes_from_float32(samples: np.ndarray, sample_rate: int = TARGET_RATE) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, samples.astype(np.float32), sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def load_audio_file(data: bytes, filename: str = "audio.wav") -> np.ndarray:
    import soundfile as sf

    buffer = io.BytesIO(data)
    try:
        samples, rate = sf.read(buffer, dtype="float32", always_2d=False)
        return normalize_audio(samples, rate)
    except Exception:
        # soundfile cannot decode some browser webm/ogg blobs; try wav header only
        buffer.seek(0)
        raise RuntimeError(f"نمی‌توان فایل صوتی را خواند ({filename}). WAV یا FLAC بفرستید.") from None
