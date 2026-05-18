from dataclasses import dataclass

from schemas._validation import clean_string, validate_video_path


@dataclass(frozen=True)
class VideoImportSchema:
    video_name: str
    video_path: str
    format: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "video_name", clean_string(self.video_name, "video_name", max_length=255, required=True))
        object.__setattr__(self, "video_path", validate_video_path(self.video_path))
        object.__setattr__(self, "format", clean_string(self.format, "format", max_length=32))
