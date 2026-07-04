import unittest
import tempfile
from pathlib import Path

from controllers.video_cut.keyframe_alignment import KeyframeAlignmentController
from controllers.video_cut_controller import VideoCutController
from services.export.export_router_service import FAST_CUTTING_MODE, SMART_CUTTING_MODE
from services.editing.cut_plan_service import CutPlanService
from services.editing.keyframe_service import KeyframeService


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

    def test_default_export_segments_route_to_smart_cutting(self):
        controller = VideoCutController()

        mode = controller._cutting_mode_for_segments([{"start": "00:00:01", "end": "00:00:03"}])

        self.assertEqual(mode, SMART_CUTTING_MODE)

    def test_requested_timing_routes_to_fast_cutting(self):
        controller = VideoCutController()

        mode = controller._cutting_mode_for_segments(
            [{"start": "00:00:01", "end": "00:00:03", "timingMode": "requested"}]
        )

        self.assertEqual(mode, FAST_CUTTING_MODE)


class KeyframeAlignmentControllerTests(unittest.TestCase):
    def test_cached_keyframes_are_used_without_triggering_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService(
                keyframe_probe=lambda *_args, **_kwargs: self.fail(
                    "Set End must not trigger keyframe extraction."
                )
            )
            request = service.request_indexing(video)
            service.complete_indexing(video, request.job_token, [0.0, 5.0, 10.0, 15.0])
            controller = KeyframeAlignmentController(service, CutPlanService())

            info = controller.get_cut_info(str(video), "00:00:06", "00:00:09", 15.0)

        self.assertTrue(info["valid"])
        self.assertEqual(info["safe_start"], 5.0)
        self.assertEqual(info["safe_end"], 10.0)

    def test_loading_cache_returns_immediately_without_triggering_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService(
                keyframe_probe=lambda *_args, **_kwargs: self.fail(
                    "Set End must not trigger keyframe extraction."
                )
            )
            service.request_indexing(video)
            controller = KeyframeAlignmentController(service)

            info = controller.get_cut_info(str(video), "00:00:01", "00:00:02", 10.0)

        self.assertFalse(info["valid"])
        self.assertIn("still being indexed", info["error"])

    def test_failed_cache_returns_error_without_triggering_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService(
                keyframe_probe=lambda *_args, **_kwargs: self.fail(
                    "Set End must not trigger keyframe extraction."
                )
            )
            request = service.request_indexing(video)
            service.fail_indexing(video, request.job_token, "ffprobe failed")
            controller = KeyframeAlignmentController(service)

            info = controller.get_cut_info(str(video), "00:00:01", "00:00:02", 10.0)

        self.assertFalse(info["valid"])
        self.assertIn("Keyframe analysis failed: ffprobe failed", info["error"])


if __name__ == "__main__":
    unittest.main()
