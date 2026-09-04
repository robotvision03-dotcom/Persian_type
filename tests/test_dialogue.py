import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.dialogue import ASK_KM, ASK_MODEL, ASK_NAME, GREETING, DialogueManager, parse_km


class ParseKmTests(unittest.TestCase):
    def test_digits_and_persian(self):
        self.assertEqual(parse_km("80000"), 80000)
        self.assertEqual(parse_km("۸۰ هزار"), 80000)


class DialogueTests(unittest.TestCase):
    def test_full_booking_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            manager = DialogueManager(db_path=db_path)
            with patch("app.dialogue.extract_answer", side_effect=lambda phase, text: text):
                start = manager.start("s1")
                self.assertEqual(start["reply"], GREETING)
                self.assertEqual(manager.handle("s1", "پژو")["reply"], ASK_MODEL)
                self.assertEqual(manager.handle("s1", "پارس")["reply"], ASK_KM)
                self.assertEqual(manager.handle("s1", "۸۰۰۰۰")["reply"], ASK_NAME)
                after_name = manager.handle("s1", "علی رضایی")
                self.assertEqual(after_name["phase"], "ask_slot")
                self.assertIn("بله", after_name["reply"])
                booked = manager.handle("s1", "بله")
            self.assertEqual(booked["phase"], "booked")
            self.assertIsNotNone(booked["appointment_id"])
            self.assertEqual(booked["customer"]["name"], "علی رضایی")
            self.assertEqual(booked["customer"]["car_name"], "پژو")


if __name__ == "__main__":
    unittest.main()
