import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from repositories.user_repository import create_user
from repositories.video_cut_repository import add_cut_to_video, clear_cuts_for_video, delete_cut, get_cuts_for_video
from repositories.video_repository import add_video


class VideoCutRepositoryTests(unittest.TestCase):
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
        self.user = create_user(self.db, username="tester", email="tester@example.com", password="secret-password")
        self.video = add_video(
            self.db,
            user_id=self.user.user_id,
            video_name="sample.mp4",
            video_path="sample.mp4",
            format="mp4",
        )

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_list_delete_cut(self):
        cut = add_cut_to_video(self.db, video_id=self.video.video_id, cut_start_ms=100, cut_end_ms=500)

        cuts = get_cuts_for_video(self.db, self.video.video_id)
        self.assertEqual([item.video_cut_id for item in cuts], [cut.video_cut_id])

        self.assertTrue(delete_cut(self.db, cut.video_cut_id))
        self.assertEqual(get_cuts_for_video(self.db, self.video.video_id), [])

    def test_clear_cuts_for_video(self):
        add_cut_to_video(self.db, video_id=self.video.video_id, cut_start_ms=100, cut_end_ms=500)
        add_cut_to_video(self.db, video_id=self.video.video_id, cut_start_ms=600, cut_end_ms=900)

        self.assertEqual(clear_cuts_for_video(self.db, self.video.video_id), 2)
        self.assertEqual(get_cuts_for_video(self.db, self.video.video_id), [])


if __name__ == "__main__":
    unittest.main()
