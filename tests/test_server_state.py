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


def make_vosk_dir(root: Path) -> Path:
    model = root / "vosk-model-fa"
    (model / "am").mkdir(parents=True)
    (model / "conf").mkdir()
    (model / "am" / "final.mdl").write_bytes(b"x")
    (model / "conf" / "model.conf").write_text("ok")
    return model


class AppStateTests(unittest.TestCase):
    def test_snapshot_lists_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_vosk_dir(root)
            piper = root / "piper-voice-fa"
            piper.mkdir()
            (piper / "voice.onnx.json").write_text("{}")
            app_state = AppState(root)
            snapshot = app_state.snapshot()
            ids = [item["id"] for item in snapshot["models"]]
            self.assertIn("vosk-model-fa", ids)
            self.assertIn("piper-voice-fa", ids)
            piper_row = next(item for item in snapshot["models"] if item["id"] == "piper-voice-fa")
            self.assertFalse(piper_row["usable"])

    def test_select_and_transcribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_vosk_dir(root)
            app_state = AppState(root)
            dummy = DummyEngine()
            with patch("app.server.load_engine", return_value=dummy):
                app_state.select("vosk-model-fa")
                audio = np.zeros(16000, dtype=np.float32)
                result = app_state.transcribe_current(audio)
            self.assertEqual(result["text"], "سلام دنیا")
            self.assertEqual(app_state.active_id, "vosk-model-fa")
            self.assertEqual(app_state.results["vosk-model-fa"]["text"], "سلام دنیا")

    def test_select_rejects_piper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            piper = root / "piper-voice-fa"
            piper.mkdir()
            (piper / "voice.onnx.json").write_text("{}")
            app_state = AppState(root)
            with self.assertRaises(Exception):
                app_state.select("piper-voice-fa")


if __name__ == "__main__":
    unittest.main()
