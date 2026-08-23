from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

DEFAULT_QWEN_MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
DEFAULT_QWEN_MODEL_REVISION = "66285546d2b821cf421d4f5eb2576359d3770cd3"
DEFAULT_PREFILTER_MODEL_ID = "Marqo/nsfw-image-detection-384"
DEFAULT_PREFILTER_MODEL_REVISION = "0c26ec22111b83f106d72a55f611ec35962bcb65"


class AnalysisMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    THOROUGH = "thorough"


class NSFWCategory(str, Enum):
    NUDITY = "nudity"
    SEXUAL_ACTIVITY = "sexual_activity"
    SEXUAL_CONTEXT = "sexual_context"
    UNCERTAIN = "uncertain"


class AnalysisStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AnalysisStage(str, Enum):
    PREFLIGHT = "preflight"
    TEXT_EVIDENCE = "text_evidence"
    COARSE_SAMPLING = "coarse_sampling"
    PREFILTER = "prefilter"
    CANDIDATE_PLANNING = "candidate_planning"
    VLM_REVIEW = "vlm_review"
    FUSION = "fusion"
    PERSISTENCE = "persistence"


class AnalysisProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: AnalysisStage
    overall_percent: int = Field(ge=0, le=100)
    stage_percent: int = Field(default=0, ge=0, le=100)
    message: str
    completed_units: int = Field(default=0, ge=0)
    total_units: int = Field(default=0, ge=0)
    candidate_count: int = Field(default=0, ge=0)
    failed_units: int = Field(default=0, ge=0)
    repaired_units: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    resumed_units: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    eta_seconds: float | None = Field(default=None, ge=0.0)
    device: str = ""


