from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String

from database.base import Base
from schemas._validation import utc_now


class VideoMetadata(Base):
    __tablename__ = "video_metadata"

    id = Column(Integer, primary_key=True)
    video_file_id = Column(Integer, ForeignKey("video_files.id", ondelete="CASCADE"), nullable=False, index=True)
    duration_seconds = Column(Float)
    format_name = Column(String(255))
    format_long_name = Column(String(255))
    bit_rate = Column(Integer)
    video_codec = Column(String(128))
    audio_codec = Column(String(128))
    width = Column(Integer)
    height = Column(Integer)
    fps = Column(Float)
    raw_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
