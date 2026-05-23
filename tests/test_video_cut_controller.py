import unittest

from controllers.video_cut_controller import VideoCutController


class VideoCutControllerTests(unittest.TestCase):
    def test_segment_payload_prefers_safe_keyframe_interval_for_export(self):
        controller = VideoCutController()

        payload = controller._segment_to_payload(
            1,
            {
                "start": "00:00:33",
                "end": "00:00:42",
                "safeStart": "00:00:32",
                "safeEnd": "00:00:44",
                "previousKeyframeStart": "00:00:32",
                "nextKeyframeStart": "00:00:34",
                "previousKeyframeEnd": "00:00:40",
                "nextKeyframeEnd": "00:00:44",
            },
        )

        self.assertEqual(payload["requested_start_seconds"], 33)
        self.assertEqual(payload["requested_end_seconds"], 42)
        self.assertEqual(payload["start_seconds"], 32)
        self.assertEqual(payload["end_seconds"], 44)
        self.assertEqual(payload["previous_keyframe_start"], 32)
        self.assertEqual(payload["next_keyframe_end"], 44)


if __name__ == "__main__":
    unittest.main()
