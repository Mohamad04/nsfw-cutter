import unittest

from core.time_intervals import invert_removed_intervals, normalize_intervals


class TimeIntervalTests(unittest.TestCase):
    def test_invert_removed_interval_keeps_before_and_after_ranges(self):
        self.assertEqual(
            invert_removed_intervals([(33.0, 42.0)], 72.0),
            [(0.0, 33.0), (42.0, 72.0)],
        )

    def test_multiple_removed_intervals_invert_in_order(self):
        self.assertEqual(
            invert_removed_intervals([(10, 20), (35, 40), (90, 100)], 120),
            [(0.0, 10.0), (20.0, 35.0), (40.0, 90.0), (100.0, 120.0)],
        )

    def test_overlapping_intervals_normalize_before_inversion(self):
        self.assertEqual(normalize_intervals([(10, 20), (18, 30)], 72), [(10.0, 30.0)])

    def test_invalid_interval_rejects_reversed_range(self):
        with self.assertRaisesRegex(ValueError, "after start"):
            normalize_intervals([(42, 33)], 72)


if __name__ == "__main__":
    unittest.main()
