from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import relationship, validates

from database.base import Base
from models._validation import clean_string, utc_now, validate_non_negative, validate_time_range


class VideoCut(Base):
    __tablename__ = "video_cuts"
    __table_args__ = (
        CheckConstraint("cut_start_ms >= 0", name="ck_video_cuts_start_non_negative"),
        CheckConstraint("cut_end_ms > cut_start_ms", name="ck_video_cuts_end_after_start"),
        CheckConstraint("cut_duration_ms IS NULL OR cut_duration_ms = cut_end_ms - cut_start_ms", name="ck_video_cuts_duration_matches"),
        Index("ix_video_cuts_video_id_start", "video_id", "cut_start_ms"),
    )

    video_cut_id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.video_id", ondelete="CASCADE"), nullable=False, index=True)
    cut_start_ms = Column(Integer, nullable=False)
    cut_end_ms = Column(Integer, nullable=False)
    cut_duration_ms = Column(Integer)
    reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    video = relationship("Video", back_populates="cuts")

    @validates("cut_start_ms")
    def validate_start(self, _key, value):
        start = validate_non_negative(value, "cut_start_ms")
        validate_time_range(start, self.cut_end_ms, start_name="cut_start_ms", end_name="cut_end_ms")
        return start

    @validates("cut_end_ms")
    def validate_end(self, _key, value):
        end = int(value)
        validate_time_range(self.cut_start_ms, end, start_name="cut_start_ms", end_name="cut_end_ms")
        return end

    @validates("cut_duration_ms")
    def validate_duration(self, _key, value):
        if value is None:
            return None
        duration = int(value)
        if self.cut_start_ms is not None and self.cut_end_ms is not None and duration != self.cut_end_ms - self.cut_start_ms:
            raise ValueError("cut_duration_ms must equal cut_end_ms - cut_start_ms")
        return duration

    @validates("reason")
    def validate_reason(self, _key, value):
        return clean_string(value, "reason", max_length=255)


@event.listens_for(VideoCut, "before_insert")
@event.listens_for(VideoCut, "before_update")
def _compute_cut_duration(_mapper, _connection, target):
    validate_time_range(target.cut_start_ms, target.cut_end_ms, start_name="cut_start_ms", end_name="cut_end_ms")
    duration = target.cut_end_ms - target.cut_start_ms
    if target.cut_duration_ms is None:
        target.cut_duration_ms = duration
    elif target.cut_duration_ms != duration:
        raise ValueError("cut_duration_ms must equal cut_end_ms - cut_start_ms")
