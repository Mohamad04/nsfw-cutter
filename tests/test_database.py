import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from database.base import Base
from models import (
    AnalysisJob,
    CutJob,
    CutJobSegment,
    DetectionResult,
    ExportJob,
    SubtitleInfo,
    User,
    Video,
    VideoCut,
    VideoFile,
    VideoMetadata,
    VideoSubtitle,
)


class DatabaseInitializationTests(unittest.TestCase):
    def test_metadata_creates_expected_tables(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        try:
            Base.metadata.create_all(bind=engine)
            tables = set(inspect(engine).get_table_names())
            self.assertEqual(
                {
                    User.__tablename__,
                    Video.__tablename__,
                    VideoCut.__tablename__,
                    VideoSubtitle.__tablename__,
                    VideoFile.__tablename__,
                    VideoMetadata.__tablename__,
                    SubtitleInfo.__tablename__,
                    ExportJob.__tablename__,
                    CutJob.__tablename__,
                    CutJobSegment.__tablename__,
                    AnalysisJob.__tablename__,
                    DetectionResult.__tablename__,
                },
                tables,
            )
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
