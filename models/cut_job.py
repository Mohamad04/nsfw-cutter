from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database.base import Base
from schemas._validation import utc_now


class CutJob(Base):
    __tablename__ = "cut_jobs"

    id = Column(Integer, primary_key=True)
    input_video_path = Column(String(1024), nullable=False)
    export_mode = Column(String(64), nullable=False)
    cut_mode = Column(String(64), nullable=False)
    output_dir = Column(String(1024), nullable=False)
    merged_output_path = Column(String(1024))
    status = Column(String(64), nullable=False, default="pending")
    error_message = Column(String(2048))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))

    segments = relationship("CutJobSegment", back_populates="job", cascade="all, delete-orphan")


class CutJobSegment(Base):
    __tablename__ = "cut_segments"

    id = Column(Integer, primary_key=True)
    cut_job_id = Column(Integer, ForeignKey("cut_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    start_seconds = Column(Float, nullable=False)
    end_seconds = Column(Float, nullable=False)
    output_path = Column(String(1024))
    status = Column(String(64), nullable=False, default="pending")
    error_message = Column(String(2048))

    job = relationship("CutJob", back_populates="segments")
