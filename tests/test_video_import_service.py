import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from models import User, Video
from services.video_import_service import LOCAL_USER_EMAIL, VideoImportService


class VideoImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
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

        self.service = VideoImportService(db_session_factory=session_factory)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_importing_valid_mp4_creates_video_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "sample.mp4"
            video_path.touch()

            result = self.service.import_video_file(video_path)

            self.assertEqual(result["video_name"], "sample.mp4")
            self.assertEqual(result["video_path"], str(video_path.resolve()))
            with self.Session() as db:
                self.assertEqual(db.query(Video).count(), 1)

    def test_importing_valid_mkv_creates_video_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "sample.mkv"
            video_path.touch()

            result = self.service.import_video_file(video_path)

            self.assertEqual(result["video_name"], "sample.mkv")
            with self.Session() as db:
                self.assertEqual(db.query(Video).count(), 1)

    def test_importing_unsupported_extension_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "sample.mov"
            video_path.touch()

            with self.assertRaises(ValueError):
                self.service.import_video_file(video_path)

    def test_importing_missing_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                self.service.import_video_file(Path(temp_dir) / "missing.mp4")

    def test_listing_importable_videos_returns_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video_path = folder / "sample.mp4"
            subtitle_path = folder / "sample.en.srt"
            video_path.touch()
            subtitle_path.touch()

            videos = self.service.list_importable_videos(folder)

            self.assertEqual(
                videos,
                [
                    {
                        "name": "sample.mp4",
                        "path": str(video_path.resolve()),
                        "subtitle_found": True,
                        "subtitle_name": "sample.en.srt",
                    }
                ],
            )

    def test_subtitle_information_is_returned_on_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video_path = folder / "sample.mp4"
            subtitle_path = folder / "sample.srt"
            video_path.touch()
            subtitle_path.touch()

            result = self.service.import_video_file(video_path)

            self.assertTrue(result["subtitle_found"])
            self.assertEqual(result["subtitle_name"], "sample.srt")

    def test_default_local_user_is_created_only_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            first = folder / "first.mp4"
            second = folder / "second.mkv"
            first.touch()
            second.touch()

            self.service.import_video_file(first)
            self.service.import_video_file(second)

            with self.Session() as db:
                self.assertEqual(db.query(User).filter(User.email == LOCAL_USER_EMAIL).count(), 1)
                self.assertEqual(db.query(Video).count(), 2)


if __name__ == "__main__":
    unittest.main()
