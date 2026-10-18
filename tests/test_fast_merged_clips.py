"""D7: Fast Cutting "merged clips" keeps the union of the selected clips once, in source order.

Real FFmpeg, frame-identifiable synthetic video: the output must contain exactly the source frames
of the union of the clips, each once and in order, through the same verified stream-copy path and
restrictions as interval removal. Every subprocess has a timeout.
"""

import functools
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from evaluation import export_frame_accuracy as efa
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import (
    CutExecutionService,
    FastCuttingAudioError,
    FastCuttingPrecisionError,
    FastCuttingVerificationError,
)
from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path

SUBPROCESS_TIMEOUT_SECONDS = 90
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FastMergedClipsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls._root = Path(tempfile.mkdtemp(prefix="fast-merged-"))
        fixtures = cls._root / "fixtures"
        cls.video_only = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_noaudio_mp4"], fixtures)
        cls.with_audio = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_aac_mp4"], fixtures)
        cls.mkv = efa.generate_fixture(
            cls.ffmpeg, efa.FixtureSpec("h264_noaudio_mkv", audio=False, container="mkv"), fixtures
        )
        cls.hashes = {path: _sha256(path) for path in (cls.video_only, cls.with_audio, cls.mkv)}

    @classmethod
    def tearDownClass(cls):
        cls._timeout_patch.stop()
        shutil.rmtree(cls._root, ignore_errors=True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self._root))
        self.cache_dir = self.work / "cache"
        self.output_dir = self.work / "out"

    def tearDown(self):
        for path, digest in self.hashes.items():
            self.assertEqual(_sha256(path), digest, f"source changed: {path}")
        leftovers = [p for p in self.cache_dir.rglob("*") if p.is_file()] if self.cache_dir.exists() else []
        self.assertEqual(leftovers, [], "temporary files left behind")

    def merge(self, clips, source=None):
        runner = BoundedProcessRunner(stall_timeout_seconds=30)
        request = VideoCutRequest(
            input_path=source or self.video_only,
            output_dir=self.output_dir,
            export_mode="export_clips_merged",
            segments=[{"index": i, "start_seconds": a, "end_seconds": b} for i, (a, b) in enumerate(clips, 1)],
        )
        service = CutExecutionService(cache_dir=self.cache_dir, command_runner=runner, probe_runner=runner)
        return service.export_segments(request)

    def assert_union_exactly_once(self, clips):
        result = self.merge(clips)
        frames = [index for _, index in efa.decode_frames(self.ffmpeg, self.ffprobe, result.merged_output_path)]
        wanted = [i for i in range(efa.SOURCE_FRAMES) if any(a - 1e-6 <= i / efa.FPS < b - 1e-6 for a, b in clips)]
        self.assertEqual(frames, wanted, "frames must be the union of the clips, each once, in source order")
        durations = efa.stream_durations(self.ffprobe, result.merged_output_path)
        self.assertAlmostEqual(durations["video"], len(wanted) / efa.FPS, delta=1.5 / efa.FPS)
        self.assertEqual(sorted(p.name for p in self.output_dir.iterdir()), [result.merged_output_path.name])
        return result

    def assert_refused(self, clips, error, fragment, source=None):
        with self.assertRaises(error) as caught:
            self.merge(clips, source=source)
        self.assertIn(fragment, str(caught.exception))
        outputs = list(self.output_dir.iterdir()) if self.output_dir.exists() else []
        self.assertEqual(outputs, [])

    def test_two_overlapping_clips(self):
        result = self.assert_union_exactly_once([(4.0, 10.0), (8.0, 14.0)])
        self.assertEqual(result.normalized_intervals, [(4.0, 14.0)])

    def test_three_overlapping_clips(self):
        self.assert_union_exactly_once([(4.0, 8.0), (6.0, 12.0), (10.0, 16.0)])

    def test_nested_clips(self):
        self.assert_union_exactly_once([(4.0, 16.0), (8.0, 10.0)])

    def test_adjacent_clips(self):
        self.assert_union_exactly_once([(4.0, 8.0), (8.0, 12.0)])

    def test_disjoint_clips_given_out_of_order_are_kept_in_source_order(self):
        self.assert_union_exactly_once([(20.0, 24.0), (2.0, 6.0)])

    def test_duplicate_clips(self):
        self.assert_union_exactly_once([(8.0, 12.0), (8.0, 12.0)])

    def test_clips_touching_the_source_start_and_end(self):
        self.assert_union_exactly_once([(0.0, 4.0), (26.0, 30.0)])

    def test_clip_extending_past_the_end_is_clamped_to_the_source(self):
        result = self.assert_union_exactly_once([(26.0, 40.0)])
        self.assertEqual(result.normalized_intervals, [(26.0, 30.0)])

    def test_invalid_and_out_of_range_clips_are_refused(self):
        with self.assertRaises(ValidationError):
            self.merge([(8.0, 8.0)])
        with self.assertRaises(ValidationError):
            self.merge([])
        self.assert_refused([(2.0, 4.0), (32.0, 34.0)], ValueError, "after the end of the video")

    def test_clip_boundaries_off_keyframes_are_refused(self):
        # FX06 of the functional validation (5.0 is not a keyframe of the 2 s GOP).
        self.assert_refused([(5.0, 10.0), (8.0, 14.0)], FastCuttingPrecisionError,
                            "cannot export the selected clips exactly")

    def test_source_with_audio_is_refused(self):
        self.assert_refused([(4.0, 10.0), (8.0, 14.0)], FastCuttingAudioError, "cannot merge clips with exact audio",
                            source=self.with_audio)

    def test_verification_failure_leaves_nothing(self):
        self.assert_refused([(8.0, 12.0)], FastCuttingVerificationError, "could not verify", source=self.mkv)


if __name__ == "__main__":
    unittest.main()
