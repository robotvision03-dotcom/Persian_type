"""Discover local Persian speech models."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

EngineKind = Literal[
    "vosk",
    "whisper_ct2",
    "sherpa_ctc",
    "sherpa_rnnt",
    "nemo",
    "piper_tts",
    "unknown",
]


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    name_fa: str
    path: str
    engine: EngineKind
    usable: bool
    note: str = ""
    files: dict[str, str] = field(default_factory=dict)


DISPLAY_NAMES = {
    "piper-voice-fa": ("Piper Voice FA", "پیپر — تبدیل متن به گفتار"),
    "shenava-koochik-ctc": ("Shenava Koochik CTC", "شنوا کوچیک CTC"),
    "shenava-koochik-v1.5": ("Shenava Koochik v1.5", "شنوا کوچیک نسخه ۱٫۵"),
    "vosk-model-fa": ("Vosk Persian", "وسک فارسی"),
    "whisper-persian-v4-ct2": ("Whisper Persian v4", "ویسپر فارسی نسخه ۴"),
}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_config_models_dir() -> Path | None:
    config_path = project_root() / "config.json"
    if not config_path.is_file():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    raw = data.get("models_dir")
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    return path if path.is_dir() else None


def _looks_like_models_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    subdirs = [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    return bool(subdirs)


def find_models_dir(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_dir():
            return path
        raise FileNotFoundError(f"Models directory not found: {path}")

    env = os.environ.get("MODELS_DIR") or os.environ.get("PERSIAN_TYPE_MODELS")
    if env:
        path = Path(env).expanduser().resolve()
        if path.is_dir():
            return path

    configured = _read_config_models_dir()
    if configured:
        return configured.resolve()

    candidates = [
        project_root() / "models",
        project_root().parent / "models",
        Path.cwd() / "models",
        Path.cwd().parent / "models",
    ]
    for candidate in candidates:
        if _looks_like_models_root(candidate):
            return candidate.resolve()

    fallback = (project_root() / "models").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _unwrap_single_nested(path: Path) -> Path:
    """If an unzip created an extra wrapper folder, step into it."""
    current = path
    for _ in range(3):
        if _has_model_markers(current):
            return current
        children = [item for item in current.iterdir() if item.is_dir() and not item.name.startswith(".")]
        files = [item for item in current.iterdir() if item.is_file() and not item.name.startswith(".")]
        if len(children) == 1 and not _has_model_markers(current) and not _meaningful_files(files):
            current = children[0]
            continue
        break
    return current


def _meaningful_files(files: list[Path]) -> bool:
    ignored = {".gitkeep", "readme.md", "license", "license.txt"}
    return any(item.name.lower() not in ignored for item in files)


def _has_model_markers(path: Path) -> bool:
    names = {item.name.lower() for item in path.iterdir()}
    if (path / "am" / "final.mdl").exists() or (path / "conf" / "model.conf").exists():
        return True
    if (path / "model.bin").exists() and (path / "config.json").exists():
        return True
    if "tokens.txt" in names and any(name.endswith(".onnx") for name in names):
        return True
    if {"encoder.onnx", "decoder.onnx", "joiner.onnx"} & names:
        return True
    if any(item.suffix.lower() == ".nemo" for item in path.iterdir() if item.is_file()):
        return True
    if any(item.name.endswith(".onnx.json") for item in path.iterdir()):
        return True
    return False


def _first_existing(path: Path, names: list[str]) -> Path | None:
    for name in names:
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def detect_engine(path: Path) -> tuple[EngineKind, dict[str, str], str]:
    path = _unwrap_single_nested(path)
    names = {item.name.lower() for item in path.iterdir()}

    piper_json = list(path.glob("*.onnx.json"))
    if piper_json or (path / "espeak-ng-data").exists() or "piper" in path.name.lower():
        onnx = next(iter(path.glob("*.onnx")), None)
        files = {}
        if onnx:
            files["onnx"] = str(onnx)
        if piper_json:
            files["config"] = str(piper_json[0])
        return "piper_tts", files, "این مدل تبدیل متن به گفتار است و برای تایپ گفتاری استفاده نمی‌شود."

    if (path / "am" / "final.mdl").exists() or (path / "conf" / "model.conf").exists():
        return "vosk", {"model_dir": str(path)}, "تشخیص زنده با Vosk"

    if (path / "model.bin").exists() and (path / "config.json").exists():
        return "whisper_ct2", {"model_dir": str(path)}, "Faster-Whisper / CTranslate2"

    encoder = _first_existing(path, ["encoder.onnx", "encoder.int8.onnx"])
    decoder = _first_existing(path, ["decoder.onnx", "decoder.int8.onnx"])
    joiner = _first_existing(path, ["joiner.onnx", "joiner.int8.onnx"])
    tokens = _first_existing(path, ["tokens.txt"])
    if encoder and decoder and joiner and tokens:
        return (
            "sherpa_rnnt",
            {
                "encoder": str(encoder),
                "decoder": str(decoder),
                "joiner": str(joiner),
                "tokens": str(tokens),
                "model_dir": str(path),
            },
            "شنوا / sherpa-onnx ترنسدیوسر",
        )

    ctc_model = _first_existing(path, ["model.onnx", "model.int8.onnx", "model.fp16.onnx"])
    if tokens is None:
        tokens = _first_existing(path, ["tokens.txt"])
    if ctc_model is None:
        onnx_files = [
            item
            for item in path.glob("*.onnx")
            if item.name.lower() not in {"encoder.onnx", "decoder.onnx", "joiner.onnx"}
            and not item.name.lower().endswith(".onnx.json")
        ]
        if onnx_files:
            ctc_model = onnx_files[0]
    if ctc_model and tokens:
        return (
            "sherpa_ctc",
            {"model": str(ctc_model), "tokens": str(tokens), "model_dir": str(path)},
            "شنوا / sherpa-onnx CTC",
        )

    nemo_files = sorted(path.glob("*.nemo"))
    if nemo_files:
        preferred = next(
            (item for item in nemo_files if "warmup" not in item.name.lower()),
            nemo_files[0],
        )
        return "nemo", {"nemo": str(preferred), "model_dir": str(path)}, "NVIDIA NeMo (.nemo)"

    unused = ", ".join(sorted(names)[:8])
    return "unknown", {"model_dir": str(path)}, f"قالب مدل شناسایی نشد: {unused}"


def _display_names(folder: str) -> tuple[str, str]:
    if folder in DISPLAY_NAMES:
        return DISPLAY_NAMES[folder]
    pretty = folder.replace("-", " ").replace("_", " ")
    return pretty, pretty


def scan_models(models_dir: str | Path | None = None) -> tuple[Path, list[ModelInfo]]:
    root = find_models_dir(models_dir)
    found: list[ModelInfo] = []
    if not root.is_dir():
        return root, found

    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        engine, files, note = detect_engine(child)
        name_en, name_fa = _display_names(child.name)
        usable = engine not in {"piper_tts", "unknown"}
        found.append(
            ModelInfo(
                id=child.name,
                name=name_en,
                name_fa=name_fa,
                path=str(child.resolve()),
                engine=engine,
                usable=usable,
                note=note,
                files=files,
            )
        )
    return root, found
