import unittest

from app.cars import match_vehicle
from app.nlu import parse_km, parse_slots
from app.numbers import digitize_text, parse_clock, parse_int


class SpokenNumberTests(unittest.TestCase):
    def test_two_hundred_six_is_206(self):
        self.assertEqual(parse_int("دویست و شش"), 206)
        self.assertEqual(digitize_text("خودرو دویست و شش"), "206")
        self.assertEqual(parse_int("دو صفر شش"), 206)

    def test_odometer_words(self):
        self.assertEqual(parse_km("هشتاد هزار"), 80000)
        self.assertEqual(parse_km("صد و بیست هزار کیلومتر"), 120000)
        self.assertEqual(parse_km("۸۰ هزار"), 80000)

    def test_clock_words(self):
        self.assertEqual(parse_clock("نه و نیم"), "09:30")
        self.assertEqual(parse_clock("ساعت شانزده"), "16:00")
        self.assertEqual(parse_clock("چهار عصر"), "16:00")


class SpokenCarTests(unittest.TestCase):
    def test_dooyist_o_shesh_is_peugeot_206(self):
        hit = match_vehicle("دویست و شش")
        self.assertEqual(hit.brand, "پژو")
        self.assertEqual(hit.model, "206")

        slots = parse_slots("دویست و شش", "ask_car")
        self.assertEqual(slots["car_name"], "پژو")
        self.assertEqual(slots["car_model"], "206")
        self.assertIsNone(slots["km"])

    def test_car_word_plus_spoken_number(self):
        hit = match_vehicle("خودرو دویست و شش")
        self.assertEqual(hit.model, "206")
        self.assertEqual(match_vehicle("چهارصد و پنج").model, "405")


if __name__ == "__main__":
    unittest.main()
