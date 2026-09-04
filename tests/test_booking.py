import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app.booking import (
    available_slots,
    book_appointment,
    init_db,
    is_office_open,
    list_appointments,
    next_open_slots,
    slot_times,
)
from app.jalali import format_jalali, from_jalali, to_jalali


class JalaliTests(unittest.TestCase):
    def test_roundtrip(self):
        day = date(2026, 9, 4)
        jy, jm, jd = to_jalali(day)
        self.assertEqual(from_jalali(jy, jm, jd), day)

    def test_format_has_persian_month(self):
        label = format_jalali(date(2026, 9, 4))
        self.assertTrue(any(month in label for month in ("شهریور", "مهر")))


class BookingTests(unittest.TestCase):
    def test_office_hours_persian_week(self):
        friday = date(2026, 9, 4)
        saturday = date(2026, 9, 5)
        monday = date(2026, 9, 7)
        thursday = date(2026, 9, 10)
        self.assertFalse(is_office_open(friday))
        self.assertTrue(is_office_open(saturday))
        self.assertTrue(is_office_open(monday))
        self.assertTrue(is_office_open(thursday))
        self.assertEqual(slot_times()[0], "09:00")
        self.assertEqual(slot_times()[-1], "16:30")

    def test_book_adds_customer_and_blocks_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            found = next_open_slots(1, db_path)
            self.assertTrue(found)
            slot = found[0]
            appt_id = book_appointment("علی رضایی", "پژو", "پارس", 80000, slot["date"], slot["time"], db_path)
            self.assertGreater(appt_id, 0)
            self.assertNotIn(slot["time"], available_slots(slot["date"], db_path))
            rows = list_appointments(db_path)
            self.assertEqual(rows[0]["customer_name"], "علی رضایی")

    def test_next_open_slots_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            found = next_open_slots(2, db_path)
            self.assertEqual(len(found), 2)
            self.assertIn("ساعت", found[0]["label"])


if __name__ == "__main__":
    unittest.main()
