from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String

from database.base import Base
from schemas._validation import utc_now


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id = Column(Integer, primary_key=True)
    job_id = Column(String(64), nullable=False, unique=True, index=True)
    job_type = Column(String(64), nullable=False)
    status = Column(String(64), nullable=False)
    progress = Column(Integer, nullable=False, default=0)
    input_video_path = Column(String(1024), nullable=False)
    output_path = Column(String(1024), nullable=False)
    export_mode = Column(String(64), nullable=False)
    reencode = Column(Boolean, nullable=False, default=False)
    subtitle_action = Column(String(64), nullable=False)
    selected_external_subtitle_path = Column(String(1024))
    settings_json = Column(JSON, nullable=False)
    segments_json = Column(JSON, nullable=False)
    result_json = Column(JSON, nullable=False)
    full_job_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    error_message = Column(String(2048))
