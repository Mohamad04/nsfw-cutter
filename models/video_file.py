from sqlalchemy import Column, DateTime, Integer, String

from database.base import Base
from schemas._validation import utc_now


class VideoFile(Base):
    __tablename__ = "video_files"

    id = Column(Integer, primary_key=True)
    path = Column(String(1024), nullable=False, unique=True, index=True)
    filename = Column(String(255), nullable=False)
    stem = Column(String(255), nullable=False)
    extension = Column(String(32), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
