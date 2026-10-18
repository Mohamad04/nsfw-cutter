"""Fast Cutting "separate clips": one verified, frame-exact file per requested clip.

Real FFmpeg, frame-identifiable synthetic video. Clips are independent (overlapping clips may share
source frames in different files). The batch is all-or-nothing: if any clip fails, is cancelled or
times out, no file of the batch is kept. Every subprocess has a timeout.
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
)
from services.infrastructure.ffmpeg.bounded_runner import (
    BoundedProcessRunner,
    ExportCancellationToken,
    ExportCancelledError,
    FFmpegTimeoutError,
)
from services.infrastructure.ffmpeg.cutting import VideoCutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path

SUBPROCESS_TIMEOUT_SECONDS = 90
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _SecondClipHook(BoundedProcessRunner):
    """Fails, or slows down and times out, the command that writes the second clip's file."""

    def __init__(self, behaviour, **kwargs):
        super().__init__(**kwargs)
        self.behaviour = behaviour

    def __call__(self, command, *args, **kwargs):
        command = [str(part) for part in command]
        self.max_runtime_seconds = None
        if "concat" in command and "_clip_002_" in command[-1]:
            if self.behaviour == "fail":
                return subprocess.CompletedProcess(command, 1, "", "simulated failure on clip 2")
            command = [*command[:3], "-re", *command[3:]]
            self.max_runtime_seconds = 0.5
        return super().__call__(command, *args, **kwargs)


class FastSeparateClipsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls._root = Path(tempfile.mkdtemp(prefix="fast-separate-"))
        fixtures = cls._root / "fixtures"
        cls.video_only = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_noaudio_mp4"], fixtures)
        cls.with_audio = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_aac_mp4"], fixtures)
        cls.hashes = {path: _sha256(path) for path in (cls.video_only, cls.with_audio)}

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

    def export(self, clips, source=None, runner=None, progress=None):
        runner = runner or BoundedProcessRunner(stall_timeout_seconds=30)
        request = VideoCutRequest(
            input_path=source or self.video_only,
            output_dir=self.output_dir,
            export_mode="export_clips_separate",
            segments=[{"index": i, "start_seconds": a, "end_seconds": b} for i, (a, b) in enumerate(clips, 1)],
        )
        service = CutExecutionService(cache_dir=self.cache_dir, command_runner=runner, probe_runner=runner)
        return service.export_segments(request, progress_callback=progress)

    def output_files(self):
        return sorted(p.name for p in self.output_dir.iterdir()) if self.output_dir.exists() else []

    def assert_each_clip_exact(self, clips):
        result = self.export(clips)
        self.assertEqual(len(result.output_paths), len(clips))
        self.assertEqual(self.output_files(), sorted(Path(p).name for p in result.output_paths))
        for (start, end), path in zip(clips, result.output_paths, strict=True):
            end = min(end, efa.DURATION_SECONDS)
            frames = [index for _, index in efa.decode_frames(self.ffmpeg, self.ffprobe, Path(path))]
            wanted = [i for i in range(efa.SOURCE_FRAMES) if start - 1e-6 <= i / efa.FPS < end - 1e-6]
            self.assertEqual(frames, wanted, f"{Path(path).name} must hold exactly the frames of {start}-{end}")
            durations = efa.stream_durations(self.ffprobe, Path(path))
            self.assertAlmostEqual(durations["video"], len(wanted) / efa.FPS, delta=1.5 / efa.FPS)
        return result

    def assert_batch_refused(self, clips, error, fragment=None, **kwargs):
        with self.assertRaises(error) as caught:
            self.export(clips, **kwargs)
        if fragment:
            self.assertIn(fragment, str(caught.exception))
        self.assertEqual(self.output_files(), [])

    def test_single_clip(self):
        self.assert_each_clip_exact([(8.0, 12.0)])

    def test_multiple_disjoint_clips(self):
        self.assert_each_clip_exact([(2.0, 6.0), (20.0, 24.0)])

    def test_overlapping_clips_stay_independent(self):
        # Each file keeps its whole clip, so the shared seconds 8-10 appear in both files.
        self.assert_each_clip_exact([(4.0, 10.0), (8.0, 14.0)])

    def test_nested_clips(self):
        self.assert_each_clip_exact([(4.0, 16.0), (8.0, 10.0)])

    def test_duplicate_clips_give_two_files_without_overwriting(self):
        result = self.assert_each_clip_exact([(8.0, 12.0), (8.0, 12.0)])
        self.assertEqual(len({Path(p).name for p in result.output_paths}), 2)

    def test_adjacent_clips(self):
        self.assert_each_clip_exact([(4.0, 8.0), (8.0, 12.0)])

    def test_clips_out_of_chronological_order_keep_request_order(self):
        result = self.assert_each_clip_exact([(20.0, 24.0), (2.0, 6.0)])
        self.assertIn("_clip_001_00-00-20", Path(result.output_paths[0]).name)

    def test_clips_at_source_boundaries(self):
        self.assert_each_clip_exact([(0.0, 4.0), (26.0, 40.0)])

    def test_non_keyframe_boundaries_are_refused(self):
        self.assert_batch_refused([(8.0, 12.0), (13.3, 16.0)], FastCuttingPrecisionError,
                                  "cannot export the selected clips exactly")

    def test_source_with_audio_is_refused(self):
        self.assert_batch_refused([(8.0, 12.0)], FastCuttingAudioError, "cannot export clips with exact audio",
                                  source=self.with_audio)

    def test_invalid_and_empty_clips_are_refused(self):
        with self.assertRaises(ValidationError):
            self.export([(8.0, 6.0)])
        with self.assertRaises(ValidationError):
            self.export([])
        self.assert_batch_refused([(2.0, 4.0), (31.0, 33.0)], ValueError, "after the end of the video")

    def test_ffmpeg_failure_on_a_later_clip_keeps_no_file_of_the_batch(self):
        self.assert_batch_refused([(2.0, 4.0), (8.0, 12.0)], VideoCutError, runner=_SecondClipHook("fail"))

    def test_timeout_on_a_later_clip_keeps_no_file_of_the_batch(self):
        self.assert_batch_refused([(2.0, 4.0), (8.0, 12.0)], FFmpegTimeoutError, runner=_SecondClipHook("timeout"))

    def test_cancellation_after_the_first_clip_keeps_no_file_of_the_batch(self):
        token = ExportCancellationToken()

        def progress(_percent, message):
            if message == "Exported selected clip 1":
                token.cancel()

        self.assert_batch_refused([(2.0, 4.0), (8.0, 12.0)], ExportCancelledError,
                                  runner=BoundedProcessRunner(cancel_token=token), progress=progress)

    def test_existing_outputs_are_never_deleted_or_overwritten(self):
        self.output_dir.mkdir(parents=True)
        existing = self.output_dir / "h264_noaudio_mp4_clip_001_00-00-02_to_00-00-04.mp4"
        existing.write_bytes(b"previous export")

        with self.assertRaises(VideoCutError):
            self.export([(2.0, 4.0), (8.0, 12.0)], runner=_SecondClipHook("fail"))
        self.assertEqual(existing.read_bytes(), b"previous export")
        self.assertEqual(self.output_files(), [existing.name])

        result = self.export([(2.0, 4.0)])
        self.assertEqual(existing.read_bytes(), b"previous export")
        self.assertEqual(Path(result.output_paths[0]).name, "h264_noaudio_mp4_clip_001_00-00-02_to_00-00-04_1.mp4")


if __name__ == "__main__":
    unittest.main()
