from dataclasses import dataclass

from schemas._validation import ALLOWED_JOB_STATUSES, clean_string


@dataclass(frozen=True)
class AnalysisJobCreateSchema:
    video_id: int
    user_id: int
    status: str = "pending"
    progress: int | None = 0

    def __post_init__(self):
        status = clean_string(self.status, "status", max_length=32, required=True)
        if status not in ALLOWED_JOB_STATUSES:
            raise ValueError(f"status must be one of {sorted(ALLOWED_JOB_STATUSES)}")
        progress = None if self.progress is None else int(self.progress)
        if progress is not None and (progress < 0 or progress > 100):
            raise ValueError("progress must be between 0 and 100")
        object.__setattr__(self, "video_id", int(self.video_id))
        object.__setattr__(self, "user_id", int(self.user_id))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "progress", progress)
