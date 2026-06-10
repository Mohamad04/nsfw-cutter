import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.editing.cut_plan_service import CutPlanService, compute_safe_cut
from services.editing.keyframe_service import KeyframeService
from services.infrastructure.ffmpeg.probe import extract_keyframes


class KeyframeServiceTests(unittest.TestCase):
    def test_request_indexing_sets_loading_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService()

            request = service.request_indexing(video)

        self.assertIsNotNone(request)
        self.assertEqual(service.keyframe_state, "loading")
        self.assertEqual(service.active_job_token, request.job_token)
        self.assertEqual(service.keyframe_timestamps, [])

    def test_completion_sets_ready_state_and_caches_sorted_unique_timestamps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService()
            request = service.request_indexing(video)

            applied = service.complete_indexing(video, request.job_token, [10.0, 0.0, 10.0, 5.0])

            self.assertTrue(applied)
            self.assertEqual(service.keyframe_state, "ready")
            self.assertEqual(service.keyframe_timestamps, [0.0, 5.0, 10.0])
            self.assertEqual(service.get_cached_keyframes(video), [0.0, 5.0, 10.0])

    def test_duplicate_request_during_loading_returns_no_new_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService()
            first_request = service.request_indexing(video)

            second_request = service.request_indexing(video)

        self.assertIsNone(second_request)
        self.assertEqual(service.active_job_token, first_request.job_token)

    def test_stale_result_is_ignored_after_another_video_becomes_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            first_video = folder / "first.mp4"
            second_video = folder / "second.mp4"
            first_video.touch()
            second_video.touch()
            service = KeyframeService()
            first_request = service.request_indexing(first_video)
            second_request = service.request_indexing(second_video)

            applied = service.complete_indexing(first_video, first_request.job_token, [0.0, 5.0])

            self.assertFalse(applied)
            self.assertEqual(service.keyframe_state, "loading")
            self.assertEqual(service.active_job_token, second_request.job_token)
            self.assertEqual(service.keyframe_timestamps, [])
            self.assertIsNone(service.get_cached_keyframes(first_video))

    def test_failure_sets_error_state_without_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()
            service = KeyframeService()
            request = service.request_indexing(video)

            applied = service.fail_indexing(video, request.job_token, "ffprobe failed")

        self.assertTrue(applied)
        self.assertEqual(service.keyframe_state, "error")
        self.assertEqual(service.keyframe_error, "ffprobe failed")
        self.assertEqual(service.keyframe_timestamps, [])

    def test_ready_cache_is_reused_until_media_file_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.write_bytes(b"a")
            service = KeyframeService()
            first_request = service.request_indexing(video)
            service.complete_indexing(video, first_request.job_token, [0.0, 5.0])

            cached_request = service.request_indexing(video)
            video.write_bytes(b"changed")
            changed_request = service.request_indexing(video)

        self.assertIsNone(cached_request)
        self.assertIsNotNone(changed_request)
        self.assertEqual(service.keyframe_state, "loading")

    def test_extract_keyframes_parses_sorted_unique_timestamps(self):
        def fake_runner(command, **_kwargs):
            payload = {
                "frames": [
                    {"best_effort_timestamp_time": "10.000"},
                    {"best_effort_timestamp_time": "0.000"},
                    {"best_effort_timestamp_time": "10.000"},
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with patch(
            "services.infrastructure.ffmpeg.probe.get_ffprobe_path",
            return_value=Path("ffprobe"),
        ):
            keyframes = extract_keyframes("movie.mp4", probe_runner=fake_runner)

        self.assertEqual(keyframes, [0.0, 10.0])

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
        info = CutPlanService().align_interval(
            [0, 32, 34, 40, 44, 72],
            requested_start=33,
            requested_end=42,
            duration_seconds=72,
        )

        self.assertEqual(info["safe_start"], 32)
        self.assertEqual(info["safe_end"], 44)
        self.assertEqual(info["requested_start"], 33)
        self.assertEqual(info["requested_end"], 42)
        self.assertEqual(info["previous_keyframe_start"], 32)
        self.assertEqual(info["next_keyframe_start"], 34)
        self.assertEqual(info["previous_keyframe_end"], 40)
        self.assertEqual(info["next_keyframe_end"], 44)
        self.assertEqual(info["extra_before"], 1)
        self.assertEqual(info["extra_after"], 2)


if __name__ == "__main__":
    unittest.main()
