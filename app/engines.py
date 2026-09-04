"""Lazy-loaded local ASR engines."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .audio import TARGET_RATE, float32_to_int16_bytes, normalize_audio
from .discovery import ModelInfo


class TranscriptionError(RuntimeError):
    pass


class Engine(ABC):
    supports_stream: bool = False

    def __init__(self, info: ModelInfo) -> None:
        self.info = info

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        raise NotImplementedError

    def start_stream(self) -> None:
        return None

    def feed(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        return ""

    def end_stream(self) -> str:
        return ""

    def close(self) -> None:
        return None


def _maybe_itn(model_dir: str | None, text: str) -> str:
    if not model_dir or not text:
        return text
    itn_path = Path(model_dir) / "persian_itn.py"
    if not itn_path.is_file():
        return text
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("persian_itn_local", itn_path)
        if spec is None or spec.loader is None:
            return text
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "itn"):
            return str(module.itn(text))
    except Exception:
        return text
    return text


def _cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


PERSIAN_WHISPER_PROMPT = "گفتگو به زبان فارسی. سلام، خوبی، ممنون، بله، نه."


def persian_whisper_options() -> dict:
    """Decode settings that keep Whisper on Persian and avoid a slow beam search."""
    return {
        "language": "fa",
        "task": "transcribe",
        "beam_size": 1,
        "best_of": 1,
        "patience": 1.0,
        "temperature": 0.0,
        "vad_filter": False,
        "without_timestamps": True,
        "word_timestamps": False,
        "condition_on_previous_text": False,
        "initial_prompt": PERSIAN_WHISPER_PROMPT,
        "multilingual": False,
        "suppress_blank": True,
    }


def mostly_latin_script(text: str) -> bool:
    """True when the transcript looks like English/Latin instead of Persian."""
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 4:
        return False
    latin = sum(1 for char in letters if ("A" <= char <= "Z") or ("a" <= char <= "z"))
    return (latin / len(letters)) >= 0.55


class VoskEngine(Engine):
    supports_stream = True

    def __init__(self, info: ModelInfo) -> None:
        super().__init__(info)
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as extra:
            raise TranscriptionError("بسته vosk نصب نیست. pip install vosk") from extra

        SetLogLevel(-1)
        model_dir = info.files.get("model_dir") or info.path
        self._model = Model(model_dir)
        self._recognizer = KaldiRecognizer(self._model, TARGET_RATE)
        self._recognizer.SetWords(True)
        self._stream_rec = None

    def _make_recognizer(self):
        from vosk import KaldiRecognizer

        rec = KaldiRecognizer(self._model, TARGET_RATE)
        rec.SetWords(True)
        return rec

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        rec = self._make_recognizer()
        pcm = float32_to_int16_bytes(normalize_audio(audio, sample_rate))
        rec.AcceptWaveform(pcm)
        result = json.loads(rec.FinalResult())
        return (result.get("text") or "").strip()

    def start_stream(self) -> None:
        self._stream_rec = self._make_recognizer()

    def feed(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        if self._stream_rec is None:
            self.start_stream()
        pcm = float32_to_int16_bytes(normalize_audio(audio, sample_rate))
        rec = self._stream_rec
        if rec.AcceptWaveform(pcm):
            result = json.loads(rec.Result())
            return (result.get("text") or "").strip()
        partial = json.loads(rec.PartialResult())
        return (partial.get("partial") or "").strip()

    def end_stream(self) -> str:
        if self._stream_rec is None:
            return ""
        result = json.loads(self._stream_rec.FinalResult())
        self._stream_rec = None
        return (result.get("text") or "").strip()

    def close(self) -> None:
        self._stream_rec = None
        self._recognizer = None
        self._model = None


class WhisperCT2Engine(Engine):
    def __init__(self, info: ModelInfo) -> None:
        super().__init__(info)
        try:
            from faster_whisper import WhisperModel
        except ImportError as extra:
            raise TranscriptionError("بسته faster-whisper نصب نیست. pip install faster-whisper") from extra

        model_dir = info.files.get("model_dir") or info.path
        use_cuda = _cuda_available()
        device = "cuda" if use_cuda else "cpu"
        compute_type = "float16" if use_cuda else "int8"
        cpu_threads = max(4, os.cpu_count() or 4)
        self._model = WhisperModel(
            model_dir,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            num_workers=1,
        )
        try:
            english_only = not bool(self._model.model.is_multilingual)
        except Exception:
            english_only = False
        if english_only:
            raise TranscriptionError(
                "این مدل ویسپر به‌صورت English-only بارگذاری شد، بنابراین فارسی را به انگلیسی تبدیل می‌کند. "
                "فایل‌های tokenizer.json و vocabulary.json باید داخل پوشه whisper-persian-v4-ct2 باشند."
            )

    def _decode(self, samples: np.ndarray, extra: dict | None = None) -> str:
        options = persian_whisper_options()
        if extra:
            options.update(extra)
        try:
            segments, _info = self._model.transcribe(samples, **options)
        except TypeError:
            options.pop("multilingual", None)
            segments, _info = self._model.transcribe(samples, **options)
        parts = [segment.text.strip() for segment in segments if getattr(segment, "text", None)]
        return " ".join(parts).strip()

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        samples = normalize_audio(audio, sample_rate)
        if samples.size == 0:
            return ""
        text = self._decode(samples)
        if mostly_latin_script(text):
            retry = self._decode(
                samples,
                {"initial_prompt": "متن فارسی: این یک رونویسی گفتار فارسی است."},
            )
            if retry and not mostly_latin_script(retry):
                return retry
        return text

    def close(self) -> None:
        self._model = None


class SherpaCtcEngine(Engine):
    def __init__(self, info: ModelInfo) -> None:
        super().__init__(info)
        try:
            import sherpa_onnx
        except ImportError as extra:
            raise TranscriptionError("بسته sherpa-onnx نصب نیست. pip install sherpa-onnx") from extra

        model = info.files["model"]
        tokens = info.files["tokens"]
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=model,
            tokens=tokens,
            num_threads=max(1, min(4, os.cpu_count() or 2)),
            sample_rate=TARGET_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
        )
        self._model_dir = info.files.get("model_dir") or info.path

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        samples = normalize_audio(audio, sample_rate)
        if samples.size == 0:
            return ""
        stream = self._recognizer.create_stream()
        stream.accept_waveform(TARGET_RATE, samples.astype(np.float32))
        self._recognizer.decode_stream(stream)
        return _maybe_itn(self._model_dir, (stream.result.text or "").strip())

    def close(self) -> None:
        self._recognizer = None


class SherpaRnntEngine(Engine):
    def __init__(self, info: ModelInfo) -> None:
        super().__init__(info)
        try:
            import sherpa_onnx
        except ImportError as extra:
            raise TranscriptionError("بسته sherpa-onnx نصب نیست. pip install sherpa-onnx") from extra

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=info.files["encoder"],
            decoder=info.files["decoder"],
            joiner=info.files["joiner"],
            tokens=info.files["tokens"],
            model_type="nemo_transducer",
            num_threads=max(1, min(4, os.cpu_count() or 2)),
            sample_rate=TARGET_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
        )
        self._model_dir = info.files.get("model_dir") or info.path

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        samples = normalize_audio(audio, sample_rate)
        if samples.size == 0:
            return ""
        stream = self._recognizer.create_stream()
        stream.accept_waveform(TARGET_RATE, samples.astype(np.float32))
        self._recognizer.decode_stream(stream)
        return _maybe_itn(self._model_dir, (stream.result.text or "").strip())

    def close(self) -> None:
        self._recognizer = None


class NemoEngine(Engine):
    def __init__(self, info: ModelInfo) -> None:
        super().__init__(info)
        try:
            from nemo.collections.asr.models import ASRModel
        except ImportError as extra:
            raise TranscriptionError(
                "برای مدل .nemo باید nemo_toolkit نصب باشد: pip install 'nemo_toolkit[asr]'"
            ) from extra

        nemo_path = info.files["nemo"]
        self._model = ASRModel.restore_from(nemo_path, map_location="cpu")
        self._model.eval()
        try:
            self._model.change_decoding_strategy(decoder_type="ctc")
        except Exception:
            pass

    def transcribe(self, audio: np.ndarray, sample_rate: int = TARGET_RATE) -> str:
        import soundfile as sf
        import tempfile

        samples = normalize_audio(audio, sample_rate)
        if samples.size == 0:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            temp_path = handle.name
        try:
            sf.write(temp_path, samples, TARGET_RATE)
            output = self._model.transcribe([temp_path])
        finally:
            Path(temp_path).unlink(missing_ok=True)

        if not output:
            return ""
        first = output[0]
        if hasattr(first, "text"):
            return str(first.text).strip()
        if isinstance(first, str):
            return first.strip()
        return str(first).strip()

    def close(self) -> None:
        self._model = None


_ENGINE_BUILDERS = {
    "vosk": VoskEngine,
    "whisper_ct2": WhisperCT2Engine,
    "sherpa_ctc": SherpaCtcEngine,
    "sherpa_rnnt": SherpaRnntEngine,
    "nemo": NemoEngine,
}


def load_engine(info: ModelInfo) -> Engine:
    if info.engine in {"piper_tts", "unknown"}:
        raise TranscriptionError(info.note or "این مدل برای تشخیص گفتار قابل استفاده نیست.")
    builder = _ENGINE_BUILDERS.get(info.engine)
    if builder is None:
        raise TranscriptionError(f"موتور ناشناخته: {info.engine}")
    return builder(info)
