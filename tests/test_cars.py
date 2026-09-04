import unittest

from app.cars import match_vehicle
from app.booking import hours_panel, is_office_open, month_calendar
from datetime import date


class CarMatchTests(unittest.TestCase):
    def test_missing_letter_samand(self):
        hit = match_vehicle("سمن")
        self.assertEqual(hit.brand, "سمند")
        self.assertGreaterEqual(hit.score, 84)

    def test_dena_and_peugeot(self):
        self.assertEqual(match_vehicle("دنا").brand, "دنا")
        hit = match_vehicle("peugeot 206")
        self.assertEqual(hit.brand, "پژو")
        self.assertEqual(hit.model, "206")

    def test_chinese_and_korean_brands(self):
        self.assertEqual(match_vehicle("تیگو ۷").brand, "چری")
        self.assertEqual(match_vehicle("سوناتا").brand, "هیوندای")
        self.assertEqual(match_vehicle("فیدلیتی").brand, "فیدلیتی")


class PersianCalendarHoursTests(unittest.TestCase):
    def test_calendar_marks_friday_closed(self):
        friday = date(2026, 9, 4)
        self.assertFalse(is_office_open(friday))
        panel = hours_panel(friday)
        self.assertFalse(panel["open"])
        self.assertEqual(panel["all"], [])

    def test_focus_hours_always_list_slots_on_workday(self):
        data = month_calendar(1405, 6)
        self.assertEqual(data["weekend"], "جمعه")
        self.assertTrue(data["focus"]["all"])
        self.assertIn("شنبه", data["open_days"])


if __name__ == "__main__":
    unittest.main()
