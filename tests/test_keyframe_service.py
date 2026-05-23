import unittest

from services.keyframe_service import KeyframeService


class KeyframeServiceTests(unittest.TestCase):
    def test_align_interval_expands_to_previous_and_next_keyframes(self):
        info = KeyframeService(ffmpeg_service=None).align_interval(
            [0, 32, 34, 40, 44, 72],
            requested_start=33,
            requested_end=42,
            duration_seconds=72,
        )

        self.assertEqual(info["safe_start"], 32)
        self.assertEqual(info["safe_end"], 44)
        self.assertEqual(info["previous_keyframe_start"], 32)
        self.assertEqual(info["next_keyframe_start"], 34)
        self.assertEqual(info["previous_keyframe_end"], 40)
        self.assertEqual(info["next_keyframe_end"], 44)
        self.assertEqual(info["extra_before"], 1)
        self.assertEqual(info["extra_after"], 2)


if __name__ == "__main__":
    unittest.main()
