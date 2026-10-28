"""D9: preliminary media validation before a video is reported as loaded.

Real bundled ffprobe on small synthetic media (valid, damaged, truncated, renamed, audio-only,
cover-art-only), plus the import service and the real AppController. Every subprocess has a timeout.
"""

import functools
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controllers.app.app_controller import AppController
from database.base import Base
from models import Video
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path
from services.media.import_service import VideoImportService
from services.media.media_validation import MediaValidationError, validate_media_file
from services.user_errors import describe_error
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
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _MediaFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls._timeout_patch = patch("subprocess.run", _run_with_timeout)
        cls._timeout_patch.start()
        cls.root = Path(tempfile.mkdtemp(prefix="media-validation-"))
        video = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=6"]
        audio = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
        h264 = ["-c:v", "libx264", "-g", "50", "-pix_fmt", "yuv420p"]
        cls.valid_mp4 = cls._make("valid.mp4", [*video, *audio, *h264, "-c:a", "aac", "-shortest"])
        cls.faststart_mp4 = cls._make("faststart.mp4", [*video, *audio, *h264, "-c:a", "aac", "-shortest",
                                                        "-movflags", "+faststart"])
        cls.video_only_mp4 = cls._make("video_only.mp4", [*video, *h264])
        cls.valid_mkv = cls._make("valid.mkv", [*video, *audio, *h264, "-c:a", "aac", "-shortest"])
        cls.vp9_mkv = cls._make("vp9.mkv", ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=3",
                                            "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"])
        cls.audio_only_mp4 = cls._make("audio_only.mp4", [*audio, "-c:a", "aac"])
        cover = cls._make("cover.png", ["-f", "lavfi", "-i", "color=red:size=64x64", "-frames:v", "1"])
        cls.cover_art_mp4 = cls._make("cover_art.mp4", [*audio, "-i", str(cover), "-map", "0:a", "-map", "1:v",
                                                        "-c:a", "aac", "-c:v", "png", "-disposition:v", "attached_pic"])
        cls.avi = cls._make("mpeg4.avi", [*video, "-c:v", "mpeg4"])
        cls.sources = [cls.valid_mp4, cls.faststart_mp4, cls.video_only_mp4, cls.valid_mkv, cls.vp9_mkv,
                       cls.audio_only_mp4, cls.cover_art_mp4, cls.avi]
        cls.hashes = {path: _sha256(path) for path in cls.sources}

    @classmethod
    def tearDownClass(cls):
        cls._timeout_patch.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def _make(cls, name, args):
        path = cls.root / name
        completed = subprocess.run([str(cls.ffmpeg), "-y", "-v", "error", *args, str(path)],
                                   capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        return path

    def derived(self, name, payload: bytes) -> Path:
        path = self.root / "derived" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(payload)
        return path

    def tearDown(self):
        for path, digest in self.hashes.items():
            self.assertEqual(_sha256(path), digest, f"source changed: {path}")


class MediaValidationServiceTests(_MediaFixtures):
    def assert_rejected(self, path, category, fragment, **kwargs):
        with self.assertRaises(MediaValidationError) as caught:
            validate_media_file(path, **kwargs)
        self.assertEqual(caught.exception.category, category, str(caught.exception))
        self.assertIn(fragment, str(caught.exception))
        self.assertNotIn("Traceback", str(caught.exception))
        self.assertEqual(describe_error(caught.exception).category, category)
        return caught.exception

    def test_valid_mp4_mkv_and_vp9_are_accepted(self):
        for path, container, codec in (
            (self.valid_mp4, "mov,mp4,m4a,3gp,3g2,mj2", "h264"),
            (self.faststart_mp4, "mov,mp4,m4a,3gp,3g2,mj2", "h264"),
            (self.video_only_mp4, "mov,mp4,m4a,3gp,3g2,mj2", "h264"),
            (self.valid_mkv, "matroska,webm", "h264"),
            (self.vp9_mkv, "matroska,webm", "vp9"),
        ):
            with self.subTest(path=path.name):
                check = validate_media_file(path)
                self.assertEqual((check.container, check.video_codec, check.width > 0), (container, codec, True))
                self.assertGreater(check.duration_seconds, 2.9)
        self.assertFalse(validate_media_file(self.video_only_mp4).has_audio)

    def test_empty_text_and_random_files_are_rejected(self):
        self.assert_rejected(self.derived("zero.mp4", b""), "corrupted_media", "is empty (0 bytes)")
        self.assert_rejected(self.derived("notes.mp4", b"not a video\n" * 100), "corrupted_media", "damaged")
        self.assert_rejected(self.derived("random.mkv", bytes((i * 7919) % 251 for i in range(50000))),
                             "corrupted_media", "damaged")

    def test_truncated_mp4_without_metadata_is_rejected(self):
        data = self.valid_mp4.read_bytes()
        error = self.assert_rejected(self.derived("no_moov.mp4", data[: len(data) // 2]), "corrupted_media",
                                     "damaged or incomplete")
        self.assertIn("moov atom not found", error.detail)

    def test_truncated_files_with_intact_metadata_are_rejected(self):
        fast = self.faststart_mp4.read_bytes()
        mkv = self.valid_mkv.read_bytes()
        for name, payload in (
            ("faststart_half.mp4", fast[: len(fast) // 2]),
            ("faststart_90.mp4", fast[: int(len(fast) * 0.9)]),
            ("mkv_half.mkv", mkv[: len(mkv) // 2]),
        ):
            with self.subTest(name=name):
                self.assert_rejected(self.derived(name, payload), "corrupted_media", "the end of the video is missing")

    def test_header_damage_is_rejected(self):
        data = self.valid_mkv.read_bytes()
        self.assert_rejected(self.derived("bad_header.mkv", b"\0" * 64 + data[64:]), "corrupted_media", "damaged")

    def test_wrong_extensions_are_rejected_with_the_real_container(self):
        self.assert_rejected(self.derived("really_mkv.mp4", self.valid_mkv.read_bytes()), "wrong_extension",
                             "actually an MKV video")
        self.assert_rejected(self.derived("really_mp4.mkv", self.valid_mp4.read_bytes()), "wrong_extension",
                             "Rename it with the .mp4 extension")
        self.assert_rejected(self.derived("really_avi.mp4", self.avi.read_bytes()), "unsupported_format", "\"avi\"")
        self.assert_rejected(self.avi, "unsupported_format", "Open an MP4 or MKV file")

    def test_files_without_usable_video_are_rejected(self):
        self.assert_rejected(self.audio_only_mp4, "no_video", "contains only audio")
        self.assert_rejected(self.cover_art_mp4, "no_video", "only a still cover picture")

    def test_missing_folder_and_unreadable_paths_are_rejected(self):
        self.assert_rejected(self.root / "missing.mp4", "missing_file", "cannot be found")
        folder = self.root / "folder.mp4"
        folder.mkdir(exist_ok=True)
        self.assert_rejected(folder, "not_a_file", "is a folder")
        with patch.object(Path, "open", side_effect=PermissionError(13, "Permission denied")):
            self.assert_rejected(self.valid_mp4, "access_denied", "cannot be read")

    def test_unavailable_ffprobe_is_reported(self):
        self.assert_rejected(self.valid_mp4, "ffmpeg_unavailable", "FFmpeg could not be started",
                             ffprobe_path=self.root / "no-ffprobe.exe")
        with patch("services.media.media_validation.get_ffprobe_path", side_effect=FFmpegNotFoundError("missing")):
            self.assert_rejected(self.valid_mp4, "ffmpeg_unavailable", "FFmpeg is not available")

    def test_every_probe_has_a_timeout_and_a_timeout_is_reported(self):
        timeouts = []

        def recording_run(command, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return _original_run(command, **kwargs)

        validate_media_file(self.valid_mp4, run=recording_run)
        self.assertEqual(len(timeouts), 3)
        self.assertTrue(all(isinstance(value, float) and value > 0 for value in timeouts))

        def hanging_run(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        self.assert_rejected(self.valid_mp4, "timeout", "took too long", run=hanging_run)

    def test_undecodable_or_unidentified_codec_is_rejected(self):
        real_header = _original_run([str(self.ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json",
                                     str(self.valid_mp4)], capture_output=True, text=True, timeout=60).stdout

        def undecodable(command, **kwargs):
            if "-show_format" in command:
                return subprocess.CompletedProcess(command, 0, real_header, "")
            if "frame=pts_time" in command:
                return subprocess.CompletedProcess(command, 0, '{"frames": []}', "Decoder (codec h264) not found")
            return subprocess.CompletedProcess(command, 0, '{"packets": [{"pts_time": "5.96"}]}', "")

        self.assert_rejected(self.valid_mp4, "unsupported_codec", "cannot be decoded", run=undecodable)

        unidentified = real_header.replace('"codec_name": "h264"', '"codec_name": "none"')

        def unknown_codec(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, unidentified, "")

        self.assert_rejected(self.valid_mp4, "unsupported_codec", "cannot identify", run=unknown_codec)

    def test_missing_duration_metadata_is_rejected(self):
        real_header = _original_run([str(self.ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json",
                                     str(self.valid_mp4)], capture_output=True, text=True, timeout=60).stdout
        no_duration = real_header.replace('"duration": "6.000000"', '"duration": "N/A"')

        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, no_duration, "")

        self.assert_rejected(self.valid_mp4, "corrupted_media", "missing or invalid video information", run=run)


class MediaValidationImportAndControllerTests(_MediaFixtures):
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

        self.import_service = VideoImportService(db_session_factory=session_factory)
        self.thread_pool = FakeThreadPool()
        self.settings_service = FakeSettingsService()
        self.controller = AppController(
            video_import_service=self.import_service,
            thread_pool=self.thread_pool,
            worker_factory=FakeExportWorker,
            prepare_worker_factory=FakePrepareWorker,
            settings_service=self.settings_service,
            keyframe_worker_factory=FakeKeyframeWorker,
            subtitle_worker_factory=FakeSubtitleWorker,
            analysis_worker_factory=FakeAnalysisWorker,
            model_provisioner=FakeModelProvisioner(),
            model_provisioning_worker_factory=FakeModelProvisioningWorker,
        )

    def tearDown(self):
        super().tearDown()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def video_rows(self):
        with self.Session() as db:
            return db.query(Video).count()

    def test_import_service_records_only_validated_media(self):
        with self.assertRaises(MediaValidationError):
            self.import_service.import_video_file(self.audio_only_mp4)
        self.assertEqual(self.video_rows(), 0)
        result = self.import_service.import_video_file(self.valid_mkv)
        self.assertEqual(result["video_name"], "valid.mkv")
        self.assertEqual(self.video_rows(), 1)

    def test_invalid_file_never_reaches_a_loaded_state(self):
        data = self.faststart_mp4.read_bytes()
        truncated = self.derived("interrupted.mp4", data[: len(data) // 2])
        with self.assertLogs("services.media.media_validation", level="WARNING") as logs:
            self.controller.loadVideoFile(str(truncated))

        self.assertEqual(self.controller.selectedVideoPath, "")
        self.assertEqual(self.controller.videoUrl, "")
        self.assertEqual(self.controller.videoName, "No video selected")
        self.assertIn("\"interrupted.mp4\" is incomplete", self.controller.videoLoadError)
        self.assertEqual(self.controller.projectStatus, self.controller.videoLoadError)
        self.assertFalse(any(isinstance(w, (FakeKeyframeWorker, FakeSubtitleWorker)) for w in self.thread_pool.workers))
        self.assertIsNone(self.settings_service.last_video)
        self.assertEqual(self.video_rows(), 0)
        self.assertIn("tail packets=0", "\n".join(logs.output))

    def test_rejection_keeps_the_previous_video_and_a_valid_load_clears_the_notice(self):
        self.controller.loadVideoFile(str(self.valid_mp4))
        loaded = self.controller.selectedVideoPath
        self.assertEqual(Path(loaded), self.valid_mp4.resolve())
        self.assertEqual(self.controller.videoLoadError, "")

        self.controller.loadVideoFile(str(self.cover_art_mp4))
        self.assertEqual(self.controller.selectedVideoPath, loaded)
        self.assertIn("only a still cover picture", self.controller.videoLoadError)

        self.controller.loadVideoFile(str(self.valid_mkv))
        self.assertEqual(Path(self.controller.selectedVideoPath), self.valid_mkv.resolve())
        self.assertEqual(self.controller.videoLoadError, "")

    def test_multi_selection_skips_invalid_files_and_explains_why(self):
        renamed = self.derived("renamed.mp4", self.valid_mkv.read_bytes())
        self.controller.loadVideoFiles([str(renamed), str(self.audio_only_mp4)])
        self.assertEqual(self.controller.availableVideos, [])
        self.assertEqual(self.controller.selectedVideoPath, "")
        self.assertIn("None of the selected files could be opened", self.controller.videoLoadError)
        self.assertIn("actually an MKV video", self.controller.videoLoadError)

        self.controller.loadVideoFiles([str(self.audio_only_mp4), str(self.valid_mp4)])
        self.assertEqual([Path(v["path"]) for v in self.controller.availableVideos], [self.valid_mp4.resolve()])
        self.assertEqual(Path(self.controller.selectedVideoPath), self.valid_mp4.resolve())
        self.assertIn("skipped 1 file(s) that could not be opened", self.controller.projectStatus)
        self.assertIn("contains only audio", self.controller.projectStatus)


if __name__ == "__main__":
    unittest.main()
