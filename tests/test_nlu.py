import unittest

from app.nlu import parse_slots, next_missing_phase


class SlotFillTests(unittest.TestCase):
    def test_brand_and_model_together(self):
        slots = parse_slots("peugeot 206", "ask_car")
        self.assertEqual(slots["car_name"], "پژو")
        self.assertEqual(slots["car_model"], "206")
        self.assertIsNone(slots["km"])

    def test_does_not_treat_206_as_mileage(self):
        slots = parse_slots("پژو ۲۰۶", "ask_car")
        self.assertEqual(slots["car_model"], "206")
        self.assertIsNone(slots["km"])

    def test_overanswer_km_in_same_turn(self):
        slots = parse_slots("پژو ۲۰۶ ۸۰۰۰۰ کیلومتر", "ask_car")
        self.assertEqual(slots["car_name"], "پژو")
        self.assertEqual(slots["car_model"], "206")
        self.assertEqual(slots["km"], 80000)

    def test_next_phase_skips_filled_model(self):
        self.assertEqual(next_missing_phase("پژو", "206", None, ""), "ask_km")
        self.assertEqual(next_missing_phase("پژو", "", None, ""), "ask_model")

    def test_partial_letters_resolve_samand(self):
        slots = parse_slots("سمن", "ask_car")
        self.assertEqual(slots["car_name"], "سمند")

    def test_zero_km_word(self):
        slots = parse_slots("صفر", "ask_km")
        self.assertEqual(slots["km"], 0)


if __name__ == "__main__":
    unittest.main()
