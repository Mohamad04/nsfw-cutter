import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controllers.video_cut_controller import VideoCutController
from database.base import Base
from services.export.media_probe_service import MediaProbeService
from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_ffprobe_path,
)
from services.infrastructure.ffmpeg.runner import FFmpegService


class _SynchronousThreadPool:
    def start(self, worker):
        worker.run()


class _MemorySettingsService:
    def __init__(self):
        self.settings = SimpleNamespace(default_export_dir=None, export_dir=None)

    def load(self):
        return self.settings

    def update(self, **changes):
        for key, value in changes.items():
            setattr(self.settings, key, value)
        return self.settings


class RealFFmpegVideoCutIntegrationTests(unittest.TestCase):
    def test_controller_remove_intervals_exports_probeable_h264_mp4_with_audio(self):
        try:
            ffmpeg_path = get_ffmpeg_path()
            ffprobe_path = get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            self.skipTest(str(exc))

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Session = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )
        Base.metadata.create_all(bind=engine)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                input_path = root / "compatible-input.mp4"
                output_dir = root / "exports"
                _generate_compatible_fixture(ffmpeg_path, input_path)

                ffmpeg_service = FFmpegService(ffmpeg_path, ffprobe_path)
                media_probe = MediaProbeService(ffmpeg_service=ffmpeg_service)
                source_info = media_probe.probe(input_path)
                self.assertEqual(source_info.video_stream.codec_name, "h264")
                self.assertEqual(source_info.video_stream.pix_fmt, "yuv420p")
                self.assertTrue(source_info.has_audio)

                controller = VideoCutController(
                    thread_pool=_SynchronousThreadPool(),
                    settings_service=_MemorySettingsService(),
                )
                failures = []
                completions = []
                controller.cutFailed.connect(failures.append)
                controller.cutFinished.connect(completions.append)

                with (
                    patch("services.editing.cut_pipeline_service.SessionLocal", Session),
                    patch(
                        "services.editing.cut_execution_service.get_cuts_cache_dir",
                        return_value=root / "cut-cache",
                    ),
                ):
                    controller.exportSegments(
                        str(input_path),
                        [
                            {
                                "start": "00:00:01",
                                "end": "00:00:02",
                                "timing_mode": "requested",
                            }
                        ],
                        str(output_dir),
                        "remove_intervals",
                    )

                self.assertEqual(failures, [])
                self.assertEqual(len(completions), 1)
                self.assertFalse(controller.cutBusy)
                self.assertEqual(controller.cutError, "")
                self.assertEqual(len(controller.cutOutputPaths), 1)
                self.assertIn("FFmpeg commands: 3", controller.cutDetails)
                self.assertIn("-f concat", controller.cutDetails)

                output_path = Path(controller.cutOutputPaths[0])
                self.assertTrue(output_path.is_file())
                self.assertGreater(output_path.stat().st_size, 0)

                output_info = media_probe.probe(output_path)
                self.assertIsNotNone(output_info.video_stream)
                self.assertEqual(output_info.video_stream.codec_name, "h264")
                self.assertEqual(output_info.video_stream.pix_fmt, "yuv420p")
                self.assertTrue(output_info.has_audio)
                self.assertEqual(output_info.audio_streams[0].codec_name, "aac")
                self.assertAlmostEqual(output_info.duration_seconds, 3.0, delta=0.35)
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


def _generate_compatible_fixture(ffmpeg_path: Path, output_path: Path) -> None:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=4:size=160x90:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=48000:duration=4",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "10",
        "-keyint_min",
        "10",
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        "-movflags",
        "+faststart",
        "-y",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Unable to create FFmpeg cut fixture")


if __name__ == "__main__":
    unittest.main()
