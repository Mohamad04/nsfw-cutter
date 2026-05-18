from dataclasses import dataclass

from schemas._validation import clean_string, validate_non_negative, validate_time_range


@dataclass(frozen=True)
class VideoCutCreateSchema:
    video_id: int
    cut_start_ms: int
    cut_end_ms: int
    reason: str | None = None

    def __post_init__(self):
        start = validate_non_negative(self.cut_start_ms, "cut_start_ms")
        end = int(self.cut_end_ms)
        validate_time_range(start, end, start_name="cut_start_ms", end_name="cut_end_ms")
        object.__setattr__(self, "video_id", int(self.video_id))
        object.__setattr__(self, "cut_start_ms", start)
        object.__setattr__(self, "cut_end_ms", end)
        object.__setattr__(self, "reason", clean_string(self.reason, "reason", max_length=255))
