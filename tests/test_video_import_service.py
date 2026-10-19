import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from models import User, Video, VideoCut
from repositories.user_repository import create_user
from repositories.video_cut_repository import add_cut_to_video
from repositories.video_repository import add_video
from services.media.import_service import LOCAL_USER_EMAIL, VideoImportService


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

        # These tests cover the database records; real media validation is in test_media_validation.py.
        self.service = VideoImportService(db_session_factory=session_factory, media_validator=lambda path: None)

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
                        "extension": ".mp4",
                        "file_size_bytes": 0,
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


class VideoRecordReuseTests(VideoImportServiceTests):
    """Reopening a file reuses its oldest Video row instead of inserting a duplicate."""

    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.video = self.folder / "movie.mp4"
        self.video.write_bytes(b"first version")

    def tearDown(self):
        self.temp.cleanup()
        super().tearDown()

    def rows(self):
        with self.Session() as db:
            return [(row.video_id, row.user_id, row.video_path, row.file_size_bytes)
                    for row in db.query(Video).order_by(Video.video_id)]

    def local_user_id(self):
        with self.Session() as db:
            return db.query(User).filter(User.email == LOCAL_USER_EMAIL).one().user_id

    def test_reopening_the_same_video_reuses_its_row(self):
        first = self.service.import_video_file(self.video)
        second = self.service.import_video_file(self.video)
        self.assertEqual(second["video_id"], first["video_id"])
        self.assertEqual(len(self.rows()), 1)

    def test_modified_file_at_the_same_path_keeps_its_row_and_refreshes_metadata(self):
        first = self.service.import_video_file(self.video)
        self.video.write_bytes(b"second, longer version")
        second = self.service.import_video_file(self.video)
        self.assertEqual(second["video_id"], first["video_id"])
        self.assertEqual(self.rows(), [(first["video_id"], self.local_user_id(), str(self.video.resolve()),
                                        len(b"second, longer version"))])

    def test_moved_file_gets_a_new_row_and_the_old_one_is_kept(self):
        first = self.service.import_video_file(self.video)
        moved = self.folder / "archive" / "movie.mp4"
        moved.parent.mkdir()
        self.video.rename(moved)
        second = self.service.import_video_file(moved)
        self.assertNotEqual(second["video_id"], first["video_id"])
        self.assertEqual([row[2] for row in self.rows()], [str(self.video.resolve()), str(moved.resolve())])

    def test_missing_or_invalid_file_changes_nothing(self):
        first = self.service.import_video_file(self.video)
        before = self.rows()
        with self.assertRaises(ValueError):
            self.service.import_video_file(self.folder / "missing.mp4")

        def reject(_path, **_kwargs):
            raise ValueError("damaged")

        self.service.media_validator = reject
        with self.assertRaises(ValueError):
            self.service.import_video_file(self.video)
        self.assertEqual(self.rows(), before)
        self.assertEqual(before[0][0], first["video_id"])

    def test_existing_duplicates_reuse_the_oldest_and_are_never_removed(self):
        self.service.import_video_file(self.video)
        user_id = self.local_user_id()
        with self.Session() as db:
            for _ in range(2):
                add_video(db, user_id=user_id, video_name="movie.mp4", video_path=str(self.video.resolve()))
            db.commit()
        before_ids = [row[0] for row in self.rows()]
        self.assertEqual(len(before_ids), 3)
        result = self.service.import_video_file(self.video)
        self.assertEqual(result["video_id"], min(before_ids))
        self.assertEqual([row[0] for row in self.rows()], before_ids)

    def test_distinct_users_keep_distinct_rows(self):
        with self.Session() as db:
            other = create_user(db, username="other", email="other@example.local", password="placeholder")
            db.commit()
            other_id = other.user_id
        mine = self.service.import_video_file(self.video)
        self.service.validate_video_file(self.video)
        theirs = self.service.register_video_file(self.video, user_id=other_id)
        self.assertNotEqual(mine["video_id"], theirs["video_id"])
        self.assertEqual(sorted(row[1] for row in self.rows()), sorted([self.local_user_id(), other_id]))

    def test_related_records_stay_attached_to_the_reused_row(self):
        first = self.service.import_video_file(self.video)
        with self.Session() as db:
            add_cut_to_video(db, video_id=first["video_id"], cut_start_ms=1000, cut_end_ms=2000)
            db.commit()
        self.video.write_bytes(b"edited elsewhere")
        second = self.service.import_video_file(self.video)
        self.assertEqual(second["video_id"], first["video_id"])
        with self.Session() as db:
            self.assertEqual([cut.video_id for cut in db.query(VideoCut).all()], [first["video_id"]])

    @unittest.skipUnless(os.name == "nt", "file paths are case-insensitive on Windows only")
    def test_path_case_differences_reuse_the_row_on_windows(self):
        first = self.service.import_video_file(self.video)
        with self.Session() as db:
            row = db.get(Video, first["video_id"])
            row.video_path = row.video_path.upper()
            db.commit()
        second = self.service.import_video_file(Path(str(self.video).lower()))
        self.assertEqual(second["video_id"], first["video_id"])
        self.assertEqual(len(self.rows()), 1)

    def test_concurrent_imports_of_the_same_file_create_one_row(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.service.import_video_file(self.video), range(16)))
        self.assertEqual({result["video_id"] for result in results}, {results[0]["video_id"]})
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
