import unittest

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from models import AnalysisJob, DetectionResult, User, Video, VideoCut, VideoSubtitle
from repositories.analysis_job_repository import create_job, mark_job_completed, mark_job_failed, update_job_progress
from repositories.detection_result_repository import (
    add_detection_result,
    filter_results_by_confidence_threshold,
    filter_results_by_label,
    get_detection_results_by_job,
    get_detection_results_by_video,
)
from repositories.user_repository import create_user, get_user_by_email, verify_login
from repositories.video_cut_repository import add_cut_to_video, get_cuts_for_video
from repositories.video_repository import add_video, delete_video, get_videos_by_user, update_video_metadata
from repositories.video_subtitle_repository import add_subtitle_segment, get_subtitles_for_video
from security.password import verify_password


class DatabaseLayerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _create_user_and_video(self):
        user = create_user(self.db, username="tester", email="tester@example.com", password="secret-password")
        video = add_video(
            self.db,
            user_id=user.user_id,
            video_name="sample.mp4",
            video_path="sample.mp4",
            duration_ms=10_000,
            fps=24.0,
            width=1920,
            height=1080,
            file_size_bytes=1_000,
            format="mp4",
        )
        return user, video

    def test_create_user_hashes_password_and_login_works(self):
        user = create_user(self.db, username="tester", email="Tester@Example.com", password="secret-password")
        self.db.commit()

        self.assertNotEqual(user.password_hash, "secret-password")
        self.assertTrue(verify_password("secret-password", user.password_hash))
        self.assertEqual(get_user_by_email(self.db, "tester@example.com").user_id, user.user_id)
        self.assertEqual(verify_login(self.db, email="tester@example.com", password="secret-password").user_id, user.user_id)
        self.assertIsNone(verify_login(self.db, email="tester@example.com", password="wrong"))

    def test_duplicate_email_is_rejected(self):
        create_user(self.db, username="tester", email="tester@example.com", password="secret-password")
        self.db.commit()

        with self.assertRaises(IntegrityError):
            create_user(self.db, username="tester2", email="tester@example.com", password="secret-password")

    def test_create_video_and_update_metadata(self):
        user, video = self._create_user_and_video()
        self.db.commit()

        videos = get_videos_by_user(self.db, user.user_id)
        self.assertEqual([item.video_id for item in videos], [video.video_id])

        updated = update_video_metadata(self.db, video.video_id, duration_ms=12_000, format="mkv")
        self.db.commit()

        self.assertEqual(updated.duration_ms, 12_000)
        self.assertEqual(updated.format, "mkv")

    def test_cut_subtitle_job_and_detection_repositories(self):
        user, video = self._create_user_and_video()
        cut = add_cut_to_video(self.db, video_id=video.video_id, cut_start_ms=100, cut_end_ms=600, reason="manual")
        subtitle = add_subtitle_segment(self.db, video_id=video.video_id, start_ms=100, end_ms=500, text="hello", language="en")
        job = create_job(self.db, video_id=video.video_id, user_id=user.user_id, status="processing", progress=25)
        result = add_detection_result(
            self.db,
            job_id=job.job_id,
            video_id=video.video_id,
            start_ms=120,
            end_ms=480,
            label="nsfw",
            confidence=0.91,
            model_name="test-model",
        )
        self.db.commit()

        self.assertEqual(cut.cut_duration_ms, 500)
        self.assertEqual(get_cuts_for_video(self.db, video.video_id)[0].video_cut_id, cut.video_cut_id)
        self.assertEqual(get_subtitles_for_video(self.db, video.video_id)[0].subtitle_id, subtitle.subtitle_id)
        self.assertEqual(get_detection_results_by_video(self.db, video.video_id)[0].result_id, result.result_id)
        self.assertEqual(get_detection_results_by_job(self.db, job.job_id)[0].result_id, result.result_id)
        self.assertEqual(filter_results_by_label(self.db, "nsfw")[0].result_id, result.result_id)
        self.assertEqual(filter_results_by_confidence_threshold(self.db, 0.9)[0].result_id, result.result_id)

    def test_job_updates_validate_status_and_progress(self):
        user, video = self._create_user_and_video()
        job = create_job(self.db, video_id=video.video_id, user_id=user.user_id)
        update_job_progress(self.db, job.job_id, 50)
        mark_job_completed(self.db, job.job_id)
        self.db.commit()

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.progress, 100)
        self.assertIsNotNone(job.finished_at)

        failed_job = create_job(self.db, video_id=video.video_id, user_id=user.user_id)
        mark_job_failed(self.db, failed_job.job_id, "model failed")
        self.db.commit()
        self.assertEqual(failed_job.status, "failed")
        self.assertEqual(failed_job.error_message, "model failed")

    def test_invalid_ranges_and_confidence_are_rejected(self):
        user, video = self._create_user_and_video()
        job = create_job(self.db, video_id=video.video_id, user_id=user.user_id)

        with self.assertRaises(ValueError):
            add_cut_to_video(self.db, video_id=video.video_id, cut_start_ms=200, cut_end_ms=100)

        with self.assertRaises(ValueError):
            add_subtitle_segment(self.db, video_id=video.video_id, start_ms=200, end_ms=100)

        with self.assertRaises(ValueError):
            add_detection_result(
                self.db,
                job_id=job.job_id,
                video_id=video.video_id,
                start_ms=0,
                end_ms=100,
                label="nsfw",
                confidence=1.5,
            )

        with self.assertRaises(ValueError):
            update_job_progress(self.db, job.job_id, 101)

    def test_deleting_video_cascades_related_records(self):
        user, video = self._create_user_and_video()
        cut = add_cut_to_video(self.db, video_id=video.video_id, cut_start_ms=0, cut_end_ms=100)
        subtitle = add_subtitle_segment(self.db, video_id=video.video_id, start_ms=0, end_ms=100, language="und")
        job = create_job(self.db, video_id=video.video_id, user_id=user.user_id)
        result = add_detection_result(
            self.db,
            job_id=job.job_id,
            video_id=video.video_id,
            start_ms=0,
            end_ms=100,
            label="nsfw",
            confidence=0.8,
        )
        ids = (cut.video_cut_id, subtitle.subtitle_id, job.job_id, result.result_id)
        self.db.commit()

        self.assertTrue(delete_video(self.db, video.video_id))
        self.db.commit()

        self.assertIsNone(self.db.get(Video, video.video_id))
        self.assertIsNone(self.db.get(VideoCut, ids[0]))
        self.assertIsNone(self.db.get(VideoSubtitle, ids[1]))
        self.assertIsNone(self.db.get(AnalysisJob, ids[2]))
        self.assertIsNone(self.db.get(DetectionResult, ids[3]))
        self.assertIsNotNone(self.db.get(User, user.user_id))


if __name__ == "__main__":
    unittest.main()
