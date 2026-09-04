import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from app.booking import (
    available_slots,
    book_appointment,
    book_invite,
    create_invite,
    due_reminders,
    get_invite,
    init_db,
    is_office_open,
    list_appointments,
    list_unbooked_invites,
    mark_reminder_sent,
    next_open_slots,
    slot_times,
    whatsapp_send_url,
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

    def test_whatsapp_invite_books_from_calendar(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            invite = create_invite("علی رضایی", "پژو", "206", 80000, db_path=db_path)
            self.assertEqual(invite["phone"], "+989032901549")
            slot = next_open_slots(1, db_path)[0]
            booked = book_invite(invite["token"], slot["date"], slot["time"], db_path)
            self.assertGreater(booked["id"], 0)
            rows = list_appointments(db_path)
            self.assertEqual(rows[0]["phone"], "+989032901549")
            url = whatsapp_send_url("لینک", "+989032901549")
            self.assertIn("wa.me/989032901549", url)

    def test_next_open_slots_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            found = next_open_slots(2, db_path)
            self.assertEqual(len(found), 2)
            self.assertIn("ساعت", found[0]["label"])

    def test_unbooked_invite_is_listed_for_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            create_invite("علی رضایی", "پژو", "206", 80000, db_path=db_path)
            rows = list_unbooked_invites(db_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["customer_name"], "علی رضایی")
            self.assertEqual(rows[0]["status"], "pending")
            self.assertEqual(rows[0]["followup_label"], "منتظر انتخاب وقت")

    def test_reminders_fire_then_stop_after_five(self):
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
            self.assertEqual(invite["next_reminder_at"], "2026-09-04T11:00:00")
            self.assertEqual(due_reminders(now=datetime(2026, 9, 4, 10, 30, 0), db_path=db_path), [])
            due = due_reminders(now=datetime(2026, 9, 4, 11, 0, 0), db_path=db_path)
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["token"], invite["token"])

            first = mark_reminder_sent(invite["token"], now=datetime(2026, 9, 4, 11, 0, 0), db_path=db_path)
            self.assertEqual(first["reminder_count"], 1)
            self.assertEqual(first["next_reminder_at"], "2026-09-04T15:00:00")
            self.assertEqual(first["status"], "pending")

            schedule = [
                datetime(2026, 9, 4, 15, 0, 0),
                datetime(2026, 9, 5, 10, 0, 0),
                datetime(2026, 9, 6, 10, 0, 0),
                datetime(2026, 9, 7, 10, 0, 0),
            ]
            updated = first
            for when in schedule:
                updated = mark_reminder_sent(invite["token"], now=when, db_path=db_path)
            self.assertEqual(updated["reminder_count"], 5)
            self.assertEqual(updated["status"], "stopped")
            self.assertIsNone(updated["next_reminder_at"])
            self.assertTrue(updated["needs_admin_call"])
            self.assertEqual(due_reminders(now=datetime(2026, 9, 10, 10, 0, 0), db_path=db_path), [])
            leftover = list_unbooked_invites(db_path)
            self.assertEqual(leftover[0]["status"], "stopped")

    def test_booking_cancels_reminders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "book.sqlite"
            init_db(db_path)
            invite = create_invite("علی رضایی", "پژو", "206", 80000, db_path=db_path)
            slot = next_open_slots(1, db_path)[0]
            booked = book_invite(invite["token"], slot["date"], slot["time"], db_path)
            self.assertGreater(booked["id"], 0)
            row = get_invite(invite["token"], db_path)
            self.assertEqual(row["status"], "booked")
            self.assertIsNone(row["next_reminder_at"])
            self.assertEqual(list_unbooked_invites(db_path), [])
            self.assertEqual(
                due_reminders(now=datetime.now() + timedelta(days=10), db_path=db_path),
                [],
            )


if __name__ == "__main__":
    unittest.main()
