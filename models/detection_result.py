from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship, validates

from database.base import Base
from schemas._validation import clean_string, utc_now, validate_non_negative, validate_time_range


class DetectionResult(Base):
    __tablename__ = "detection_results"
    __table_args__ = (
        CheckConstraint("start_ms >= 0", name="ck_detection_results_start_non_negative"),
        CheckConstraint("end_ms > start_ms", name="ck_detection_results_end_after_start"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)", name="ck_detection_results_confidence_range"),
        Index("ix_detection_results_video_label", "video_id", "label"),
        Index("ix_detection_results_job_start", "job_id", "start_ms"),
    )

    result_id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("analysis_jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
    video_id = Column(Integer, ForeignKey("videos.video_id", ondelete="CASCADE"), nullable=False, index=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    label = Column(String(64), nullable=False)
    confidence = Column(Float)
    model_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    job = relationship("AnalysisJob", back_populates="detection_results")
    video = relationship("Video", back_populates="detection_results")

    @validates("start_ms")
    def validate_start(self, _key, value):
        start = validate_non_negative(value, "start_ms")
        validate_time_range(start, self.end_ms)
        return start

    @validates("end_ms")
    def validate_end(self, _key, value):
        end = int(value)
        validate_time_range(self.start_ms, end)
        return end

    @validates("label")
    def validate_label(self, _key, value):
        return clean_string(value, "label", max_length=64, required=True)

    @validates("confidence")
    def validate_confidence(self, _key, value):
        if value is None:
            return None
        confidence = float(value)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return confidence

    @validates("model_name")
    def validate_model_name(self, _key, value):
        return clean_string(value, "model_name", max_length=255)
