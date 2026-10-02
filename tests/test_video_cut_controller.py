import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from controllers.video_cut.keyframe_alignment import KeyframeAlignmentController
from controllers.video_cut_controller import VideoCutController
from services.editing.cut_plan_service import CutPlanService
from services.editing.keyframe_service import KeyframeService
from services.export.export_router_service import FAST_CUTTING_MODE, SMART_CUTTING_MODE
from workers.worker_signals import WorkerSignals


class FakeThreadPool:
    def __init__(self):
        self.workers = []

    def start(self, worker):
        self.workers.append(worker)


class FakeVideoCutWorker:
    def __init__(self, job_key, request_data):
        self.job_key = job_key
        self.request_data = request_data
        self.signals = WorkerSignals()


class FakeSettingsService:
    def __init__(self):
        self.settings = SimpleNamespace(default_export_dir=None, export_dir=None)

    def load(self):
        return self.settings

    def update(self, **changes):
        for key, value in changes.items():
            setattr(self.settings, key, value)


class VideoCutControllerTests(unittest.TestCase):
    def _start_export(self, temp_dir):
        thread_pool = FakeThreadPool()
        controller = VideoCutController(
            thread_pool=thread_pool,
            worker_factory=FakeVideoCutWorker,
            settings_service=FakeSettingsService(),
        )
        input_path = Path(temp_dir) / "movie.mp4"
        input_path.touch()
        controller.exportSegments(
            str(input_path),
            [
                {
                    "start": "00:00:01",
                    "end": "00:00:02",
                    "timing_mode": "requested",
                }
            ],
            temp_dir,
            "remove_intervals",
        )
        return controller, thread_pool.workers[-1]

    def _finish_export(self, worker, output_path, warning=""):
        worker.signals.finished.emit(
            worker.job_key,
            {
                "result": {
                    "output_paths": [str(output_path)],
                    "duration_warning": warning,
                    "export_mode": "remove_intervals",
                    "cut_mode": "stream_copy",
                    "segments": [{"index": 1}],
                    "input_duration_seconds": 10.0,
                    "expected_output_duration_seconds": 9.0,
                    "actual_output_duration_seconds": 9.1,
                    "duration_difference_seconds": 0.1,
                }
            },
        )

    def test_success_exposes_output_path_warning_and_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, worker = self._start_export(temp_dir)
            output_path = Path(temp_dir) / "movie_removed_intervals.mp4"

            self._finish_export(worker, output_path, "Output duration differs by 0.1s")

        self.assertFalse(controller.cutBusy)
        self.assertEqual(controller.cutProgressValue, 100)
        self.assertEqual(controller.cutOutputPaths, [str(output_path)])
        self.assertEqual(controller.cutWarning, "Output duration differs by 0.1s")
        self.assertIn("Video export completed", controller.cutStatus)
        self.assertIn("Mode: remove_intervals", controller.cutDetails)

    def test_smart_success_exposes_output_path_and_subtitle_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_pool = FakeThreadPool()
            controller = VideoCutController(
                thread_pool=thread_pool,
                smart_worker_factory=FakeVideoCutWorker,
                settings_service=FakeSettingsService(),
            )
            input_path = Path(temp_dir) / "movie.mp4"
            input_path.touch()
            output_path = Path(temp_dir) / "movie_smart_cut.mp4"
            controller.exportSegments(
                str(input_path),
                [{"start": "00:00:01", "end": "00:00:02"}],
                temp_dir,
                "remove_intervals",
            )
            worker = thread_pool.workers[-1]

            worker.signals.finished.emit(
                worker.job_key,
                {
                    "result": {
                        "output_paths": [str(output_path)],
                        "subtitles": [
                            {
                                "status": "warning",
                                "message": "One subtitle stream was skipped.",
                            }
                        ],
                        "export_mode": "remove_intervals",
                        "cut_mode": "smart_cutting",
                        "segments": [{"start": "00:00:01", "end": "00:00:02"}],
                    }
                },
            )

        self.assertEqual(controller.cutOutputPaths, [str(output_path)])
        self.assertEqual(controller.cutWarning, "One subtitle stream was skipped.")
        self.assertIn("Smart Cutting export completed", controller.cutStatus)

    def test_failure_exposes_error_information(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, worker = self._start_export(temp_dir)

            worker.signals.error.emit(worker.job_key, "FFmpeg could not write output.mp4")

        self.assertFalse(controller.cutBusy)
        self.assertEqual(controller.cutStatus, "Video export failed")
        self.assertEqual(controller.cutError, "FFmpeg could not write output.mp4")
        self.assertEqual(controller.cutOutputPaths, [])

    def test_starting_new_export_clears_previous_terminal_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, first_worker = self._start_export(temp_dir)
            output_path = Path(temp_dir) / "movie_removed_intervals.mp4"
            self._finish_export(first_worker, output_path, "Previous warning")

            controller.exportSegments(
                str(Path(temp_dir) / "movie.mp4"),
                [
                    {
                        "start": "00:00:03",
                        "end": "00:00:04",
                        "timing_mode": "requested",
                    }
                ],
                temp_dir,
                "remove_intervals",
            )

        self.assertTrue(controller.cutBusy)
        self.assertEqual(controller.cutProgressValue, 0)
        self.assertEqual(controller.cutError, "")
        self.assertEqual(controller.cutWarning, "")
        self.assertEqual(controller.cutDetails, "")
        self.assertEqual(controller.cutOutputPaths, [])

    def test_clear_export_result_removes_terminal_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, worker = self._start_export(temp_dir)
            self._finish_export(worker, Path(temp_dir) / "movie_removed_intervals.mp4")

            controller.clearExportResult()

        self.assertEqual(controller.cutStatus, "Video export idle")
        self.assertEqual(controller.cutProgressValue, 0)
        self.assertEqual(controller.cutError, "")
        self.assertEqual(controller.cutWarning, "")
        self.assertEqual(controller.cutDetails, "")
        self.assertEqual(controller.cutOutputPaths, [])

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
