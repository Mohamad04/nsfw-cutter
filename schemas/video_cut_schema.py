from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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


class CutExportMode(str, Enum):
    REMOVE_INTERVALS = "remove_intervals"
    EXPORT_CLIPS_SEPARATE = "export_clips_separate"
    EXPORT_CLIPS_MERGED = "export_clips_merged"


class CutMode(str, Enum):
    STREAM_COPY = "stream_copy"


class VideoCutSegment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    index: int = Field(..., ge=1)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(..., ge=0)
    requested_start_seconds: float | None = Field(default=None, ge=0)
    requested_end_seconds: float | None = Field(default=None, ge=0)
    previous_keyframe_start: float | None = Field(default=None, ge=0)
    next_keyframe_start: float | None = Field(default=None, ge=0)
    previous_keyframe_end: float | None = Field(default=None, ge=0)
    next_keyframe_end: float | None = Field(default=None, ge=0)
    label: str | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Segment end must be greater than segment start.")
        if (
            self.requested_start_seconds is not None
            and self.requested_end_seconds is not None
            and self.requested_end_seconds <= self.requested_start_seconds
        ):
            raise ValueError("Requested segment end must be greater than requested segment start.")
        return self


class VideoCutRequest(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    input_path: Path
    output_dir: Path
    segments: list[VideoCutSegment]
    export_mode: CutExportMode = CutExportMode.REMOVE_INTERVALS
    cut_mode: CutMode = CutMode.STREAM_COPY
    merged_output_name: str | None = None

    @field_validator("export_mode", mode="before")
    @classmethod
    def migrate_export_mode(cls, value):
        if value == "separate":
            return CutExportMode.EXPORT_CLIPS_SEPARATE
        if value == "merged":
            return CutExportMode.EXPORT_CLIPS_MERGED
        return value

    @field_validator("segments")
    @classmethod
    def validate_segments(cls, value):
        if not value:
            raise ValueError("At least one cut segment is required.")
        return value

    @model_validator(mode="after")
    def validate_input_path(self):
        if not self.input_path.is_file():
            raise ValueError(f"Input video does not exist: {self.input_path}")
        return self


class CutSegmentResult(BaseModel):
    segment_index: int
    output_path: Path
    start_seconds: float
    end_seconds: float
    requested_start_seconds: float | None = None
    requested_end_seconds: float | None = None
    previous_keyframe_start: float | None = None
    next_keyframe_start: float | None = None
    previous_keyframe_end: float | None = None
    next_keyframe_end: float | None = None
    duration_seconds: float


class VideoCutResult(BaseModel):
    input_path: Path
    output_paths: list[Path]
    merged_output_path: Path | None = None
    segments: list[CutSegmentResult]
    export_mode: CutExportMode
    cut_mode: CutMode
    input_duration_seconds: float | None = None
    expected_output_duration_seconds: float | None = None
    actual_output_duration_seconds: float | None = None
    duration_difference_seconds: float | None = None
    duration_warning: str | None = None
    normalized_intervals: list[tuple[float, float]] = Field(default_factory=list)
    kept_intervals: list[tuple[float, float]] = Field(default_factory=list)
    ffmpeg_commands: list[list[str]] = Field(default_factory=list)
    ffmpeg_stderr: list[str] = Field(default_factory=list)
    status: str = "completed"
