from dataclasses import dataclass

from schemas._validation import clean_string, validate_language, validate_non_negative, validate_time_range


@dataclass(frozen=True)
class VideoSubtitleCreateSchema:
    video_id: int
    start_ms: int
    end_ms: int
    text: str | None = None
    language: str | None = "und"

    def __post_init__(self):
        start = validate_non_negative(self.start_ms, "start_ms")
        end = int(self.end_ms)
        validate_time_range(start, end)
        object.__setattr__(self, "video_id", int(self.video_id))
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "text", clean_string(self.text, "text"))
        object.__setattr__(self, "language", validate_language(self.language))
