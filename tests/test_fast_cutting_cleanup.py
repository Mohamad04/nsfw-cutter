"""D5: Fast Cutting removes its own temporary files, with real FFmpeg, on every outcome."""

import functools
import hashlib
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation import export_frame_accuracy as efa
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import CutExecutionService, FastCuttingVerificationError
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


class _CommandHook(BoundedProcessRunner):
    """Bounded runner that can fail, slow down or time out the concat command."""

    def __init__(self, on_concat=None, **kwargs):
        super().__init__(**kwargs)
        self.on_concat = on_concat

    def __call__(self, command, *args, **kwargs):
        command = [str(part) for part in command]
        self.max_runtime_seconds = None
        if "concat" in command and self.on_concat == "fail":
            return subprocess.CompletedProcess(command, 1, "", "simulated concat failure")
        if "concat" in command and self.on_concat in ("slow", "timeout"):
            command = [*command[:3], "-re", *command[3:]]
            if self.on_concat == "timeout":
                self.max_runtime_seconds = 0.5
        return super().__call__(command, *args, **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FastCuttingCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls._root = Path(tempfile.mkdtemp(prefix="fast-cleanup-"))
        fixtures = cls._root / "fixtures"
        cls.video_only = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_noaudio_mp4"], fixtures)
        cls.gop25 = efa.generate_fixture(
            cls.ffmpeg, efa.FixtureSpec("h264_noaudio_gop25_mp4", audio=False, gop_frames=25), fixtures
        )
        cls.mkv = efa.generate_fixture(
            cls.ffmpeg, efa.FixtureSpec("h264_noaudio_mkv", audio=False, container="mkv"), fixtures
        )
        cls.hashes = {path: _sha256(path) for path in (cls.video_only, cls.gop25, cls.mkv)}

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

    def export(self, source, removed, mode="remove_intervals", runner=None, progress=None, cache_dir=None, output_dir=None):
        runner = runner or BoundedProcessRunner(stall_timeout_seconds=30)
        request = VideoCutRequest(
            input_path=source,
            output_dir=output_dir or self.output_dir,
            export_mode=mode,
            segments=[{"index": i, "start_seconds": a, "end_seconds": b} for i, (a, b) in enumerate(removed, 1)],
        )
        service = CutExecutionService(cache_dir=cache_dir or self.cache_dir, command_runner=runner, probe_runner=runner)
        return service.export_segments(request, progress_callback=progress)

    def cache_files(self, cache_dir=None):
        folder = cache_dir or self.cache_dir
        return sorted(str(path) for path in folder.rglob("*") if path.is_file()) if folder.exists() else []

    def output_files(self):
        return sorted(path.name for path in self.output_dir.iterdir()) if self.output_dir.exists() else []

    def test_successful_removal_leaves_only_the_frame_exact_output(self):
        removed = [(1.0 + 2 * k, 2.0 + 2 * k) for k in range(10)]

        result = self.export(self.gop25, removed)

        self.assertEqual(self.cache_files(), [])
        self.assertEqual(self.output_files(), [result.merged_output_path.name])
        self.assertIsNone(result.duration_warning)
        report = efa.removal_report(efa.decode_frames(self.ffmpeg, self.ffprobe, result.merged_output_path), removed)
        self.assertTrue(report["frame_exact"], report)

    def test_successful_clip_exports_leave_no_temporary_files(self):
        merged = self.export(self.video_only, [(2.0, 4.0), (20.0, 24.0)], mode="export_clips_merged")
        separate = self.export(self.video_only, [(2.0, 4.0), (20.0, 24.0)], mode="export_clips_separate")

        self.assertEqual(self.cache_files(), [])
        self.assertTrue(merged.merged_output_path.is_file())
        self.assertTrue(all(path.is_file() for path in separate.output_paths))

    def test_verification_failure_leaves_nothing(self):
        with self.assertRaises(FastCuttingVerificationError):
            self.export(self.mkv, [(8.0, 12.0)])

        self.assertEqual(self.cache_files(), [])
        self.assertEqual(self.output_files(), [])

    def test_ffmpeg_failure_leaves_nothing(self):
        with self.assertRaises(VideoCutError):
            self.export(self.video_only, [(8.0, 12.0)], runner=_CommandHook(on_concat="fail"))

        self.assertEqual(self.cache_files(), [])
        self.assertEqual(self.output_files(), [])

    def test_timeout_while_joining_leaves_nothing(self):
        with self.assertRaises(FFmpegTimeoutError):
            self.export(self.video_only, [(8.0, 12.0)], runner=_CommandHook(on_concat="timeout"))

        self.assertEqual(self.cache_files(), [])
        self.assertEqual(self.output_files(), [])

    def test_cancellation_leaves_nothing(self):
        token = ExportCancellationToken()

        def progress(_percent, message):
            if message == "Prepared stream-copy segment 1":
                token.cancel()

        with self.assertRaises(ExportCancelledError):
            self.export(self.video_only, [(8.0, 12.0)], runner=BoundedProcessRunner(cancel_token=token), progress=progress)

        self.assertEqual(self.cache_files(), [])
        self.assertEqual(self.output_files(), [])

    def test_concurrent_exports_only_remove_their_own_files(self):
        shared_cache = self.work / "shared-cache"
        slow_outcome = {}

        def slow_export():
            slow_outcome["result"] = self.export(
                self.video_only, [(8.0, 12.0)], runner=_CommandHook(on_concat="slow", stall_timeout_seconds=60),
                cache_dir=shared_cache, output_dir=self.work / "slow-out",
            )

        thread = threading.Thread(target=slow_export)
        thread.start()
        while thread.is_alive() and not list(shared_cache.glob("*/concat_list.txt")):
            thread.join(0.05)
        slow_files = self.cache_files(shared_cache)

        fast = self.export(self.video_only, [(20.0, 24.0)], cache_dir=shared_cache, output_dir=self.work / "fast-out")

        self.assertTrue(thread.is_alive(), "the slow export should still be joining its segments")
        self.assertEqual(self.cache_files(shared_cache), slow_files)
        thread.join(60)
        self.assertTrue(fast.merged_output_path.is_file())
        self.assertTrue(slow_outcome["result"].merged_output_path.is_file())
        self.assertEqual(self.cache_files(shared_cache), [])

    def test_cleanup_failure_is_reported_and_the_verified_output_is_kept(self):
        with patch("services.editing.cut_execution_service.shutil.rmtree"):
            result = self.export(self.video_only, [(8.0, 12.0)])

        self.assertIn("Temporary files could not be removed", result.duration_warning)
        self.assertTrue(result.merged_output_path.is_file())
        self.assertTrue(self.cache_files())


if __name__ == "__main__":
    unittest.main()
