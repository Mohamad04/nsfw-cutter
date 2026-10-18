"""D8: user-facing error messages, technical logging and consistent categories.

Unit cases cover each known failure family (including the raw messages of the functional validation:
FX10/SM15 WinError 183, SM11 raw ffprobe output, FX16 misleading stream-copy message). Integration
cases run the real export workers and the real VideoCutController on synthetic media with the bundled
FFmpeg. Every subprocess has a timeout.
"""

import errno
import functools
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from controllers.video_cut_controller import VideoCutController
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import FAST_CUTTING_AUDIO_REFUSED, CutExecutionService, FastCuttingAudioError
from services.export.smart_cutting_export_service import SmartCuttingExportService
from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner, ExportCancelledError, FFmpegTimeoutError
from services.infrastructure.ffmpeg.cutting import VideoCutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path
from services.user_errors import describe_error, technical_details
from workers.smart_cutting_worker import SmartCuttingWorker
from workers.video_cut_worker import VideoCutWorker

SUBPROCESS_TIMEOUT_SECONDS = 90
_original_run = subprocess.run

SM11_STDERR = (
    "[mov,mp4,m4a,3gp,3g2,mj2 @ 000002382e831fc0] moov atom not found\n"
    "D:\\Projet STAGE NSFW\\nsfw-cutter-vlm\\artifacts\\fixtures\\F10_truncated.mp4: Invalid data found when "
    "processing input"
)


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _cut_error(stderr: str, code: int = 1) -> VideoCutError:
    return VideoCutError(["ffmpeg.exe", "-i", "D:\\videos\\in.mp4", "D:\\cache\\job\\out.mp4"], code, stderr)


