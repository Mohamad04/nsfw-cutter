import unittest

from services.keyframe_service import KeyframeService, compute_safe_cut


class KeyframeServiceTests(unittest.TestCase):
    def test_compute_safe_cut_expands_non_keyframe_request(self):
        safe_start, safe_end = compute_safe_cut(
            requested_start=12.3,
            requested_end=18.7,
            keyframes=[0.0, 5.0, 10.0, 15.0, 20.0],
        )

        self.assertEqual(safe_start, 10.0)
        self.assertEqual(safe_end, 20.0)

    def test_compute_safe_cut_preserves_exact_keyframe_request(self):
        safe_start, safe_end = compute_safe_cut(
            requested_start=5.0,
            requested_end=10.0,
            keyframes=[0.0, 5.0, 10.0, 15.0],
        )

        self.assertEqual(safe_start, 5.0)
        self.assertEqual(safe_end, 10.0)

    def test_compute_safe_cut_uses_zero_boundary_before_first_keyframe(self):
        safe_start, safe_end = compute_safe_cut(
            requested_start=1.0,
            requested_end=9.0,
            keyframes=[3.0, 8.0, 13.0],
            video_duration=20.0,
        )

        self.assertEqual(safe_start, 0.0)
        self.assertEqual(safe_end, 13.0)

    def test_compute_safe_cut_rejects_missing_keyframes(self):
        with self.assertRaisesRegex(ValueError, "Keyframe data unavailable"):
            compute_safe_cut(
                requested_start=1.0,
                requested_end=2.0,
                keyframes=[],
                video_duration=20.0,
            )

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
