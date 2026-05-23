import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.base import Base
from repositories.cut_job_repository import create_job, mark_completed, mark_running
from schemas.video_cut_schema import CutSegmentResult, VideoCutRequest, VideoCutResult


class CutJobRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_job_and_segments_are_persisted_through_completion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            output_path = temp_path / "cuts" / "movie_cut_001.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=output_path.parent,
                segments=[{"index": 1, "start_seconds": 0, "end_seconds": 5}],
            )
            result = VideoCutResult(
                input_path=input_path,
                output_paths=[output_path],
                export_mode=request.export_mode,
                cut_mode=request.cut_mode,
                segments=[
                    CutSegmentResult(
                        segment_index=1,
                        output_path=output_path,
                        start_seconds=0,
                        end_seconds=5,
                        duration_seconds=5,
                    )
                ],
            )

            with self.Session() as db:
                job = create_job(db, request)
                mark_running(db, job.id)
                mark_completed(db, job.id, result)
                db.commit()

                self.assertEqual(job.status, "completed")
                self.assertEqual(job.segments[0].output_path, str(output_path))
                self.assertEqual(job.segments[0].status, "completed")


if __name__ == "__main__":
    unittest.main()