class AnalysisSettings(BaseModel):
    """Versioned settings which form part of an analysis cache key."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    settings_version: int = Field(default=2, ge=2)
    analysis_mode: AnalysisMode = AnalysisMode.BALANCED
    sampling_profile_revision: int = Field(default=1, ge=1)
    provider: Literal["local_qwen"] = "local_qwen"
    model_id: str = DEFAULT_QWEN_MODEL_ID
    model_revision: str = DEFAULT_QWEN_MODEL_REVISION
    quantization_mode: Literal["auto", "4bit", "none"] = "auto"
    whisper_model_id: str = "small"
    use_gpu: bool = True
    # Explicit values are advanced overrides. Normal app runs use the selected
    # versioned mode profile so old 1 FPS settings cannot accidentally make a
    # two-hour movie generate thousands of VLM inputs.
    sample_rate_fps: float | None = Field(default=None, gt=0.0, le=5.0)
    dense_sample_rate_fps: float | None = Field(default=None, gt=0.0, le=5.0)
    scene_threshold: float = Field(default=0.35, ge=0.05, le=0.95)
    batch_size: int = Field(default=4, ge=1, le=8)
    prefilter_model_id: str = DEFAULT_PREFILTER_MODEL_ID
    prefilter_model_revision: str = DEFAULT_PREFILTER_MODEL_REVISION
    prefilter_batch_size: int = Field(default=32, ge=1, le=256)
    prefilter_candidate_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    prefilter_strong_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    candidate_gap_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    candidate_padding_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    max_candidate_window_seconds: float = Field(default=30.0, gt=1.0, le=300.0)
    visual_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    text_confidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    merge_gap_seconds: float = Field(default=1.5, ge=0.0, le=30.0)
    context_padding_seconds: float = Field(default=0.75, ge=0.0, le=30.0)
    max_new_tokens: int = Field(default=192, ge=96, le=384)
    repair_max_new_tokens: int = Field(default=128, ge=64, le=192)
    batch_timeout_seconds: float = Field(default=75.0, ge=5.0, le=600.0)
    prompt_schema_revision: int = Field(default=2, ge=1)

    @field_validator(
        "model_id",
        "model_revision",
        "prefilter_model_id",
        "prefilter_model_revision",
        "whisper_model_id",
    )
    @classmethod
    def non_empty_identifier(cls, value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("model identifiers cannot be empty")
        return normalized

    @model_validator(mode="after")
    def valid_prefilter_thresholds(self):
        if self.prefilter_strong_threshold < self.prefilter_candidate_threshold:
            raise ValueError(
                "prefilter strong threshold cannot be below the candidate threshold"
            )
        return self

    @property
    def resolved_coarse_sample_rate_fps(self) -> float:
        if self.sample_rate_fps is not None:
            return self.sample_rate_fps
        return {
            AnalysisMode.FAST: 0.1,
            AnalysisMode.BALANCED: 0.2,
            AnalysisMode.THOROUGH: 0.2,
        }[self.analysis_mode]

    @property
    def resolved_dense_sample_rate_fps(self) -> float:
        if self.dense_sample_rate_fps is not None:
            return self.dense_sample_rate_fps
        return {
            AnalysisMode.FAST: 0.5,
            AnalysisMode.BALANCED: 1.0,
            AnalysisMode.THOROUGH: 2.0,
        }[self.analysis_mode]

    @property
    def resolved_prefilter_threshold(self) -> float:
        if self.analysis_mode == AnalysisMode.FAST:
            return self.prefilter_strong_threshold
        return self.prefilter_candidate_threshold


class AnalysisRunRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    video_path: Path
    selected_subtitle: dict[str, Any] | None = None
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    force_reanalysis: bool = False


class MediaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float = Field(gt=0.0)
    fps: float = Field(ge=0.0)
    format_name: str = ""
    streams: list[dict[str, Any]] = Field(default_factory=list)


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_fingerprint: str
    text_source_fingerprint: str = "audio-fallback:v1"
    media: MediaSummary
    cache_key: str


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    text: str
    source: Literal["subtitle", "whisper"]

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("transcript segment end must be after start")
        self.text = self.text.strip()
        return self


class TextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    category: NSFWCategory
    confidence: float = Field(ge=0.0, le=1.0)
    excerpt: str = Field(default="", max_length=240)
    source: Literal["subtitle", "whisper"]

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("text evidence end must be after start")
        return self


class TextEvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    evidence: list[TextEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SampledFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_seconds: float = Field(ge=0.0)
    path: Path
    source: Literal["interval", "scene", "refined"]


class PrefilterFrameScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame: SampledFrame
    nsfw_probability: float = Field(ge=0.0, le=1.0)
    conservatively_included: bool = False

    @field_validator("nsfw_probability")
    @classmethod
    def finite_probability(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("prefilter probability must be finite")
        return value


class CandidateWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    peak_probability: float = Field(ge=0.0, le=1.0)
    evidence_timestamps: list[float] = Field(default_factory=list)
    trigger: Literal["visual", "text", "visual_and_text"] = "visual"

    @model_validator(mode="after")
    def valid_window(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("candidate window end must be after start")
        self.evidence_timestamps = sorted(set(self.evidence_timestamps))
        return self


class VisualBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    frames: list[SampledFrame] = Field(min_length=1)
    candidate_window_id: str = ""
    contact_sheet_path: Path | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds < self.start_seconds:
            raise ValueError("visual batch end cannot precede start")
        return self


class VLMReviewItem(BaseModel):
    """Strict contract accepted from a VLM provider."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal[
        "nudity",
        "sexual_activity",
        "sexual_context",
        "uncertain",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    evidence_timestamps: list[float] = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=240)
    needs_review: StrictBool

    @field_validator("evidence_timestamps")
    @classmethod
    def valid_evidence_timestamps(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("evidence timestamps must be finite and non-negative")
        return sorted(set(values))

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason cannot be blank")
        return normalized

    @field_validator("needs_review")
    @classmethod
    def review_is_required(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("needs_review must be true")
        return value

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("VLM suggestion end must be after start")
        if any(
            timestamp < self.start_seconds - 0.5
            or timestamp > self.end_seconds + 0.5
            for timestamp in self.evidence_timestamps
        ):
            raise ValueError("evidence timestamps must fall inside the suggested interval")
        return self


class VLMReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    suggestions: list[VLMReviewItem] = Field(max_length=128)


class VLMWireSuggestion(BaseModel):
    """Compact grammar-constrained JSON emitted directly by the local VLM."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: Literal[
        "nudity",
        "sexual_activity",
        "sexual_context",
        "uncertain",
    ]
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    first_frame: StrictInt = Field(ge=1, le=8)
    last_frame: StrictInt = Field(ge=1, le=8)
    evidence_frames: list[StrictInt] = Field(min_length=1, max_length=8)
    reason: str = Field(min_length=1, max_length=96)

    @field_validator("confidence")
    @classmethod
    def finite_confidence(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("reason")
    @classmethod
    def compact_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("reason cannot be blank")
        return normalized

    @model_validator(mode="after")
    def valid_frame_range(self):
        if self.last_frame < self.first_frame:
            raise ValueError("last_frame cannot precede first_frame")
        if any(
            frame < self.first_frame or frame > self.last_frame
            for frame in self.evidence_frames
        ):
            raise ValueError("evidence frames must fall inside the suggested range")
        self.evidence_frames = sorted(set(self.evidence_frames))
        return self


class VLMWireResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    suggestions: list[VLMWireSuggestion] = Field(max_length=4)


class ProviderDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_mode: Literal["cuda", "hybrid", "cpu", "unavailable"] = "unavailable"
    device_name: str = ""
    precision: str = ""
    quantization: str = ""
    gpu_layer_count: int = Field(default=0, ge=0)
    cpu_layer_count: int = Field(default=0, ge=0)


class VLMReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: VLMReviewResponse
    raw_output: str = Field(default="", max_length=16000)
    repaired_output: str = Field(default="", max_length=16000)
    repaired: bool = False
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    stop_reason: str = "completed"
    diagnostics: ProviderDiagnostics | None = None


class VisualEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str
    category: NSFWCategory
    confidence: float = Field(ge=0.0, le=1.0)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    evidence_timestamps: list[float] = Field(default_factory=list)
    reason: str = Field(max_length=240)
    needs_review: bool = True

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("visual evidence end must be after start")
        return self


class FinalSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    category: NSFWCategory
    visual_confidence: float = Field(ge=0.0, le=1.0)
    text_confidence: float = Field(ge=0.0, le=1.0)
    final_confidence: float = Field(ge=0.0, le=1.0)
    evidence_timestamps: list[float] = Field(default_factory=list)
    reason: str = Field(max_length=320)
    needs_review: bool = True
    review_state: Literal["pending", "accepted", "rejected"] = "pending"

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("final suggestion end must be after start")
        self.needs_review = True
        self.evidence_timestamps = sorted(set(self.evidence_timestamps))
        return self


class AnalysisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    video_fingerprint: str
    text_source_fingerprint: str = "audio-fallback:v1"
    model_id: str
    model_revision: str
    settings_version: int
    settings: dict[str, Any]
    status: AnalysisStatus
    media: MediaSummary | None = None
    text_evidence: list[TextEvidence] = Field(default_factory=list)
    visual_evidence: list[VisualEvidence] = Field(default_factory=list)
    candidate_windows: list[CandidateWindow] = Field(default_factory=list)
    suggestions: list[FinalSuggestion] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    provider_diagnostics: ProviderDiagnostics | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime | None = None
