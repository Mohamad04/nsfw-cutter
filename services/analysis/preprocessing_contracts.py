from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MICROSECONDS_PER_SECOND = 1_000_000


class SampleReason(str, Enum):
    TEMPORAL_SAFETY = "temporal_safety"
    SCENE_TRANSITION = "scene_transition"


class FrameDisposition(str, Enum):
    REPRESENTATIVE = "representative"
    BLACK = "black"
    NEAR_DUPLICATE = "near_duplicate"
    STATIC_SUPPRESSED = "static_suppressed"


class PreprocessingConfig(BaseModel):
    """Versioned settings for prompt-independent visual preprocessing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_duration_seconds: float = Field(default=240.0, gt=0.0)
    chunk_overlap_seconds: float = Field(default=2.0, ge=0.0)
    max_sampling_gap_seconds: float = Field(default=1.0, gt=0.0)
    selected_video_stream_index: int = Field(default=0, ge=0)
    scene_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    target_width: int = Field(default=384, gt=0)
    target_height: int = Field(default=384, gt=0)
    black_pixel_luma_threshold: int = Field(default=12, ge=0, le=255)
    black_frame_ratio_threshold: float = Field(default=0.995, ge=0.0, le=1.0)
    black_mean_luma_threshold: float = Field(default=8.0, ge=0.0, le=255.0)
    perceptual_hash_algorithm: Literal["dhash-spatial-64"] = "dhash-spatial-64"
    perceptual_hash_version: int = Field(default=1, ge=1)
    duplicate_hamming_threshold: int = Field(default=3, ge=0, le=64)
    static_suppression_limit_seconds: float = Field(default=10.0, gt=0.0)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> PreprocessingConfig:
        if self.chunk_overlap_seconds >= self.chunk_duration_seconds:
            raise ValueError("chunk overlap must be shorter than chunk duration")
        if round(self.chunk_duration_seconds * MICROSECONDS_PER_SECOND) <= 0:
            raise ValueError("chunk duration must be at least one microsecond")
        if round(self.max_sampling_gap_seconds * MICROSECONDS_PER_SECOND) <= 0:
            raise ValueError("sampling gap must be at least one microsecond")
        if round(self.static_suppression_limit_seconds * MICROSECONDS_PER_SECOND) <= 0:
            raise ValueError("static suppression limit must be at least one microsecond")
        return self

    @property
    def chunk_duration_us(self) -> int:
        return round(self.chunk_duration_seconds * MICROSECONDS_PER_SECOND)

    @property
    def chunk_overlap_us(self) -> int:
        return round(self.chunk_overlap_seconds * MICROSECONDS_PER_SECOND)

    @property
    def max_sampling_gap_us(self) -> int:
        return round(self.max_sampling_gap_seconds * MICROSECONDS_PER_SECOND)

    @property
    def static_suppression_limit_us(self) -> int:
        return round(self.static_suppression_limit_seconds * MICROSECONDS_PER_SECOND)


class ProcessingChunk(BaseModel):
    """Logical work unit; its core is the sole owner of timestamps in that range."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0)
    core_start_us: int = Field(ge=0)
    core_end_us: int = Field(gt=0)
    decode_start_us: int = Field(ge=0)
    decode_end_us: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> ProcessingChunk:
        if self.core_end_us <= self.core_start_us:
            raise ValueError("chunk core range must have positive duration")
        if self.decode_end_us <= self.decode_start_us:
            raise ValueError("chunk decode range must have positive duration")
        if self.decode_start_us > self.core_start_us or self.decode_end_us < self.core_end_us:
            raise ValueError("chunk decode range must contain its core range")
        return self


class FrameSample(BaseModel):
    """Persistent-safe metadata for a sampled frame; raw pixels are never retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_us: int = Field(ge=0)
    source_pts: int | None = None
    source_time_base: str | None = None
    owning_chunk_index: int = Field(ge=0)
    sample_reasons: frozenset[SampleReason] = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    content_rect: tuple[int, int, int, int]
    scene_score: float | None = Field(default=None, ge=0.0, le=1.0)
    black_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_luma: float | None = Field(default=None, ge=0.0, le=255.0)
    content_mean_rgb: tuple[float, float, float] | None = None
    perceptual_hash: str | None = None
    regional_hashes: tuple[str, ...] = ()
    regional_mean_rgb: tuple[tuple[float, float, float], ...] = ()
    disposition: FrameDisposition
    duplicate_of_timestamp_us: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_content_rect(self) -> FrameSample:
        left, top, width, height = self.content_rect
        if left < 0 or top < 0 or width <= 0 or height <= 0:
            raise ValueError("content rectangle must be positive and non-negative")
        if left + width > self.width or top + height > self.height:
            raise ValueError("content rectangle must fit inside the frame")
        return self


class PreprocessingStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    movie_duration_us: int = Field(ge=0)
    preprocessing_wall_seconds: float = Field(ge=0.0)
    chunks_processed: int = Field(ge=0)
    temporal_samples: int = Field(ge=0)
    scene_samples: int = Field(ge=0)
    samples_considered: int = Field(ge=0)
    black_frames_removed: int = Field(ge=0)
    duplicates_removed: int = Field(ge=0)
    static_frames_suppressed: int = Field(ge=0)
    representative_frames: int = Field(ge=0)
    media_throughput: float = Field(ge=0.0)

    @property
    def movie_duration_seconds(self) -> float:
        return self.movie_duration_us / MICROSECONDS_PER_SECOND


class PreprocessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: PreprocessingConfig
    chunks: tuple[ProcessingChunk, ...]
    representative_frames: tuple[FrameSample, ...]
    statistics: PreprocessingStatistics
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
