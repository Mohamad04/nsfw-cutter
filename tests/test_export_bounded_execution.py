"""D1/D6: bounded and cancellable export execution, with real processes and real FFmpeg.

Covers the stall watchdog, absolute limits, user cancellation of a running FFmpeg, refusal of
commands after cancellation, cleanup of partial outputs and temporary files, invalid output
paths, and the full controller -> worker -> pipeline -> FFmpeg cancellation path.
"""

import functools
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controllers.video_cut_controller import VideoCutController
from database.base import Base
from evaluation import export_frame_accuracy as efa
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import CutExecutionService
from services.export.smart_cutting_export_service import SmartCuttingExportService
from services.infrastructure.ffmpeg.bounded_runner import (
    STALL_TIMEOUT_ENV,
    BoundedProcessRunner,
    ExportCancellationToken,
    ExportCancelledError,
    FFmpegTimeoutError,
)
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path

SUBPROCESS_TIMEOUT_SECONDS = 90
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        listing = _original_run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
        return str(pid) in listing.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _TimeoutOnCommand(BoundedProcessRunner):
    """Forces a timeout while a matching FFmpeg command is really running and writing its output.

    The matching command reads its input at native speed (``-re``), so it lasts several seconds and
    the 0.5 s absolute limit stops it mid-write.
    """

    def __init__(self, predicate, **kwargs):
        super().__init__(**kwargs)
        self.predicate = predicate

    def __call__(self, command, *args, **kwargs):
        command = [str(part) for part in command]
        if self.predicate(command):
            self.max_runtime_seconds = 0.5
            command = [*command[:3], "-re", *command[3:]]
        else:
            self.max_runtime_seconds = None
        return super().__call__(command, *args, **kwargs)


class _FFmpegCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = get_ffmpeg_path()
            cls.ffprobe = get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._patches = [
            patch("subprocess.run", _run_with_timeout),
            patch.dict(os.environ, {STALL_TIMEOUT_ENV: "20"}),
        ]
        for active in cls._patches:
            active.start()
        cls._root = Path(tempfile.mkdtemp(prefix="export-bounded-"))
        fixtures = cls._root / "fixtures"
        cls.with_audio = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_aac_mp4"], fixtures)
        cls.video_only = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_noaudio_mp4"], fixtures)
        cls.source_hashes = {path: _sha256(path) for path in (cls.with_audio, cls.video_only)}

    @classmethod
    def tearDownClass(cls):
        for active in reversed(cls._patches):
            active.stop()
        import shutil

        shutil.rmtree(cls._root, ignore_errors=True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self._root))
        self.output_dir = self.work / "out"
        self.cache_dir = self.work / "cache"

    def tearDown(self):
        for path, digest in self.source_hashes.items():
            self.assertEqual(_sha256(path), digest, f"source media changed: {path}")

    def assert_no_files(self, *folders: Path):
        for folder in folders:
            leftovers = [path for path in folder.rglob("*") if path.is_file()] if folder.exists() else []
            self.assertEqual(leftovers, [], f"unexpected files left in {folder}")

    def smart(self, runner, removed=((7.3, 12.7),), progress_callback=None, output_dir=None):
        segments = [{"requested_start_seconds": start, "requested_end_seconds": end} for start, end in removed]
        return SmartCuttingExportService(cache_dir=self.cache_dir, process_runner=runner).export(
            {"input_path": str(self.with_audio), "output_dir": str(output_dir or self.output_dir), "segments": segments},
            progress_callback=progress_callback,
        )["result"]

    def fast(self, runner, removed=((8.0, 12.0),), progress_callback=None, output_dir=None):
        request = VideoCutRequest(
            input_path=self.video_only,
            output_dir=output_dir or self.output_dir,
            export_mode="remove_intervals",
            segments=[{"index": i, "start_seconds": a, "end_seconds": b} for i, (a, b) in enumerate(removed, 1)],
        )
        service = CutExecutionService(cache_dir=self.cache_dir, command_runner=runner, probe_runner=runner)
        return service.export_segments(request, progress_callback=progress_callback)


