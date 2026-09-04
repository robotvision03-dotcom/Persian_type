import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.booking import create_invite, due_reminders, init_db
from app.server import process_due_reminders
from app.whatsapp import attach_message, send_text, send_via_whatsapp_web, software_number, web_send_url


class WhatsAppSendTests(unittest.TestCase):
    def test_software_number(self):
        self.assertEqual(software_number(), "+989032901549")

    def test_send_uses_software_line_to_customer(self):
        sent = []

        def fake_post_form(url, payload):
            sent.append((url, payload))
            return True, '{"sent":true}'

        with patch.dict(
            "os.environ",
            {"ULTRAMSG_INSTANCE": "inst1", "ULTRAMSG_TOKEN": "tok1", "WHATSAPP_FROM": "+989032901549"},
            clear=False,
        ):
            with patch("app.whatsapp._post_form", side_effect=fake_post_form):
                result = send_text("+989032901549", "لینک تقویم")
        self.assertTrue(result["ok"])
        self.assertEqual(result["from"], "+989032901549")
        self.assertEqual(result["to"], "+989032901549")
        self.assertEqual(sent[0][1]["to"], "+989032901549")
        self.assertEqual(sent[0][1]["body"], "لینک تقویم")

    def test_attach_message_has_no_click_url(self):
        extra = attach_message(
            {
                "token": "abc",
                "customer_name": "علی رضایی",
                "car_name": "پژو",
                "car_model": "206",
                "phone": "+989032901549",
                "calendar_path": "/book/abc",
            },
            "http://desk.local",
        )
        self.assertEqual(extra["from_number"], "+989032901549")
        self.assertIn("http://desk.local/book/abc", extra["whatsapp_text"])
        self.assertNotIn("whatsapp_url", extra)

    def test_due_reminder_is_sent_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            created = datetime(2026, 9, 4, 10, 0, 0)
            invite = create_invite(
                "علی رضایی",
                "پژو",
                "206",
                80000,
                db_path=db_path,
                now=created,
            )
            self.assertEqual(len(due_reminders(now=datetime(2026, 9, 4, 11, 0, 0), db_path=db_path)), 1)
            sent = {
                "ok": True,
                "from": "+989032901549",
                "to": "+989032901549",
                "provider": "test",
                "error": "",
            }
            with patch("app.server.send_text", return_value=sent):
                out = process_due_reminders(
                    now=datetime(2026, 9, 4, 11, 0, 0),
                    origin="http://desk.local",
                    db_path=db_path,
                )
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["whatsapp_sent"]["ok"])
            self.assertIn("یادآوری", out[0]["whatsapp_text"])
            self.assertEqual(due_reminders(now=datetime(2026, 9, 4, 11, 0, 0), db_path=db_path), [])
            leftover = invite["token"]
            self.assertTrue(leftover)

    def test_web_send_url_goes_to_customer(self):
        url = web_send_url("+989032901549", "سلام تست")
        self.assertIn("web.whatsapp.com/send", url)
        self.assertIn("989032901549", url)
        self.assertIn("%D8%B3%D9%84%D8%A7%D9%85", url)

    def test_windows_web_session_is_used_without_api(self):
        with patch("app.whatsapp.send_via_whatsapp_web", return_value={"ok": True, "provider": "whatsapp-web"}):
            with patch("app.whatsapp._can_use_whatsapp_web", return_value=True):
                result = send_text("+989032901549", "لینک تقویم")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "whatsapp-web")
        self.assertTrue(result["queued"])

    def test_whatsapp_web_opens_chat_and_presses_send(self):
        with patch("app.whatsapp._open_whatsapp_tab", return_value="chrome") as opened:
            with patch("app.whatsapp._press_send") as pressed:
                with patch("app.whatsapp.time.sleep"):
                    result = send_via_whatsapp_web("+989032901549", "سلام")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "whatsapp-web")
        opened.assert_called_once()
        self.assertIn("989032901549", opened.call_args[0][0])
        pressed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
