import tempfile
import unittest
from pathlib import Path

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
            start = manager.start("s1")
            self.assertEqual(start["reply"], GREETING)
            self.assertTrue(start["hours"]["all"])
            self.assertIn("شنبه", start["hours"]["open_days"])
            self.assertEqual(manager.handle("s1", "پژو")["phase"], "ask_model")
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

    def test_peugeot_206_skips_model_and_asks_km(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DialogueManager(db_path=Path(tmp) / "book.sqlite")
            manager.start("s1")
            turn = manager.handle("s1", "peugeot 206")
            self.assertEqual(turn["phase"], "ask_km")
            self.assertEqual(turn["reply"], ASK_KM)
            self.assertEqual(turn["customer"]["car_name"], "پژو")
            self.assertEqual(turn["customer"]["car_model"], "206")

    def test_persian_peugeot_206_skips_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DialogueManager(db_path=Path(tmp) / "book.sqlite")
            manager.start("s1")
            turn = manager.handle("s1", "پژو ۲۰۶")
            self.assertEqual(turn["phase"], "ask_km")
            self.assertEqual(turn["customer"]["car_name"], "پژو")
            self.assertEqual(turn["customer"]["car_model"], "206")

    def test_typo_peguete_206(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DialogueManager(db_path=Path(tmp) / "book.sqlite")
            manager.start("s1")
            turn = manager.handle("s1", "peguete 206")
            self.assertEqual(turn["reply"], ASK_KM)
            self.assertEqual(turn["customer"]["car_model"], "206")

    def test_partial_samand_letters(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = DialogueManager(db_path=Path(tmp) / "book.sqlite")
            manager.start("s1")
            turn = manager.handle("s1", "سمن")
            self.assertEqual(turn["customer"]["car_name"], "سمند")
            self.assertEqual(turn["phase"], "ask_model")


if __name__ == "__main__":
    unittest.main()