class DescribeErrorTests(unittest.TestCase):
    def assert_category(self, exc, category, *fragments, absent=()):
        described = describe_error(exc)
        self.assertEqual(described.category, category, described.message)
        for fragment in fragments:
            self.assertIn(fragment, described.message)
        for fragment in ("Traceback", "WinError", "@ 0000", *absent):
            self.assertNotIn(fragment, described.message)
        return described.message

    def test_cancellation_is_never_reported_as_a_failure(self):
        self.assert_category(ExportCancelledError("Video export was cancelled."), "cancelled", "cancelled")
        try:
            try:
                raise ExportCancelledError("cancelled")
            except ExportCancelledError as inner:
                raise VideoCutError(["ffmpeg"], 1, "Exiting normally, received signal 2.") from inner
        except VideoCutError as wrapped:
            self.assert_category(wrapped, "cancelled", "cancelled")

    def test_timeout(self):
        error = FFmpegTimeoutError(["ffmpeg.exe", "out.mp4"], "no progress for 180 s (stuck at 3.00 s of output)", "")
        self.assert_category(error, "timeout", "stopped responding", "no progress for 180 s", "No output was kept")

    def test_missing_or_incompatible_ffmpeg(self):
        self.assert_category(FFmpegNotFoundError("ffmpeg executable was not found"), "ffmpeg_unavailable",
                             "FFmpeg is missing", "prepare_ffmpeg.ps1")
        self.assert_category(_cut_error("Unrecognized option 'fps_mode'.\nError splitting the argument list"),
                             "ffmpeg_incompatible", "FFmpeg 8.1.1")

    def test_corrupted_input_is_not_called_an_unsupported_codec(self):
        # FX16: was "Video export failed. This workflow uses FFmpeg stream copy and the source streams must support it."
        self.assert_category(_cut_error(SM11_STDERR), "corrupted_media", "damaged or incomplete",
                             absent=("stream copy", "codec"))
        # SM11: the raw ffprobe output (internal address, full path) was shown as is.
        self.assert_category(RuntimeError(SM11_STDERR), "corrupted_media", "damaged or incomplete",
                             absent=("moov", "D:\\"))
        self.assert_category(_cut_error("[matroska,webm @ 0x1] File ended prematurely"), "corrupted_media")

    def test_unsupported_codec_for_the_operation(self):
        self.assert_category(_cut_error("Could not find tag for codec pcm_s16le in stream #1, codec not currently "
                                        "supported in container"), "unsupported_media", "codec or format")
        self.assert_category(_cut_error("Unknown encoder 'libx265'"), "unsupported_media")

    def test_invalid_output_location_and_name_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing_file = Path(temp_dir) / "cues.srt"
            existing_file.write_text("1")
            # FX10 / SM15: FileExistsError [WinError 183] when the output folder is an existing file.
            winerror = FileExistsError(errno.EEXIST, "Cannot create a file when that file already exists",
                                       str(existing_file))
            self.assert_category(winerror, "invalid_output_location", "\"cues.srt\" is an existing file, not a folder",
                                 absent=(temp_dir,))
            collision = FileExistsError(errno.EEXIST, "File exists", str(Path(temp_dir) / "missing" / "out.mp4"))
            self.assert_category(collision, "output_exists", "\"out.mp4\" already exists", "nothing was overwritten")

    def test_missing_inaccessible_and_full_disk(self):
        self.assert_category(FileNotFoundError(errno.ENOENT, "No such file", "D:\\videos\\gone.mp4"), "missing_file",
                             "\"gone.mp4\" can no longer be found")
        self.assert_category(PermissionError(errno.EACCES, "Permission denied", "D:\\out\\clip.mp4"), "access_denied",
                             "\"clip.mp4\"", "not open in another program")
        self.assert_category(OSError(errno.ENOSPC, "No space left on device"), "disk_full", "not enough free disk space")
        disk_full = OSError(None, "There is not enough space on the disk")
        disk_full.winerror = 112
        self.assert_category(disk_full, "disk_full")
        self.assert_category(_cut_error("av_interleaved_write_frame(): No space left on device"), "disk_full")

    def test_unknown_ffmpeg_failure_keeps_the_exit_code_and_points_to_the_log(self):
        self.assert_category(_cut_error("Something new went wrong", code=-22), "ffmpeg_failed", "exit code -22",
                             "video-cut.log")

    def test_request_validation_messages(self):
        with self.assertRaises(ValidationError) as caught:
            VideoCutRequest(input_path=__file__, output_dir=".", export_mode="explode",
                            segments=[{"index": 1, "start_seconds": 0, "end_seconds": 1}])
        self.assert_category(caught.exception, "invalid_request", "Unsupported export mode \"explode\"")
        with self.assertRaises(ValidationError) as caught:
            VideoCutRequest(input_path=__file__, output_dir=".", segments=[])
        message = self.assert_category(caught.exception, "invalid_request", "At least one cut segment is required.")
        self.assertFalse(message.startswith("Value error"))
        with self.assertRaises(ValidationError) as caught:
            VideoCutRequest(input_path=__file__, output_dir=".",
                            segments=[{"index": 1, "start_seconds": 0, "end_seconds": 1}])
        self.assert_category(caught.exception, "invalid_request", "is not a supported video")

    def test_curated_refusals_pass_through_unchanged(self):
        self.assertEqual(describe_error(FastCuttingAudioError(FAST_CUTTING_AUDIO_REFUSED)).message,
                         FAST_CUTTING_AUDIO_REFUSED)
        try:
            try:
                Path("Z:/definitely/missing").stat()
            except OSError:
                raise ValueError("Removed intervals cover the full video.")
        except ValueError as curated:
            self.assertEqual(describe_error(curated).message, "Removed intervals cover the full video.")

    def test_unknown_failures_are_shown_not_hidden(self):
        self.assert_category(RuntimeError("Subtitle rebuild failed for track 2"), "unexpected",
                             "Subtitle rebuild failed for track 2")
        self.assert_category(KeyError("video_stream"), "unexpected", "unexpected internal error occurred (KeyError)",
                             "video-cut.log")

    def test_technical_details_keep_command_stderr_and_cause(self):
        try:
            try:
                raise OSError(errno.EIO, "I/O error")
            except OSError as inner:
                raise _cut_error(SM11_STDERR) from inner
        except VideoCutError as exc:
            details = technical_details(exc)
        self.assertIn("ffmpeg.exe -i D:\\videos\\in.mp4", details)
        self.assertIn("moov atom not found", details)
        self.assertIn("return code: 1", details)
        self.assertIn("OSError", details)


class _ImmediateThreadPool:
    def start(self, worker):
        worker.run()


class _Settings:
    def __init__(self):
        self.settings = SimpleNamespace(default_export_dir=None, export_dir=None)

    def load(self):
        return self.settings

    def update(self, **changes):
        for key, value in changes.items():
            setattr(self.settings, key, value)


