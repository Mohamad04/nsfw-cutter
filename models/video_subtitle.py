from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship, validates

from database.base import Base
from schemas._validation import clean_string, utc_now, validate_language, validate_non_negative, validate_time_range


class VideoSubtitle(Base):
    __tablename__ = "video_subtitles"
    __table_args__ = (
        CheckConstraint("start_ms >= 0", name="ck_video_subtitles_start_non_negative"),
        CheckConstraint("end_ms > start_ms", name="ck_video_subtitles_end_after_start"),
        Index("ix_video_subtitles_video_id_start", "video_id", "start_ms"),
    )

    subtitle_id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.video_id", ondelete="CASCADE"), nullable=False, index=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text)
    language = Column(String(16))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    video = relationship("Video", back_populates="subtitles")

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

    @validates("text")
    def validate_text(self, _key, value):
        return clean_string(value, "text")

    @validates("language")
    def validate_subtitle_language(self, _key, value):
        return validate_language(value)
