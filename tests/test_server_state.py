import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.dialogue import ASK_KM, GREETING
from app.server import AppState, app, reset_state

try:
    from fastapi.testclient import TestClient
except Exception:  # starlette may require httpx/httpx2
    TestClient = None

ROOT = Path(__file__).resolve().parent.parent


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
            self.assertEqual(snapshot["open_days"], "شنبه تا پنجشنبه")
            self.assertTrue(snapshot["hours_panel"]["all"])

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

    def test_ui_has_single_call_button(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("شروع تماس", html)
        self.assertIn('id="call-btn"', html)
        self.assertNotIn("صحبت کن", html)
        self.assertNotIn('id="stop-btn"', html)
        self.assertNotIn('id="start-btn"', html)
        self.assertIn("ثبت‌شده بدون نوبت", html)
        self.assertIn('id="followups"', html)

    @unittest.skipUnless(TestClient, "httpx is required for the live websocket test")
    def test_live_endpoint_asks_next_question_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_shenava_dir(root)
            app_state = reset_state(root, db_path=root / "book.sqlite")
            dummy = DummyEngine()
            dummy.transcribe = lambda audio, sample_rate=16000: "peugeot 206"
            app_state.engine = dummy
            app_state.dialogue.start("live1")
            client = TestClient(app)
            with client.websocket_connect("/ws/stream") as ws:
                self.assertEqual(ws.receive_json()["type"], "status")
                ws.send_text(json.dumps({"session_id": "live1", "type": "start"}))
                ws.send_bytes(np.zeros(int(16000 * 0.3), dtype=np.int16).tobytes())
                ws.send_text(json.dumps({"type": "endpoint", "session_id": "live1"}))
                message = ws.receive_json()
                self.assertEqual(message["type"], "assistant")
                self.assertEqual(message["text"], "peugeot 206")
                self.assertEqual(message["turn"]["phase"], "ask_km")
                self.assertEqual(message["turn"]["reply"], ASK_KM)
                ws.send_text(json.dumps({"type": "hangup", "session_id": "live1"}))

    @unittest.skipUnless(TestClient, "httpx is required for the followups API test")
    def test_followups_list_unbooked_after_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_shenava_dir(root)
            reset_state(root, db_path=root / "book.sqlite")
            client = TestClient(app)
            client.post("/api/call/start", json={"session_id": "s1"})
            client.post("/api/call/turn", json={"session_id": "s1", "text": "پژو"})
            client.post("/api/call/turn", json={"session_id": "s1", "text": "پارس"})
            client.post("/api/call/turn", json={"session_id": "s1", "text": "۸۰۰۰۰"})
            turn = client.post("/api/call/turn", json={"session_id": "s1", "text": "علی رضایی"}).json()
            self.assertTrue(turn["end_call"])
            self.assertIn("روز خوبی", turn["reply"])
            rows = client.get("/api/followups").json()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["customer_name"], "علی رضایی")
            self.assertEqual(rows[0]["status"], "pending")
            self.assertIn("whatsapp_url", rows[0])
            self.assertEqual(client.get("/api/reminders/due").json(), [])


if __name__ == "__main__":
    unittest.main()
