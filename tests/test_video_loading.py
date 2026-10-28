"""Video loading off the GUI thread: real QThreadPool, real bundled ffprobe, synthetic media.

The controller must stay responsive while ffprobe checks a file, ignore late results of superseded
selections, stop ffprobe on cancellation and shutdown, and record only validated files. Every wait
has a deadline and every subprocess a timeout.
"""

import functools
import hashlib
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QThreadPool, QTimer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controllers.app.app_controller import AppController
from database.base import Base
from models import Video
from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner, FFmpegTimeoutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path
from services.media import media_validation
from services.media.import_service import VideoImportService
from services.media.media_validation import validate_media_file
from tests.test_app_controller import (
    FakeAnalysisWorker,
    FakeExportWorker,
    FakeKeyframeWorker,
    FakeModelProvisioner,
    FakeModelProvisioningWorker,
    FakePrepareWorker,
    FakeSettingsService,
    FakeSubtitleWorker,
    FakeThreadPool,
)

SUBPROCESS_TIMEOUT_SECONDS = 90
WAIT_SECONDS = 30
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _RecordingRun:
    """Like ``cancellable_run``; can turn a file probe into an endless ffprobe, and keeps every runner."""

    def __init__(self, cancel_token, endless: bool):
        self.cancel_token = cancel_token
        self.endless = endless
        self.runners = []

    def __call__(self, command, timeout=None, **_kwargs):
        command = [str(part) for part in command]
        if self.endless:
            # Same ffprobe, but on an infinite generated input: it never finishes on its own.
            command = [command[0], "-v", "error", "-show_packets", "-f", "lavfi", "testsrc2=size=64x64:rate=25"]
        runner = BoundedProcessRunner(cancel_token=self.cancel_token, stall_timeout_seconds=timeout,
                                      max_runtime_seconds=timeout)
        self.runners.append(runner)
        try:
            return runner(command, text=True, encoding="utf-8", errors="replace")
        except FFmpegTimeoutError as exc:
            raise subprocess.TimeoutExpired(command, timeout) from exc


class VideoLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls.root = Path(tempfile.mkdtemp(prefix="video-loading-"))
        video = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=6"]
        audio = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
        h264 = ["-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p"]
        cls.mp4 = cls._make("valid.mp4", [*video, *audio, *h264, "-c:a", "aac", "-shortest"])
        cls.mkv = cls._make("valid.mkv", [*video, *audio, *h264, "-c:a", "aac", "-shortest"])
        cls.other_mp4 = cls._make("other.mp4", [*video, *h264])
        cls.audio_only = cls._make("audio_only.mp4", [*audio, "-c:a", "aac"])
        data = cls.mp4.read_bytes()
        cls.corrupted = cls.root / "corrupted.mp4"
        cls.corrupted.write_bytes(data[: len(data) // 2])
        cls.slow = cls.root / "slow.mp4"
        shutil.copyfile(cls.other_mp4, cls.slow)
        cls.hashes = {path: _sha256(path) for path in (cls.mp4, cls.mkv, cls.other_mp4, cls.audio_only,
                                                        cls.corrupted, cls.slow)}

    @classmethod
    def tearDownClass(cls):
        cls._timeout_patch.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def _make(cls, name, args):
        path = cls.root / name
        completed = _original_run([str(cls.ffmpeg), "-y", "-v", "error", *args, str(path)], capture_output=True,
                                  text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        return path

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                                    poolclass=StaticPool, future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

        @contextmanager
        def session_factory():
            db = self.Session()
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        self.validation_threads = []
        self.recorders = []
        self.blocked = {}
        self.import_service = VideoImportService(db_session_factory=session_factory, media_validator=self.validator)
        self.load_pool = QThreadPool()
        self.settings_service = FakeSettingsService()
        self.controller = AppController(
            video_import_service=self.import_service,
            thread_pool=FakeThreadPool(),
            worker_factory=FakeExportWorker,
            prepare_worker_factory=FakePrepareWorker,
            settings_service=self.settings_service,
            keyframe_worker_factory=FakeKeyframeWorker,
            subtitle_worker_factory=FakeSubtitleWorker,
            analysis_worker_factory=FakeAnalysisWorker,
            model_provisioner=FakeModelProvisioner(),
            model_provisioning_worker_factory=FakeModelProvisioningWorker,
            video_load_thread_pool=self.load_pool,
        )

    def tearDown(self):
        for event in self.blocked.values():
            event.set()
        self.controller.shutdown()
        self.assertTrue(self.load_pool.waitForDone(WAIT_SECONDS * 1000))
        self.app.processEvents()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        for path, digest in self.hashes.items():
            self.assertEqual(_sha256(path), digest, f"source changed: {path}")

    # The validator the import service calls in the worker thread: real D9 checks with real ffprobe.
    def validator(self, path, cancel_token=None):
        self.validation_threads.append(threading.get_ident())
        name = Path(path).name
        if name in self.blocked:
            # A check that is already past its cancellation point: it still returns a valid result, late.
            self.blocked[name].wait(WAIT_SECONDS)
            return validate_media_file(path)
        recorder = _RecordingRun(cancel_token, endless=(name == "slow.mp4"))
        self.recorders.append(recorder)
        return validate_media_file(path, run=recorder)

    def wait_until(self, condition, seconds=WAIT_SECONDS):
        deadline = time.monotonic() + seconds
        while not condition():
            if time.monotonic() > deadline:
                self.fail(f"condition not reached within {seconds} s")
            self.app.processEvents()
            time.sleep(0.005)

    def wait_loaded(self, path):
        self.wait_until(lambda: not self.controller.videoLoading)
        self.assertEqual(Path(self.controller.selectedVideoPath), path.resolve(), self.controller.videoLoadError)

    def video_rows(self):
        with self.Session() as db:
            return [row.video_path for row in db.query(Video).all()]

    def test_valid_mp4_and_mkv_load_in_the_background(self):
        for path in (self.mp4, self.mkv):
            with self.subTest(path=path.name):
                started = time.perf_counter()
                self.controller.loadVideoFile(str(path))
                self.assertLess(time.perf_counter() - started, 0.3, "loadVideoFile must not wait for ffprobe")
                self.assertTrue(self.controller.videoLoading)
                self.assertEqual(self.controller.videoLoadingName, path.name)
                self.assertIn("Checking", self.controller.projectStatus)
                self.wait_loaded(path)
                self.assertEqual(self.controller.videoLoadError, "")
        self.assertNotIn(threading.get_ident(), self.validation_threads)
        self.assertEqual(self.video_rows(), [str(self.mp4.resolve()), str(self.mkv.resolve())])
        self.assertEqual(self.settings_service.last_video, self.mkv.resolve())

    def test_corrupted_file_is_rejected_and_the_previous_video_kept(self):
        self.controller.loadVideoFile(str(self.mp4))
        self.wait_loaded(self.mp4)
        recents = list(self.controller.recentFiles)

        self.controller.loadVideoFile(str(self.corrupted))
        self.wait_until(lambda: not self.controller.videoLoading)
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mp4.resolve())
        self.assertIn("\"corrupted.mp4\" is damaged or incomplete", self.controller.videoLoadError)
        self.assertEqual(self.video_rows(), [str(self.mp4.resolve())])
        self.assertEqual(self.controller.recentFiles, recents)

    def test_gui_event_loop_stays_responsive_during_validation(self):
        gaps = self.measure_event_loop_gaps(lambda: self.controller.loadVideoFile(str(self.mp4)),
                                            lambda: not self.controller.videoLoading)
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mp4.resolve())
        self.assertLess(max(gaps), 250, f"longest GUI-thread stall {max(gaps)} ms")

        # Baseline: the same validation run on the GUI thread blocks the event loop for its whole duration.
        blocking = self.measure_event_loop_gaps(lambda: validate_media_file(self.mkv), lambda: True, settle_ms=300)
        self.assertGreater(max(blocking), 500)
        print(f"GUI-thread stall: background {max(gaps)} ms, on the GUI thread {max(blocking)} ms")

    def measure_event_loop_gaps(self, start, done, settle_ms=0):
        timer, ticks, clock = QTimer(), [], QElapsedTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(clock.elapsed()))
        clock.start()
        timer.start()
        while clock.elapsed() < 100:
            self.app.processEvents()
            time.sleep(0.002)
        start()
        settle_until = clock.elapsed() + settle_ms
        deadline = time.monotonic() + WAIT_SECONDS
        while (not done() or clock.elapsed() < settle_until) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        timer.stop()
        self.assertGreater(len(ticks), 5)
        return [b - a for a, b in zip(ticks, ticks[1:])]

    def test_slow_probe_is_stopped_by_its_timeout(self):
        with patch.object(media_validation, "HEADER_PROBE_TIMEOUT_SECONDS", 1.0):
            self.controller.loadVideoFile(str(self.slow))
            self.wait_until(lambda: not self.controller.videoLoading)
        self.assertIn("took too long", self.controller.videoLoadError)
        self.assertEqual(self.controller.selectedVideoPath, "")
        self.assertEqual(self.video_rows(), [])
        self.assertTrue(self.recorders[0].runners[0].terminated_pids, "the endless ffprobe must be terminated")

    def test_selecting_b_while_a_is_probing_cancels_a(self):
        self.controller.loadVideoFile(str(self.slow))
        self.wait_until(lambda: self.recorders and self.recorders[0].runners)
        self.controller.loadVideoFile(str(self.mkv))
        self.wait_loaded(self.mkv)
        self.assertTrue(self.load_pool.waitForDone(WAIT_SECONDS * 1000))
        self.app.processEvents()
        self.assertTrue(self.recorders[0].runners[0].terminated_pids, "A's ffprobe must be terminated")
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mkv.resolve())
        self.assertEqual(self.video_rows(), [str(self.mkv.resolve())])

    def test_a_late_valid_result_for_a_never_overwrites_b(self):
        self.blocked["other.mp4"] = threading.Event()
        self.controller.loadVideoFile(str(self.other_mp4))
        self.wait_until(lambda: len(self.validation_threads) == 1)
        self.controller.loadVideoFile(str(self.mkv))
        self.wait_loaded(self.mkv)

        self.blocked["other.mp4"].set()  # A now completes, valid, after B
        self.assertTrue(self.load_pool.waitForDone(WAIT_SECONDS * 1000))
        self.app.processEvents()
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mkv.resolve())
        self.assertEqual(self.video_rows(), [str(self.mkv.resolve())])
        self.assertEqual(self.settings_service.last_video, self.mkv.resolve())

    def test_repeated_selections(self):
        self.blocked["other.mp4"] = threading.Event()
        for _ in range(3):
            self.controller.loadVideoFile(str(self.other_mp4))
        self.assertEqual(len(self.controller._video_load_workers), 1, "duplicate requests start no new check")
        self.blocked["other.mp4"].set()
        self.wait_loaded(self.other_mp4)

        for path in (self.mp4, self.mkv, self.mp4, self.mkv, self.mp4):
            self.controller.loadVideoFile(str(path))
        self.wait_loaded(self.mp4)
        self.assertTrue(self.load_pool.waitForDone(WAIT_SECONDS * 1000))
        self.app.processEvents()
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mp4.resolve())
        self.assertEqual(self.video_rows(), [str(self.other_mp4.resolve()), str(self.mp4.resolve())])

    def test_user_cancellation_stops_ffprobe_and_keeps_the_previous_video(self):
        self.controller.loadVideoFile(str(self.mp4))
        self.wait_loaded(self.mp4)
        self.controller.loadVideoFile(str(self.slow))
        self.wait_until(lambda: len(self.recorders) == 2 and self.recorders[1].runners)

        self.controller.cancelVideoLoad()
        self.assertFalse(self.controller.videoLoading)
        self.assertEqual(self.controller.projectStatus, "Video loading cancelled.")
        self.assertTrue(self.load_pool.waitForDone(10000), "the cancelled check must end promptly")
        self.app.processEvents()
        self.assertTrue(self.recorders[1].runners[0].terminated_pids)
        self.assertEqual(Path(self.controller.selectedVideoPath), self.mp4.resolve())
        self.assertEqual(self.video_rows(), [str(self.mp4.resolve())])
        self.assertEqual(self.controller.videoLoadError, "")

    def test_shutdown_during_validation_returns_promptly(self):
        self.controller.loadVideoFile(str(self.slow))
        self.wait_until(lambda: self.recorders and self.recorders[0].runners)
        started = time.perf_counter()
        self.controller.shutdown()
        self.assertLess(time.perf_counter() - started, 10)
        self.assertEqual(self.load_pool.activeThreadCount(), 0)
        self.assertTrue(self.recorders[0].runners[0].terminated_pids)
        self.app.processEvents()
        self.assertEqual(self.controller.selectedVideoPath, "")
        self.assertEqual(self.video_rows(), [])

    def test_ui_state_changes_happen_on_the_main_thread(self):
        main_thread = threading.get_ident()
        emitting_threads = []
        for signal in (self.controller.videoLoadingChanged, self.controller.selectedVideoPathChanged,
                       self.controller.videoUrlChanged, self.controller.projectStatusChanged,
                       self.controller.videoLoadErrorChanged, self.controller.recentFilesChanged):
            signal.connect(lambda *_args: emitting_threads.append(threading.get_ident()))

        self.controller.loadVideoFile(str(self.mp4))
        self.wait_loaded(self.mp4)
        self.controller.loadVideoFiles([str(self.corrupted), str(self.mkv)])
        self.wait_loaded(self.mkv)
        self.controller.loadVideoFile(str(self.audio_only))
        self.wait_until(lambda: not self.controller.videoLoading)

        self.assertGreater(len(emitting_threads), 10)
        self.assertEqual(set(emitting_threads), {main_thread})
        self.assertTrue(self.validation_threads)
        self.assertNotIn(main_thread, self.validation_threads)

    def test_registration_requires_a_fresh_successful_validation(self):
        copy = self.root / "registered_copy.mp4"
        shutil.copyfile(self.mp4, copy)
        try:
            with self.assertRaisesRegex(ValueError, "must be checked again"):
                self.import_service.register_video_file(copy)  # never validated
            with self.assertRaises(ValueError):
                self.import_service.validate_video_file(self.corrupted)
            with self.assertRaisesRegex(ValueError, "must be checked again"):
                self.import_service.register_video_file(self.corrupted)  # validation failed

            self.import_service.validate_video_file(copy)
            with copy.open("ab") as handle:
                handle.write(b"\0" * 16)  # replaced/changed after its check
            with self.assertRaisesRegex(ValueError, "must be checked again"):
                self.import_service.register_video_file(copy)

            self.import_service.validate_video_file(self.mp4)
            self.import_service.register_video_file(self.mp4)
            with self.assertRaisesRegex(ValueError, "must be checked again"):
                self.import_service.register_video_file(self.mp4)  # one check, one registration
            self.assertEqual(self.video_rows(), [str(self.mp4.resolve())])
        finally:
            copy.unlink(missing_ok=True)

    def test_multi_selection_with_valid_and_invalid_files(self):
        started = time.perf_counter()
        self.controller.loadVideoFiles([str(self.mp4), str(self.corrupted), str(self.audio_only), str(self.mkv)])
        self.assertLess(time.perf_counter() - started, 0.3)
        self.assertEqual(self.controller.videoLoadingName, "4 selected files")
        self.wait_loaded(self.mp4)

        self.assertEqual([Path(v["path"]) for v in self.controller.availableVideos],
                         [self.mp4.resolve(), self.mkv.resolve()])
        self.assertIn("skipped 2 file(s) that could not be opened", self.controller.projectStatus)
        self.assertEqual([Path(item["path"]) for item in self.controller.recentFiles][:2],
                         [self.mp4.resolve(), self.mkv.resolve()])
        self.assertNotIn(str(self.corrupted.resolve()), [item["path"] for item in self.controller.recentFiles])
        self.assertEqual(self.video_rows(), [str(self.mp4.resolve())])


if __name__ == "__main__":
    unittest.main()
