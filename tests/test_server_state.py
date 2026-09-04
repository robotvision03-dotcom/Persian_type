import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.server import AppState


class DummyEngine:
    supports_stream = False

    def transcribe(self, audio, sample_rate=16000):
        return "سلام دنیا"

    def start_stream(self):
        return None

    def feed(self, audio, sample_rate=16000):
        return ""

    def end_stream(self):
        return ""

    def close(self):
        return None


def make_shenava_dir(root: Path) -> Path:
    model = root / "shenava-koochik-ctc"
    model.mkdir()
    (model / "model.onnx").write_bytes(b"x")
    (model / "tokens.txt").write_text("a 0\n")
    return model


class AppStateTests(unittest.TestCase):
    def test_snapshot_uses_only_shenava_ctc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_shenava_dir(root)
            vosk = root / "vosk-model-fa"
            vosk.mkdir()
            (vosk / "am").mkdir()
            (vosk / "am" / "final.mdl").write_bytes(b"x")
            app_state = AppState(root)
            snapshot = app_state.snapshot()
            self.assertEqual(snapshot["asr"]["id"], "shenava-koochik-ctc")
            self.assertFalse(snapshot["ready"])

    def test_boot_and_transcribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_shenava_dir(root)
            app_state = AppState(root)
            dummy = DummyEngine()
            with patch("app.server.load_engine", return_value=dummy):
                snapshot = app_state.boot()
                self.assertTrue(snapshot["ready"])
                audio = np.zeros(16000, dtype=np.float32)
                result = app_state.transcribe_current(audio)
            self.assertEqual(result["text"], "سلام دنیا")
            self.assertEqual(app_state.last_transcript, "سلام دنیا")

    def test_boot_without_shenava(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            piper = root / "piper-voice-fa"
            piper.mkdir()
            (piper / "voice.onnx.json").write_text("{}")
            app_state = AppState(root)
            with self.assertRaises(Exception):
                app_state.boot()


if __name__ == "__main__":
    unittest.main()
