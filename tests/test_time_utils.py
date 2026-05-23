import unittest

from core.time_utils import duration_seconds, seconds_to_ffmpeg_time, timecode_to_seconds


class TimeUtilsTests(unittest.TestCase):
    def test_seconds_to_ffmpeg_time_supports_milliseconds(self):
        self.assertEqual(seconds_to_ffmpeg_time(70.5), "00:01:10.500")
        self.assertEqual(seconds_to_ffmpeg_time(3661.2345), "01:01:01.235")

    def test_duration_seconds_requires_positive_range(self):
        self.assertEqual(duration_seconds(70.5, 150.75), 80.25)
        with self.assertRaisesRegex(ValueError, "greater than"):
            duration_seconds(5, 5)

    def test_timecode_to_seconds_parses_qml_times(self):
        self.assertEqual(timecode_to_seconds("00:01:10"), 70.0)
        self.assertEqual(timecode_to_seconds("00:01:10.500"), 70.5)


if __name__ == "__main__":
    unittest.main()