class BoundedProcessRunnerTests(_FFmpegCase):
    def test_process_without_progress_is_stopped_by_the_stall_watchdog(self):
        runner = BoundedProcessRunner(stall_timeout_seconds=1.0)
        started = time.monotonic()

        with self.assertRaises(FFmpegTimeoutError) as caught:
            runner([sys.executable, "-c", "import time; time.sleep(60)"])

        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("no progress for 1 s", str(caught.exception))
        self.assertEqual(runner.terminated_pids, [runner.last_pid])
        self.assertFalse(_pid_alive(runner.last_pid))

    def test_stalled_ffmpeg_is_stopped_by_the_stall_watchdog(self):
        # Simulated FFmpeg stall: FFmpeg waits on a local TCP socket that never receives data.
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        runner = BoundedProcessRunner(stall_timeout_seconds=2.0)
        started = time.monotonic()

        with self.assertRaises(FFmpegTimeoutError) as caught:
            runner([str(self.ffmpeg), "-hide_banner", "-nostdin", "-i", f"tcp://127.0.0.1:{port}?listen=1",
                    "-f", "null", "-"])

        self.assertLess(time.monotonic() - started, 15)
        self.assertIn("no progress for 2 s", str(caught.exception))
        self.assertFalse(_pid_alive(runner.last_pid))

    def test_progressing_ffmpeg_is_not_stopped_by_a_short_stall_timeout(self):
        runner = BoundedProcessRunner(stall_timeout_seconds=1.0)

        completed = runner(
            [str(self.ffmpeg), "-hide_banner", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc2=d=3", "-f", "null", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(runner.terminated_pids, [])

    def test_absolute_limit_stops_a_progressing_process(self):
        runner = BoundedProcessRunner(max_runtime_seconds=1.0)

        with self.assertRaises(FFmpegTimeoutError) as caught:
            runner([str(self.ffmpeg), "-hide_banner", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc2=d=600", "-f", "null", "-"])

        self.assertIn("1 s limit", caught.exception.reason)
        self.assertFalse(_pid_alive(runner.last_pid))

    def test_cancellation_terminates_the_running_ffmpeg_and_refuses_later_commands(self):
        token = ExportCancellationToken()
        runner = BoundedProcessRunner(cancel_token=token)
        timer = threading.Timer(1.0, token.cancel)
        timer.start()
        started = time.monotonic()

        with self.assertRaises(ExportCancelledError):
            runner([str(self.ffmpeg), "-hide_banner", "-nostdin", "-re", "-f", "lavfi", "-i", "testsrc2=d=600", "-f", "null", "-"])

        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(runner.terminated_pids, [runner.last_pid])
        self.assertFalse(_pid_alive(runner.last_pid))
        token.cancel()  # repeated cancellation is harmless
        with self.assertRaises(ExportCancelledError):
            runner([str(self.ffmpeg), "-version"])
        self.assertEqual(len(runner.terminated_pids), 1)

    def test_known_aac_encoder_hang_is_bounded(self):
        runner = BoundedProcessRunner(stall_timeout_seconds=5.0)
        output = self.work / "d1.m4a"
        command = [str(self.ffmpeg), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", efa.D1_REPRO_AUDIO,
                   "-c:a", "aac", "-b:a", "192k", str(output)]
        started = time.monotonic()
        try:
            completed = runner(command)
        except FFmpegTimeoutError as exc:
            self.assertIn("no progress", str(exc))
            self.assertFalse(_pid_alive(runner.last_pid))
        else:
            self.assertEqual(completed.returncode, 0)
        self.assertLess(time.monotonic() - started, 20)


class FFmpegResolutionTests(_FFmpegCase):
    def test_application_resolves_ffmpeg_and_ffprobe_from_the_same_bundled_build(self):
        from core.paths import PROJECT_ROOT
        from services.infrastructure.ffmpeg.runner import FFmpegService

        service = FFmpegService()
        self.assertEqual(service.ffmpeg_path, self.ffmpeg)
        self.assertEqual(service.ffprobe_path, self.ffprobe)
        self.assertEqual(self.ffmpeg.parent, self.ffprobe.parent)
        bundled = PROJECT_ROOT / "vendor" / "ffmpeg" / "bin"
        if (bundled / "ffmpeg.exe").is_file():
            self.assertEqual(self.ffmpeg.parent.resolve(), bundled.resolve())
        versions = [
            _original_run([str(path), "-version"], capture_output=True, text=True, timeout=30).stdout.split()[2]
            for path in (self.ffmpeg, self.ffprobe)
        ]
        self.assertEqual(versions[0], versions[1], "ffmpeg.exe and ffprobe.exe come from different builds")


class ServiceCancellationAndTimeoutTests(_FFmpegCase):
    def test_smart_cancellation_during_video_chunks_keeps_nothing(self):
        token = ExportCancellationToken()

        def progress(_percent, message):
            if message.startswith("Rendered smart video chunk 1/"):
                token.cancel()

        with self.assertRaises(ExportCancelledError):
            self.smart(BoundedProcessRunner(cancel_token=token), progress_callback=progress)

        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_smart_timeout_while_muxing_deletes_the_partial_output(self):
        runner = _TimeoutOnCommand(lambda command: command[-1].startswith(str(self.output_dir)))

        with self.assertRaises(FFmpegTimeoutError):
            self.smart(runner)

        self.assertTrue(runner.terminated_pids)
        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_smart_timeout_while_rebuilding_audio_is_a_distinct_error(self):
        runner = _TimeoutOnCommand(lambda command: command[-1].endswith("smart_audio.m4a"))

        with self.assertRaises(FFmpegTimeoutError) as caught:
            self.smart(runner)

        self.assertNotIsInstance(caught.exception, ExportCancelledError)
        self.assertIn("FFmpeg was stopped", str(caught.exception))
        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_fast_cancellation_between_segments_removes_its_temporary_files(self):
        token = ExportCancellationToken()

        def progress(_percent, message):
            if message == "Prepared stream-copy segment 1":
                token.cancel()

        with self.assertRaises(ExportCancelledError):
            self.fast(BoundedProcessRunner(cancel_token=token), progress_callback=progress)

        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_fast_timeout_while_joining_deletes_the_partial_output(self):
        runner = _TimeoutOnCommand(lambda command: "concat" in command)

        with self.assertRaises(FFmpegTimeoutError):
            self.fast(runner)

        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_invalid_output_path_fails_without_side_effects(self):
        blocker = self.work / "not-a-folder"
        blocker.write_bytes(b"keep me")

        with self.assertRaises(OSError):
            self.smart(BoundedProcessRunner(), output_dir=blocker)
        with self.assertRaises(OSError):
            self.fast(BoundedProcessRunner(), output_dir=blocker)

        self.assertEqual(blocker.read_bytes(), b"keep me")
        self.assert_no_files(self.cache_dir)

    def test_export_after_a_cancelled_export_succeeds(self):
        token = ExportCancellationToken()
        token.cancel()
        with self.assertRaises(ExportCancelledError):
            self.smart(BoundedProcessRunner(cancel_token=token))

        result = self.smart(BoundedProcessRunner())

        frames = efa.decode_frames(self.ffmpeg, self.ffprobe, Path(result["merged_output_path"]))
        report = efa.removal_report(frames, [(7.3, 12.7)])
        self.assertTrue(report["frame_exact"], report)
        self.assert_no_files(self.cache_dir)


class _MemorySettingsService:
    def __init__(self):
        self.settings = SimpleNamespace(default_export_dir=None, export_dir=None)

    def load(self):
        return self.settings

    def update(self, **changes):
        for key, value in changes.items():
            setattr(self.settings, key, value)
        return self.settings


class ControllerCancellationTests(_FFmpegCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        self._engine = engine
        self._context = [
            patch("services.editing.cut_pipeline_service.SessionLocal", self.Session),
            patch("services.editing.cut_execution_service.get_cuts_cache_dir", return_value=self.cache_dir),
            patch("services.export.smart_cutting_export_service.get_cuts_cache_dir", return_value=self.cache_dir),
        ]
        for active in self._context:
            active.start()
        self.pool = QThreadPool()
        self.controller = VideoCutController(thread_pool=self.pool, settings_service=_MemorySettingsService())
        self.events = []
        self.controller.cutFinished.connect(lambda message: self.events.append(("finished", message)))
        self.controller.cutFailed.connect(lambda message: self.events.append(("failed", message)))
        self.controller.exportCancelled.connect(lambda message: self.events.append(("cancelled", message)))

    def tearDown(self):
        self.controller.cancelExport()
        self.wait_until(lambda: not self.controller.cutBusy)
        self.pool.waitForDone(30000)
        for active in reversed(self._context):
            active.stop()
        self._engine.dispose()
        super().tearDown()

    def wait_until(self, condition, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.02)
        return condition()

    def export(self, source: Path, timing_mode: str, start: float, end: float):
        self.controller.exportSegments(
            str(source),
            [{"start": "", "end": "", "requested_start_seconds": start, "requested_end_seconds": end,
              "start_seconds": start, "end_seconds": end, "timing_mode": timing_mode}],
            str(self.output_dir),
            "remove_intervals",
        )

    def test_user_cancels_a_running_smart_export_then_exports_again(self):
        cancel_calls = []

        def cancel_when_chunks_render(value):
            if value >= 22 and not cancel_calls:
                cancel_calls.append(self.controller.cancelExport())
                cancel_calls.append(self.controller.cancelExport())  # repeated click while stopping

        self.controller.cutProgress.connect(cancel_when_chunks_render)
        self.export(self.with_audio, "safe", 7.3, 12.7)
        self.assertTrue(self.controller.cutBusy)
        self.export(self.with_audio, "safe", 1.0, 2.0)  # a second export while busy is refused
        self.assertIn("already running", self.controller.cutStatus)

        self.assertTrue(self.wait_until(lambda: not self.controller.cutBusy), "export did not stop")
        self.assertEqual(cancel_calls, [True, True])
        self.assertEqual([kind for kind, _ in self.events], ["cancelled"])
        self.assertTrue(self.controller.cutCancelled)
        self.assertEqual(self.controller.cutStatus, "Video export cancelled")
        self.assertEqual(self.controller.cutError, "")
        self.assertEqual(self.controller.cutOutputPaths, [])
        self.assertEqual(self.controller.cutProgressValue, 0)
        self.assertFalse(self.controller.cancelExport(), "cancelling while idle must do nothing")
        self.assert_no_files(self.output_dir, self.cache_dir)

        self.controller.cutProgress.disconnect(cancel_when_chunks_render)
        self.export(self.with_audio, "safe", 7.3, 12.7)
        self.assertFalse(self.controller.cutCancelled)
        self.assertTrue(self.wait_until(lambda: not self.controller.cutBusy))
        self.assertEqual(self.events[-1][0], "finished", self.events)
        output = Path(self.controller.cutOutputPaths[0])
        report = efa.removal_report(efa.decode_frames(self.ffmpeg, self.ffprobe, output), [(7.3, 12.7)])
        self.assertTrue(report["frame_exact"], report)
        self.assertEqual(sorted(path.name for path in self.output_dir.iterdir()), [output.name])

    def test_user_cancels_a_fast_export_and_the_job_is_recorded_as_cancelled(self):
        from models.cut_job import CutJob

        self.export(self.video_only, "requested", 8.0, 12.0)
        self.assertTrue(self.controller.cancelExport())

        self.assertTrue(self.wait_until(lambda: not self.controller.cutBusy))
        self.assertEqual([kind for kind, _ in self.events], ["cancelled"])
        self.assertTrue(self.controller.cutCancelled)
        self.assert_no_files(self.output_dir, self.cache_dir)
        with self.Session() as db:
            self.assertEqual([job.status for job in db.query(CutJob).all()], ["cancelled"])

        self.export(self.video_only, "requested", 8.0, 12.0)
        self.assertTrue(self.wait_until(lambda: not self.controller.cutBusy))
        self.assertEqual(self.events[-1][0], "finished", self.events)
        report = efa.removal_report(
            efa.decode_frames(self.ffmpeg, self.ffprobe, Path(self.controller.cutOutputPaths[0])), [(8.0, 12.0)]
        )
        self.assertTrue(report["frame_exact"], report)


if __name__ == "__main__":
    unittest.main()
