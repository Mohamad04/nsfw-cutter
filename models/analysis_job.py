from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship, validates

from database.base import Base
from schemas._validation import ALLOWED_JOB_STATUSES, clean_string


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint("progress IS NULL OR (progress >= 0 AND progress <= 100)", name="ck_analysis_jobs_progress_range"),
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')", name="ck_analysis_jobs_status_allowed"),
        Index("ix_analysis_jobs_video_user", "video_id", "user_id"),
    )

    job_id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.video_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    progress = Column(Integer)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    error_message = Column(Text)

    video = relationship("Video", back_populates="analysis_jobs")
    user = relationship("User", back_populates="analysis_jobs")
    detection_results = relationship("DetectionResult", back_populates="job", cascade="all, delete-orphan")

    @validates("status")
    def validate_status(self, _key, value):
        status = clean_string(value, "status", max_length=32, required=True)
        if status not in ALLOWED_JOB_STATUSES:
            raise ValueError(f"status must be one of {sorted(ALLOWED_JOB_STATUSES)}")
        return status

    @validates("progress")
    def validate_progress(self, _key, value):
        if value is None:
            return None
        progress = int(value)
        if progress < 0 or progress > 100:
            raise ValueError("progress must be between 0 and 100")
        return progress

    @validates("error_message")
    def validate_error_message(self, _key, value):
        return clean_string(value, "error_message")