class ExportErrorIntegrationTests(unittest.TestCase):
    """Real workers, real controller, bundled FFmpeg, synthetic media."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = get_ffmpeg_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls.root = Path(tempfile.mkdtemp(prefix="user-errors-"))
        valid = cls.root / "valid.mp4"
        completed = subprocess.run(
            [str(cls.ffmpeg), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=6",
             "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", str(valid)],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        cls.valid = valid
        data = valid.read_bytes()
        cls.truncated = cls.root / "truncated.mp4"
        cls.truncated.write_bytes(data[: len(data) // 2])

    @classmethod
    def tearDownClass(cls):
        cls._timeout_patch.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root))

    def fast_pipeline(self, request_data, progress_callback=None, cancel_token=None):
        runner = BoundedProcessRunner(cancel_token=cancel_token, stall_timeout_seconds=30)
        request = VideoCutRequest.model_validate(request_data)
        service = CutExecutionService(cache_dir=self.work / "cache", command_runner=runner, probe_runner=runner)
        return {"result": service.export_segments(request, progress_callback=progress_callback).model_dump(mode="json")}

    def smart_pipeline(self, request_data, progress_callback=None, cancel_token=None):
        runner = BoundedProcessRunner(cancel_token=cancel_token, stall_timeout_seconds=30)
        service = SmartCuttingExportService(process_runner=runner, cache_dir=self.work / "smart-cache")
        return service.export(request_data, progress_callback=progress_callback)

    def controller(self):
        return VideoCutController(
            thread_pool=_ImmediateThreadPool(),
            worker_factory=lambda job_key, request_data: VideoCutWorker(job_key, request_data, self.fast_pipeline),
            smart_worker_factory=lambda job_key, request_data: SmartCuttingWorker(job_key, request_data,
                                                                                 self.smart_pipeline),
            settings_service=_Settings(),
        )

    def export(self, source, output_dir, timing_mode=None):
        controller = self.controller()
        segment = {"start": "00:00:02", "end": "00:00:03"}
        if timing_mode:
            segment["timing_mode"] = timing_mode
        controller.exportSegments(str(source), [segment], str(output_dir), "remove_intervals")
        return controller

    def test_truncated_source_gives_a_clear_message_in_fast_and_smart(self):
        for timing_mode, logger_name in (("requested", "workers.video_cut_worker"),
                                         (None, "workers.smart_cutting_worker")):
            with self.subTest(timing_mode=timing_mode):
                with self.assertLogs(logger_name, level="ERROR") as logs:
                    controller = self.export(self.truncated, self.work / f"out-{timing_mode}", timing_mode)
                self.assertEqual(controller.cutStatus, "Video export failed")
                self.assertIn("damaged or incomplete", controller.cutError)
                self.assertNotIn("moov", controller.cutError)
                self.assertNotIn("stream copy", controller.cutError)
                self.assertIn("moov atom not found", "\n".join(logs.output))

    def test_output_folder_that_is_a_file_is_refused_before_ffmpeg(self):
        not_a_folder = self.work / "cues.srt"
        not_a_folder.write_text("1")
        for timing_mode in ("requested", None):
            with self.subTest(timing_mode=timing_mode):
                controller = self.export(self.valid, not_a_folder, timing_mode)
                self.assertEqual(controller.cutStatus, "Video export failed")
                self.assertIn("\"cues.srt\" is an existing file, not a folder", controller.cutError)
                self.assertNotIn("WinError", controller.cutError)
                self.assertFalse((self.work / "cache").exists())

    def test_missing_source_is_reported_by_name(self):
        for timing_mode in ("requested", None):
            with self.subTest(timing_mode=timing_mode):
                controller = self.export(self.work / "gone.mp4", self.work / "out", timing_mode)
                self.assertIn("\"gone.mp4\" can no longer be found", controller.cutError)

    def test_cancellation_is_reported_as_cancelled(self):
        # A cancellation wrapped by a later FFmpeg error must still reach the "cancelled" signal.
        worker = VideoCutWorker("job", {}, pipeline=lambda *args, **kwargs: self._raise_cancelled())
        cancelled, errors = [], []
        worker.signals.cancelled.connect(lambda key, message: cancelled.append(message))
        worker.signals.error.connect(lambda key, message: errors.append(message))
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(cancelled), 1)

    @staticmethod
    def _raise_cancelled():
        try:
            raise ExportCancelledError("Video export was cancelled. No output was kept.")
        except ExportCancelledError as inner:
            raise VideoCutError(["ffmpeg"], 255, "Exiting normally, received signal 2.") from inner


if __name__ == "__main__":
    unittest.main()
