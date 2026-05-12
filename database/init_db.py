from database.base import Base
from database.session import engine

# Import models so SQLAlchemy registers all tables before create_all().
from models import (  # noqa: F401
    AnalysisJob,
    DetectionResult,
    User,
    Video,
    VideoCut,
    VideoSubtitle,
)


def init_db():
    Base.metadata.create_all(bind=engine)


def init_database():
    init_db()
