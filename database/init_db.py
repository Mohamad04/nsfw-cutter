from pathlib import Path

from database.base import Base
from database.session import engine

# Import models so SQLAlchemy registers all tables before create_all().
from models import (  # noqa: F401
    AnalysisJob,
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


def init_db():
    if engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def init_database():
    init_db()
