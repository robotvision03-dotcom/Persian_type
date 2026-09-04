import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.discovery import ModelInfo
from app.engines import mostly_latin_script, persian_whisper_options


class LatinDetectTests(unittest.TestCase):
    def test_english_is_latin(self):
        self.assertTrue(mostly_latin_script("This is a test sentence"))

    def test_persian_is_not_latin(self):
        self.assertFalse(mostly_latin_script("این یک جمله فارسی است"))


class WhisperOptionsTests(unittest.TestCase):
    def test_forces_persian_transcribe_and_greedy_decode(self):
        options = persian_whisper_options()
        self.assertEqual(options["language"], "fa")
        self.assertEqual(options["task"], "transcribe")
        self.assertEqual(options["beam_size"], 1)
        self.assertFalse(options["vad_filter"])
        self.assertFalse(options["condition_on_previous_text"])


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisperModel:
    last_kwargs = None
    replies: list[str] = ["hello there everyone"]

    def __init__(self, *args, **kwargs) -> None:
        self.model = SimpleNamespace(is_multilingual=True)

    def transcribe(self, audio, **kwargs):
        FakeWhisperModel.last_kwargs = kwargs
        text = FakeWhisperModel.replies.pop(0) if FakeWhisperModel.replies else ""
        return iter([FakeSegment(text)]), None


class WhisperEngineTests(unittest.TestCase):
    def test_retries_when_first_pass_is_english(self):
        FakeWhisperModel.replies = ["This is English output", "سلام بر همه"]
        info = ModelInfo(
            id="whisper-persian-v4-ct2",
            name="Whisper",
            name_fa="ویسپر",
            path="/tmp/whisper",
            engine="whisper_ct2",
            usable=True,
            files={"model_dir": "/tmp/whisper"},
        )
        fake_module = SimpleNamespace(WhisperModel=FakeWhisperModel)
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            from app.engines import WhisperCT2Engine

            engine = WhisperCT2Engine(info)
            text = engine.transcribe(np.zeros(16000, dtype=np.float32))
        self.assertEqual(text, "سلام بر همه")
        self.assertEqual(FakeWhisperModel.last_kwargs["language"], "fa")
        self.assertEqual(FakeWhisperModel.last_kwargs["task"], "transcribe")

    def test_rejects_english_only_checkpoint(self):
        class EnglishOnly(FakeWhisperModel):
            def __init__(self, *args, **kwargs) -> None:
                self.model = SimpleNamespace(is_multilingual=False)

        info = ModelInfo(
            id="whisper-persian-v4-ct2",
            name="Whisper",
            name_fa="ویسپر",
            path="/tmp/whisper",
            engine="whisper_ct2",
            usable=True,
            files={"model_dir": "/tmp/whisper"},
        )
        fake_module = SimpleNamespace(WhisperModel=EnglishOnly)
        with patch.dict(sys.modules, {"faster_whisper": fake_module}):
            from app.engines import WhisperCT2Engine

            with self.assertRaises(Exception):
                WhisperCT2Engine(info)


if __name__ == "__main__":
    unittest.main()
