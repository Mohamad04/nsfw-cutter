import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.json_writer import write_json_artifact
from core.time_utils import parse_fraction_to_float
from database.base import Base
from services.media.metadata_service import get_video_metadata
from services.media.validation_service import validate_input_video
from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams
from services.subtitles.policy_service import decide_subtitle_action
from services.workflows.export_job_service import create_export_job_data
from repositories.user_repository import create_user
from repositories.video_repository import add_video


class BackendPipelineV1Tests(unittest.TestCase):
    def test_video_validation_accepts_mp4_and_mkv_and_rejects_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            mp4 = folder / "movie.mp4"
            mkv = folder / "movie.mkv"
            exe = folder / "movie.exe"
            mp4.touch()
            mkv.touch()
            exe.touch()

            self.assertEqual(validate_input_video(mp4), mp4.resolve())
            self.assertEqual(validate_input_video(mkv), mkv.resolve())
            with self.assertRaises(ValueError):
                validate_input_video(exe)
            with self.assertRaises(ValueError):
                validate_input_video(folder / "missing.mp4")

    def test_parse_fraction_to_float(self):
        self.assertAlmostEqual(parse_fraction_to_float("24000/1001"), 23.976, places=3)
        self.assertEqual(parse_fraction_to_float("25/1"), 25.0)
        self.assertIsNone(parse_fraction_to_float(None))
        self.assertIsNone(parse_fraction_to_float("bad"))

    def test_video_metadata_service_parses_ffprobe_output(self):
        ffprobe_output = {
            "format": {
                "duration": "12.5",
                "format_name": "mov,mp4",
                "format_long_name": "QuickTime / MOV",
                "bit_rate": "2500000",
            },
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "codec_long_name": "H.264",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "24000/1001",
                    "pix_fmt": "yuv420p",
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "codec_long_name": "AAC",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.write_bytes(b"fake")

            metadata = get_video_metadata(video, media_probe=lambda _path: ffprobe_output)

        self.assertEqual(metadata["filename"], "movie.mp4")
        self.assertEqual(metadata["duration_seconds"], 12.5)
        self.assertEqual(metadata["video"]["codec_name"], "h264")
        self.assertAlmostEqual(metadata["video"]["fps"], 23.976, places=3)
        self.assertEqual(metadata["audio"]["sample_rate"], 48000)
        self.assertEqual(metadata["raw_ffprobe"], ffprobe_output)

    def test_subtitle_discovery_finds_matching_srt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            subtitle = Path(temp_dir) / "movie.srt"
            video.touch()
            subtitle.touch()

            matches = find_matching_external_subtitles(video)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["filename"], "movie.srt")
        self.assertEqual(matches[0]["detected_by"], "same_stem_sidecar")

    def test_subtitle_discovery_returns_empty_when_no_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()

            self.assertEqual(find_matching_external_subtitles(video), [])

    def test_subtitle_inspection_maps_embedded_streams(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()

            streams = get_embedded_subtitle_streams(
                video,
                subtitle_probe=lambda _path: [
                    {
                        "index": 2,
                        "codec_name": "subrip",
                        "tags": {"language": "eng", "title": "English"},
                    }
                ],
            )

        self.assertEqual(
            streams,
            [
                {
                    "index": 2,
                    "codec_name": "subrip",
                    "language": "eng",
                    "title": "English",
                }
            ],
        )

    def test_subtitle_policy(self):
        embedded = [{"index": 2, "codec_name": "subrip"}]
        external = [{"path": "movie.srt"}]

        self.assertEqual(decide_subtitle_action(embedded, external)["action"], "keep_embedded")
        self.assertEqual(decide_subtitle_action([], external)["action"], "add_external")
        self.assertEqual(decide_subtitle_action([], [])["action"], "none")

    def test_export_job_creation(self):
        metadata = {
            "path": str(Path("movie.mp4").resolve()),
            "duration_seconds": 10.0,
            "format_name": "mov,mp4",
            "video": {"codec_name": "h264", "width": 1920, "height": 1080, "fps": 24.0},
            "audio": {"codec_name": "aac"},
        }
        policy = decide_subtitle_action([], [{"path": str(Path("movie.srt").resolve())}])

        job = create_export_job_data(metadata, policy)

        self.assertEqual(job["status"], "pending")
        self.assertEqual(job["progress"], 0)
        self.assertFalse(job["export_settings"]["reencode"])
        self.assertTrue(job["output"]["path"].endswith(".mkv"))
        self.assertEqual(job["segments"]["safe_segments"], [{"start": 0.0, "end": 10.0}])
        self.assertEqual(job["segments"]["remove_segments"], [])
        self.assertEqual(job["subtitle_policy"], policy)

    def test_json_writer_writes_readable_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = write_json_artifact({"key": "value"}, temp_dir, "metadata", "movie")
            loaded = json.loads(Path(output_path).read_text(encoding="utf-8"))

        self.assertEqual(loaded, {"key": "value"})

    def test_backend_pipeline_persists_db_records_and_json_artifacts(self):
        from services.workflows import backend_pipeline_service

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(bind=engine)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                folder = Path(temp_dir)
                video = folder / "movie.mp4"
                metadata_dir = folder / "json" / "metadata"
                subtitles_dir = folder / "json" / "subtitles"
                export_jobs_dir = folder / "json" / "export_jobs"
                video.write_bytes(b"fake")

                metadata = {
                    "path": str(video.resolve()),
                    "filename": "movie.mp4",
                    "stem": "movie",
                    "extension": ".mp4",
                    "file_size_bytes": 4,
                    "duration_seconds": 5.0,
                    "format_name": "mov,mp4",
                    "format_long_name": "QuickTime / MOV",
                    "bit_rate": 1000,
                    "video": {"codec_name": "h264", "width": 640, "height": 360, "fps": 25.0},
                    "audio": {"codec_name": "aac"},
                    "raw_ffprobe": {"format": {}, "streams": []},
                }

                with Session() as session:
                    user = create_user(session, username="tester", email="tester@example.com", password="secret-password")
                    add_video(
                        session,
                        user_id=user.user_id,
                        video_name="movie.mp4",
                        video_path=str(video.resolve()),
                    )
                    session.commit()

                with patch.object(backend_pipeline_service, "SessionLocal", Session):
                    with patch.object(backend_pipeline_service, "METADATA_JSON_DIR", metadata_dir):
                        with patch.object(backend_pipeline_service, "SUBTITLES_JSON_DIR", subtitles_dir):
                            with patch.object(backend_pipeline_service, "EXPORT_JOBS_JSON_DIR", export_jobs_dir):
                                with patch.object(backend_pipeline_service, "get_video_metadata", return_value=metadata):
                                    with patch.object(backend_pipeline_service, "get_embedded_subtitle_streams", return_value=[]):
                                        result = backend_pipeline_service.prepare_export_job_pipeline(str(video))

                self.assertEqual(result["metadata"], metadata)
                self.assertEqual(result["subtitle_info"]["policy"]["action"], "none")
                self.assertEqual(result["export_job"]["status"], "pending")
                for path in result["json_artifacts"].values():
                    self.assertTrue(Path(path).is_file())
                self.assertEqual(result["database"]["video_file_id"], 1)
                self.assertEqual(result["database"]["metadata_id"], 1)
                self.assertEqual(result["database"]["subtitle_info_id"], 1)
                self.assertEqual(result["database"]["export_job_id"], 1)
                with Session() as session:
                    from models import Video

                    video_row = session.query(Video).filter(Video.video_path == str(video.resolve())).one()
                    self.assertEqual(video_row.duration_ms, 5000)
                    self.assertEqual(video_row.fps, 25.0)
                    self.assertEqual(video_row.width, 640)
                    self.assertEqual(video_row.height, 360)
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
