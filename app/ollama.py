"""Ollama helpers for comparing local LLM speed and Persian accuracy."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODELS = ("qwen2.5:14b", "llama3.2:3b")


class OllamaError(RuntimeError):
    pass


def ollama_host() -> str:
    return (os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")


def configured_models() -> list[str]:
    raw = os.environ.get("OLLAMA_MODELS")
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return list(DEFAULT_MODELS)


def persian_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha() or ("\u0600" <= char <= "\u06FF")]
    if not letters:
        return 0.0
    persian = sum(1 for char in letters if "\u0600" <= char <= "\u06FF")
    return round(persian / len(letters), 3)


def build_eval_prompt(transcript: str) -> str:
    return (
        "تو یک ویرایشگر دقیق زبان فارسی هستی.\n"
        "متن زیر خروجی تشخیص گفتار فارسی است.\n"
        "۱) غلط‌های املایی و واژه‌های اشتباه را اصلاح کن.\n"
        "۲) اگر متن سؤال است، به فارسی جواب بده.\n"
        "فقط نتیجه نهایی را بنویس؛ توضیح اضافه نده.\n\n"
        f"متن:\n{transcript.strip()}\n"
    )


def _request_json(url: str, payload: dict[str, Any] | None = None, timeout: int = 180) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as extra:
        raise OllamaError("Ollama در دسترس نیست. در ترمینال بزنید: ollama serve") from extra
    if not body:
        return {}
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise OllamaError("پاسخ Ollama نامعتبر بود.")
    return parsed


def list_ollama_models(host: str | None = None) -> list[str]:
    payload = _request_json(f"{host or ollama_host()}/api/tags", timeout=10)
    names = []
    for item in payload.get("models") or []:
        name = item.get("name")
        if name:
            names.append(str(name))
    return names


def generate(model: str, prompt: str, host: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    payload = _request_json(
        f"{host or ollama_host()}/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        },
        timeout=300,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    text = str(payload.get("response") or "").strip()
    eval_count = payload.get("eval_count")
    eval_duration = payload.get("eval_duration")
    tokens_per_sec = None
    if isinstance(eval_count, (int, float)) and isinstance(eval_duration, (int, float)) and eval_duration > 0:
        tokens_per_sec = round(eval_count / (eval_duration / 1_000_000_000), 2)
    return {
        "model": model,
        "text": text,
        "ms": elapsed_ms,
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec,
        "persian_ratio": persian_ratio(text),
    }


def resolve_test_models(available: list[str] | None = None) -> list[str]:
    wanted = configured_models()
    if available is None:
        return wanted
    resolved = []
    for name in wanted:
        if name in available or any(item.startswith(f"{name}") for item in available):
            resolved.append(name)
            continue
        short = name.split(":")[0]
        match = next((item for item in available if item.split(":")[0] == short), None)
        if match:
            resolved.append(match)
    return resolved


def test_models(transcript: str, models: list[str] | None = None, host: str | None = None) -> dict[str, Any]:
    text = (transcript or "").strip()
    if not text:
        raise OllamaError("متنی برای آزمایش LLM وجود ندارد.")
    available = list_ollama_models(host)
    selected = models if models is not None else resolve_test_models(available)
    if not selected:
        raise OllamaError(
            "مدل‌های qwen2.5:14b و llama3.2:3b در Ollama پیدا نشدند. "
            "با ollama list بررسی کنید."
        )
    prompt = build_eval_prompt(text)
    results = []
    for model in selected:
        try:
            results.append(generate(model, prompt, host=host))
        except OllamaError as extra:
            results.append(
                {
                    "model": model,
                    "text": str(extra),
                    "ms": 0,
                    "eval_count": None,
                    "tokens_per_sec": None,
                    "persian_ratio": 0.0,
                    "error": True,
                }
            )
    successful = [item for item in results if not item.get("error")]
    fastest = min(successful, key=lambda item: item["ms"])["model"] if successful else None
    most_persian = (
        max(successful, key=lambda item: item["persian_ratio"])["model"] if successful else None
    )
    return {
        "prompt": prompt,
        "results": results,
        "fastest": fastest,
        "most_persian": most_persian,
        "available": available,
    }
