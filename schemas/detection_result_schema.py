from dataclasses import dataclass

from schemas._validation import clean_string, validate_non_negative, validate_time_range


@dataclass(frozen=True)
class DetectionResultCreateSchema:
    job_id: int
    video_id: int
    start_ms: int
    end_ms: int
    label: str
    confidence: float | None = None
    model_name: str | None = None

    def __post_init__(self):
        start = validate_non_negative(self.start_ms, "start_ms")
        end = int(self.end_ms)
        validate_time_range(start, end)
        confidence = None if self.confidence is None else float(self.confidence)
        if confidence is not None and (confidence < 0.0 or confidence > 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "job_id", int(self.job_id))
        object.__setattr__(self, "video_id", int(self.video_id))
        object.__setattr__(self, "start_ms", start)
        object.__setattr__(self, "end_ms", end)
        object.__setattr__(self, "label", clean_string(self.label, "label", max_length=64, required=True))
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "model_name", clean_string(self.model_name, "model_name", max_length=255))
