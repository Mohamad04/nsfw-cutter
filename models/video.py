from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship, validates

from database.base import Base
from models._validation import clean_string, utc_now, validate_video_path


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_user_id_created_at", "user_id", "created_at"),
    )

    video_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    video_name = Column(String(255), nullable=False)
    video_path = Column(String(1024), nullable=False)
    duration_ms = Column(Integer)
    fps = Column(Float)
    width = Column(Integer)
    height = Column(Integer)
    file_size_bytes = Column(Integer)
    format = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="videos")
    cuts = relationship("VideoCut", back_populates="video", cascade="all, delete-orphan")
    subtitles = relationship("VideoSubtitle", back_populates="video", cascade="all, delete-orphan")
    analysis_jobs = relationship("AnalysisJob", back_populates="video", cascade="all, delete-orphan")
    detection_results = relationship("DetectionResult", back_populates="video", cascade="all, delete-orphan")

    @validates("video_name")
    def validate_video_name(self, _key, value):
        return clean_string(value, "video_name", max_length=255, required=True)

    @validates("video_path")
    def validate_path(self, _key, value):
        return validate_video_path(value)

    @validates("format")
    def validate_format(self, _key, value):
        return clean_string(value, "format", max_length=32)
