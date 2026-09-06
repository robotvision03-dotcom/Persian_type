import unittest

from app.marketplace.engine import live_increment, minimum_next_bid, reserve_met, resolve_price, should_extend
from datetime import datetime, timedelta


class ResolvePriceTests(unittest.TestCase):
    def test_spec_example_a_beats_b(self):
        winner, price = resolve_price(
            1_300_000_000,
            5_000_000,
            [(1, 1_400_000_000, "2026-01-01T10:00:00"), (2, 1_350_000_000, "2026-01-01T10:01:00")],
        )
        self.assertEqual(winner, 1)
        self.assertEqual(price, 1_355_000_000)

    def test_spec_example_b_beats_a(self):
        winner, price = resolve_price(
            1_300_000_000,
            5_000_000,
            [(1, 1_400_000_000, "2026-01-01T10:00:00"), (2, 1_450_000_000, "2026-01-01T10:01:00")],
        )
        self.assertEqual(winner, 2)
        self.assertEqual(price, 1_405_000_000)

    def test_single_auto_stays_at_start(self):
        winner, price = resolve_price(1_300_000_000, 5_000_000, [(1, 1_400_000_000, "t")])
        self.assertEqual(winner, 1)
        self.assertEqual(price, 1_300_000_000)

    def test_same_max_earlier_wins(self):
        winner, price = resolve_price(
            1_300_000_000,
            5_000_000,
            [(1, 1_400_000_000, "2026-01-01T10:00:00"), (2, 1_400_000_000, "2026-01-01T10:05:00")],
        )
        self.assertEqual(winner, 1)
        self.assertEqual(price, 1_400_000_000)

    def test_live_increment_is_half_percent(self):
        self.assertEqual(live_increment(6_200_000, 10_000), 31_000)
        self.assertEqual(minimum_next_bid(6_200_000, 5_000_000, True), 6_231_000)
        self.assertEqual(live_increment(1_300_000_000, 10_000), 6_500_000)
        self.assertEqual(live_increment(100_000, 10_000), 10_000)
        self.assertEqual(minimum_next_bid(6_200_000, 10_000, False), 6_200_000)

    def test_reserve_and_sniping_window(self):
        self.assertTrue(reserve_met(200, 200))
        self.assertFalse(reserve_met(199, 200))
        now = datetime(2026, 1, 1, 12, 0, 0)
        end = now + timedelta(seconds=60)
        self.assertTrue(should_extend(now + timedelta(seconds=50), end, True, 120, 0, 3))
        self.assertFalse(should_extend(now + timedelta(seconds=50), end, True, 120, 3, 3))


if __name__ == "__main__":
    unittest.main()
