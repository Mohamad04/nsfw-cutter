from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String

from database.base import Base
from schemas._validation import utc_now


class SubtitleInfo(Base):
    __tablename__ = "subtitle_info"

    id = Column(Integer, primary_key=True)
    video_file_id = Column(Integer, ForeignKey("video_files.id", ondelete="CASCADE"), nullable=False, index=True)
    embedded_subtitles_detected = Column(Boolean, nullable=False, default=False)
    embedded_count = Column(Integer, nullable=False, default=0)
    external_subtitles_detected = Column(Boolean, nullable=False, default=False)
    external_count = Column(Integer, nullable=False, default=0)
    selected_external_subtitle_path = Column(String(1024))
    subtitle_action = Column(String(64), nullable=False)
    reason = Column(String(1024), nullable=False)
    embedded_streams_json = Column(JSON, nullable=False)
    external_subtitles_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
