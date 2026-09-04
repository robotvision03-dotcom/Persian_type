import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.dialogue import GREETING
from app.server import AppState


class DummyEngine:
    supports_stream = False

    def transcribe(self, audio, sample_rate=16000):
        return "پژو"

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
            db_path = root / "book.sqlite"
            app_state = AppState(root, db_path=db_path)
            snapshot = app_state.snapshot()
            self.assertEqual(snapshot["asr"]["id"], "shenava-koochik-ctc")
            self.assertEqual(snapshot["llm_model"], "llama3.2:3b")

    def test_boot_and_transcribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_shenava_dir(root)
            app_state = AppState(root, db_path=root / "book.sqlite")
            dummy = DummyEngine()
            with patch("app.server.load_engine", return_value=dummy):
                snapshot = app_state.boot()
                self.assertTrue(snapshot["ready"])
                text = app_state.transcribe(np.zeros(16000, dtype=np.float32))
            self.assertEqual(text, "پژو")

    def test_boot_without_shenava_still_allows_text_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_state = AppState(root, db_path=root / "book.sqlite")
            snapshot = app_state.boot()
            self.assertFalse(snapshot["ready"])
            started = app_state.dialogue.start("x")
            self.assertEqual(started["reply"], GREETING)


if __name__ == "__main__":
    unittest.main()
