from __future__ import annotations

import csv
import io
import json
import math
import os
from collections import defaultdict
from collections.abc import Sequence
from itertools import product
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.time_utils import seconds_to_ffmpeg_time, timecode_to_seconds
from services.analysis.preprocessing_contracts import PreprocessingConfig

SCORE_SCHEMA_VERSION = 1
GROUND_TRUTH_SCHEMA_VERSION = 1
EVALUATION_REPORT_SCHEMA_VERSION = 1
MICROSECONDS_PER_SECOND = 1_000_000


class Stage1EvaluationDataError(ValueError):
    """An evaluation artifact is missing, malformed, or incompatible."""


class Stage1ScoreVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1)
    duration_us: int = Field(gt=0)
    fingerprint: str | None = None

    @field_validator("filename")
    @classmethod
    def normalize_filename(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("video filename cannot be blank")
        return normalized

    @field_validator("fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        prefix = "sha256:"
        digest = normalized.removeprefix(prefix)
        if not normalized.startswith(prefix) or len(digest) != 64:
            raise ValueError("video fingerprint must be sha256:<64 lowercase hex characters>")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("video fingerprint must be sha256:<64 lowercase hex characters>")
        return normalized


class Stage1ScoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    runtime: str = Field(min_length=1)
    providers: tuple[str, ...] = Field(min_length=1)

    @field_validator("repo_id", "revision", "runtime")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model provenance values cannot be blank")
        return normalized

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("model SHA-256 must contain exactly 64 lowercase hex characters")
        return normalized


class Stage1ScoreSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str = Field(min_length=1)
    timestamp_us: int = Field(ge=0)
    nsfl: float = Field(ge=0.0, le=1.0)
    nsfw: float = Field(ge=0.0, le=1.0)
    sfw: float = Field(ge=0.0, le=1.0)
    selected_label: Literal["NSFL", "NSFW", "SFW"]
    sample_reasons: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_probabilities_and_identity(self) -> Stage1ScoreSample:
        if not self.sample_id.strip():
            raise ValueError("sample ID cannot be blank")
        probabilities = (self.nsfl, self.nsfw, self.sfw)
        if not all(math.isfinite(value) for value in probabilities):
            raise ValueError("Stage-1 score probabilities must be finite")
        if not math.isclose(sum(probabilities), 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise ValueError("Stage-1 score probabilities must sum to one")
        normalized_reasons = tuple(reason.strip() for reason in self.sample_reasons)
        if any(not reason for reason in normalized_reasons):
            raise ValueError("sample reasons cannot be blank")
        object.__setattr__(self, "sample_id", self.sample_id.strip())
        object.__setattr__(self, "sample_reasons", normalized_reasons)
        return self


class Stage1ScoreArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = SCORE_SCHEMA_VERSION
    generated_at_utc: str = Field(min_length=1)
    video: Stage1ScoreVideo
    model: Stage1ScoreModel
    preprocessing: PreprocessingConfig
    samples: tuple[Stage1ScoreSample, ...]

    @model_validator(mode="after")
    def valid_sample_sequence(self) -> Stage1ScoreArtifact:
        timestamps = [sample.timestamp_us for sample in self.samples]
        if timestamps != sorted(timestamps):
            raise ValueError("Stage-1 score samples must be sorted by timestamp")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("Stage-1 score sample timestamps must be unique")
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Stage-1 score sample IDs must be unique")
        if any(timestamp > self.video.duration_us for timestamp in timestamps):
            raise ValueError("Stage-1 score sample timestamp exceeds movie duration")
        return self


class GroundTruthVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def nonblank_filename(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("ground-truth video filename cannot be blank")
        return normalized


class GroundTruthInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: str = Field(min_length=1)
    end: str = Field(min_length=1)
    category: str | None = None
    severity: str | None = None
    notes: str | None = None

    @field_validator("category", "severity", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def valid_time_range(self) -> GroundTruthInterval:
        start_us = _timecode_to_microseconds(self.start, "interval start")
        end_us = _timecode_to_microseconds(self.end, "interval end")
        if end_us <= start_us:
            raise ValueError("ground-truth interval end must be after start")
        return self

    @property
    def start_us(self) -> int:
        return _timecode_to_microseconds(self.start, "interval start")

    @property
    def end_us(self) -> int:
        return _timecode_to_microseconds(self.end, "interval end")


class GroundTruthArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = GROUND_TRUTH_SCHEMA_VERSION
    video: GroundTruthVideo
    intervals: tuple[GroundTruthInterval, ...]


class ThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nsfw_threshold: float = Field(ge=0.0, le=1.0)
    nsfl_threshold: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def finite_thresholds(self) -> ThresholdPolicy:
        if not math.isfinite(self.nsfw_threshold) or not math.isfinite(
            self.nsfl_threshold
        ):
            raise ValueError("thresholds must be finite")
        return self


class Stage1EvaluationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nsfw_thresholds: tuple[float, ...] = Field(min_length=1)
    nsfl_thresholds: tuple[float, ...] = Field(min_length=1)
    tolerance_seconds: float = Field(default=5.0, ge=0.0)
    window_context_seconds: float = Field(default=5.0, ge=0.0)
    window_merge_gap_seconds: float = Field(default=0.0, ge=0.0)
    minimum_recall: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalized_configuration(self) -> Stage1EvaluationConfiguration:
        for name, values in (
            ("NSFW", self.nsfw_thresholds),
            ("NSFL", self.nsfl_thresholds),
        ):
            if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
                raise ValueError(f"{name} thresholds must be finite values within [0, 1]")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} threshold list must not contain duplicates")
        for label, value in (
            ("tolerance", self.tolerance_seconds),
            ("window context", self.window_context_seconds),
            ("window merge gap", self.window_merge_gap_seconds),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        return self


class RecallBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    total_intervals: int = Field(ge=1)
    detected_intervals: int = Field(ge=0)
    missed_intervals: int = Field(ge=0)
    interval_recall: float = Field(ge=0.0, le=1.0)
    tolerant_detected_intervals: int = Field(ge=0)
    tolerant_missed_intervals: int = Field(ge=0)
    tolerant_interval_recall: float = Field(ge=0.0, le=1.0)


class MissedIntervalDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interval_index: int = Field(ge=0)
    start: str
    end: str
    category: str | None
    severity: str | None
    notes: str | None
    tolerant_detected: bool
    max_nsfw_probability_exact: float | None = Field(default=None, ge=0.0, le=1.0)
    max_nsfl_probability_exact: float | None = Field(default=None, ge=0.0, le=1.0)
    max_nsfw_probability_tolerant: float | None = Field(default=None, ge=0.0, le=1.0)
    max_nsfl_probability_tolerant: float | None = Field(default=None, ge=0.0, le=1.0)
    nearest_representative_timestamp_us: int | None = Field(default=None, ge=0)
    nearest_representative_distance_us: int | None = Field(default=None, ge=0)


class EstimatedVLMWorkload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_candidate_samples: int = Field(ge=0)
    merged_candidate_windows: int = Field(ge=0)
    total_candidate_window_seconds: float = Field(ge=0.0)
    movie_fraction: float = Field(ge=0.0, le=1.0)
    average_window_seconds: float = Field(ge=0.0)
    maximum_window_seconds: float = Field(ge=0.0)


class PolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: ThresholdPolicy
    total_intervals: int = Field(ge=0)
    detected_intervals: int = Field(ge=0)
    missed_intervals: int = Field(ge=0)
    interval_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    tolerant_detected_intervals: int = Field(ge=0)
    tolerant_missed_intervals: int = Field(ge=0)
    tolerant_interval_recall_5s: float | None = Field(default=None, ge=0.0, le=1.0)
    configured_tolerance_seconds: float = Field(ge=0.0)
    total_representative_samples: int = Field(ge=0)
    candidate_samples: int = Field(ge=0)
    candidate_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_samples_inside_gt: int | None = Field(default=None, ge=0)
    candidate_samples_outside_gt: int | None = Field(default=None, ge=0)
    frame_candidate_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    category_recall: tuple[RecallBreakdown, ...]
    severity_recall: tuple[RecallBreakdown, ...]
    missed_interval_details: tuple[MissedIntervalDetail, ...]
    estimated_vlm_workload: EstimatedVLMWorkload


class PolicySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nsfw_threshold: float
    nsfl_threshold: float
    interval_recall: float
    tolerant_interval_recall: float
    candidate_sample_rate: float | None
    estimated_vlm_movie_fraction: float
    estimated_vlm_windows: int


class GroundTruthSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    annotation_source: Literal["stage1_ground_truth", "cut_json"]
    total_intervals: int = Field(ge=0)
    categories: tuple[str, ...]
    severities: tuple[str, ...]
    category_metrics_available: bool
    severity_metrics_available: bool
    overlapping_interval_pairs: int = Field(ge=0)
    overlap_handling: str


class Stage1EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = EVALUATION_REPORT_SCHEMA_VERSION
    scores_schema_version: int
    ground_truth_schema_version: int
    video: Stage1ScoreVideo
    model: Stage1ScoreModel
    preprocessing: PreprocessingConfig
    configuration: Stage1EvaluationConfiguration
    ground_truth: GroundTruthSummary
    policies: tuple[PolicyEvaluation, ...]
    high_recall_policies: tuple[PolicySummary, ...]
    metric_definitions: dict[str, str]


def load_score_artifact(path: str | Path) -> Stage1ScoreArtifact:
    resolved_path = Path(path)
    try:
        return Stage1ScoreArtifact.model_validate_json(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1EvaluationDataError(
            f"Stage-1 score artifact does not exist: {resolved_path}"
        ) from exc
    except OSError as exc:
        raise Stage1EvaluationDataError(
            f"Unable to read Stage-1 score artifact: {resolved_path}"
        ) from exc
    except ValidationError as exc:
        raise Stage1EvaluationDataError(
            f"Invalid Stage-1 score artifact '{resolved_path.name}': {exc}"
        ) from exc


def load_ground_truth_artifact(
    path: str | Path,
    *,
    duration_us: int,
    default_video_filename: str,
) -> tuple[GroundTruthArtifact, Literal["stage1_ground_truth", "cut_json"]]:
    resolved_path = Path(path)
    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Stage1EvaluationDataError(
            f"Ground-truth artifact does not exist: {resolved_path}"
        ) from exc
    except OSError as exc:
        raise Stage1EvaluationDataError(
            f"Unable to read ground-truth artifact: {resolved_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise Stage1EvaluationDataError(
            f"Ground-truth artifact is not valid JSON at line {exc.lineno}, column {exc.colno}."
        ) from exc

    if not isinstance(payload, dict):
        raise Stage1EvaluationDataError("Ground-truth JSON must be an object.")
    source: Literal["stage1_ground_truth", "cut_json"]
    try:
        if "intervals" in payload:
            artifact = GroundTruthArtifact.model_validate(payload)
            source = "stage1_ground_truth"
        elif "cuts" in payload:
            artifact = _ground_truth_from_cut_payload(payload, default_video_filename)
            source = "cut_json"
        else:
            raise Stage1EvaluationDataError(
                "Ground-truth JSON must contain either an intervals array or a cuts array."
            )
    except ValidationError as exc:
        raise Stage1EvaluationDataError(f"Invalid ground-truth artifact: {exc}") from exc

    _validate_ground_truth_duration(artifact, duration_us)
    return artifact, source


def write_json_artifact(model: BaseModel, path: str | Path) -> Path:
    output_path = Path(path).expanduser().resolve()
    _atomic_write_text(output_path, model.model_dump_json(indent=2))
    return output_path


def create_ground_truth_template(scores: Stage1ScoreArtifact) -> GroundTruthArtifact:
    return GroundTruthArtifact(
        video=GroundTruthVideo(filename=scores.video.filename),
        intervals=(),
    )


def evaluate_thresholds(
    scores: Stage1ScoreArtifact,
    ground_truth: GroundTruthArtifact,
    configuration: Stage1EvaluationConfiguration,
    *,
    annotation_source: Literal["stage1_ground_truth", "cut_json"] = (
        "stage1_ground_truth"
    ),
) -> Stage1EvaluationReport:
    if scores.video.filename.casefold() != ground_truth.video.filename.casefold():
        raise Stage1EvaluationDataError(
            "Score and ground-truth video filenames differ: "
            f"'{scores.video.filename}' != '{ground_truth.video.filename}'."
        )
    _validate_ground_truth_duration(ground_truth, scores.video.duration_us)
    intervals = sorted(
        ground_truth.intervals,
        key=lambda interval: (
            interval.start_us,
            interval.end_us,
            interval.category or "",
            interval.severity or "",
        ),
    )
    timestamps = np.asarray(
        [sample.timestamp_us for sample in scores.samples],
        dtype=np.int64,
    )
    nsfw_probabilities = np.asarray(
        [sample.nsfw for sample in scores.samples],
        dtype=np.float64,
    )
    nsfl_probabilities = np.asarray(
        [sample.nsfl for sample in scores.samples],
        dtype=np.float64,
    )

    policy_results = tuple(
        _evaluate_policy(
            policy=ThresholdPolicy(
                nsfw_threshold=nsfw_threshold,
                nsfl_threshold=nsfl_threshold,
            ),
            timestamps=timestamps,
            nsfw_probabilities=nsfw_probabilities,
            nsfl_probabilities=nsfl_probabilities,
            intervals=intervals,
            duration_us=scores.video.duration_us,
            configuration=configuration,
        )
        for nsfw_threshold, nsfl_threshold in product(
            configuration.nsfw_thresholds,
            configuration.nsfl_thresholds,
        )
    )
    return Stage1EvaluationReport(
        scores_schema_version=scores.schema_version,
        ground_truth_schema_version=ground_truth.schema_version,
        video=scores.video,
        model=scores.model,
        preprocessing=scores.preprocessing,
        configuration=configuration,
        ground_truth=_ground_truth_summary(intervals, annotation_source),
        policies=policy_results,
        high_recall_policies=_high_recall_view(policy_results, configuration.minimum_recall),
        metric_definitions={
            "interval_recall": (
                "Fraction of annotated intervals containing at least one candidate representative; interval boundaries are inclusive."
            ),
            "tolerant_interval_recall_5s": (
                "Interval recall after expanding each annotation by configured_tolerance_seconds (5 seconds by evaluation default) and clamping to movie bounds."
            ),
            "candidate_sample_rate": (
                "Candidate representative samples divided by all representative samples."
            ),
            "frame_candidate_precision": (
                "Candidate representatives inside the union of exact ground-truth intervals divided by all candidate representatives; this is frame-level precision only."
            ),
            "estimated_vlm_workload": (
                "Evaluation-only union of candidate timestamp windows after configured context padding and merge-gap handling; it is not actual VLM cost."
            ),
        },
    )


def write_policy_csv(report: Stage1EvaluationReport, path: str | Path) -> Path:
    output = io.StringIO(newline="")
    fieldnames = (
        "nsfw_threshold",
        "nsfl_threshold",
        "interval_recall",
        "tolerant_interval_recall",
        "missed_intervals",
        "candidate_samples",
        "candidate_sample_rate",
        "frame_candidate_precision",
        "estimated_vlm_windows",
        "estimated_vlm_seconds",
        "estimated_vlm_movie_fraction",
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for result in report.policies:
        writer.writerow(
            {
                "nsfw_threshold": result.policy.nsfw_threshold,
                "nsfl_threshold": result.policy.nsfl_threshold,
                "interval_recall": result.interval_recall,
                "tolerant_interval_recall": result.tolerant_interval_recall_5s,
                "missed_intervals": result.missed_intervals,
                "candidate_samples": result.candidate_samples,
                "candidate_sample_rate": result.candidate_sample_rate,
                "frame_candidate_precision": result.frame_candidate_precision,
                "estimated_vlm_windows": (
                    result.estimated_vlm_workload.merged_candidate_windows
                ),
                "estimated_vlm_seconds": (
                    result.estimated_vlm_workload.total_candidate_window_seconds
                ),
                "estimated_vlm_movie_fraction": (
                    result.estimated_vlm_workload.movie_fraction
                ),
            }
        )
    output_path = Path(path).expanduser().resolve()
    _atomic_write_text(output_path, output.getvalue())
    return output_path


def _evaluate_policy(
    *,
    policy: ThresholdPolicy,
    timestamps: np.ndarray,
    nsfw_probabilities: np.ndarray,
    nsfl_probabilities: np.ndarray,
    intervals: Sequence[GroundTruthInterval],
    duration_us: int,
    configuration: Stage1EvaluationConfiguration,
) -> PolicyEvaluation:
    candidate_mask = (nsfw_probabilities >= policy.nsfw_threshold) | (
        nsfl_probabilities >= policy.nsfl_threshold
    )
    candidate_count = int(candidate_mask.sum())
    tolerance_us = round(configuration.tolerance_seconds * MICROSECONDS_PER_SECOND)
    exact_detections: list[bool] = []
    tolerant_detections: list[bool] = []
    missed_details: list[MissedIntervalDetail] = []
    inside_gt_mask = np.zeros(timestamps.shape, dtype=bool)

    for interval_index, interval in enumerate(intervals):
        exact_mask = (timestamps >= interval.start_us) & (timestamps <= interval.end_us)
        tolerant_start = max(0, interval.start_us - tolerance_us)
        tolerant_end = min(duration_us, interval.end_us + tolerance_us)
        tolerant_mask = (timestamps >= tolerant_start) & (timestamps <= tolerant_end)
        exact_detected = bool(np.any(candidate_mask & exact_mask))
        tolerant_detected = bool(np.any(candidate_mask & tolerant_mask))
        exact_detections.append(exact_detected)
        tolerant_detections.append(tolerant_detected)
        inside_gt_mask |= exact_mask
        if not exact_detected:
            nearest_timestamp, nearest_distance = _nearest_representative(
                timestamps,
                interval.start_us,
                interval.end_us,
            )
            missed_details.append(
                MissedIntervalDetail(
                    interval_index=interval_index,
                    start=interval.start,
                    end=interval.end,
                    category=interval.category,
                    severity=interval.severity,
                    notes=interval.notes,
                    tolerant_detected=tolerant_detected,
                    max_nsfw_probability_exact=_masked_max(nsfw_probabilities, exact_mask),
                    max_nsfl_probability_exact=_masked_max(nsfl_probabilities, exact_mask),
                    max_nsfw_probability_tolerant=_masked_max(
                        nsfw_probabilities,
                        tolerant_mask,
                    ),
                    max_nsfl_probability_tolerant=_masked_max(
                        nsfl_probabilities,
                        tolerant_mask,
                    ),
                    nearest_representative_timestamp_us=nearest_timestamp,
                    nearest_representative_distance_us=nearest_distance,
                )
            )

    total_intervals = len(intervals)
    detected_intervals = sum(exact_detections)
    tolerant_detected_intervals = sum(tolerant_detections)
    inside_candidates = int(np.sum(candidate_mask & inside_gt_mask))
    outside_candidates = candidate_count - inside_candidates
    candidate_timestamps = timestamps[candidate_mask]
    return PolicyEvaluation(
        policy=policy,
        total_intervals=total_intervals,
        detected_intervals=detected_intervals,
        missed_intervals=total_intervals - detected_intervals,
        interval_recall=(
            detected_intervals / total_intervals if total_intervals else None
        ),
        tolerant_detected_intervals=tolerant_detected_intervals,
        tolerant_missed_intervals=total_intervals - tolerant_detected_intervals,
        tolerant_interval_recall_5s=(
            tolerant_detected_intervals / total_intervals if total_intervals else None
        ),
        configured_tolerance_seconds=configuration.tolerance_seconds,
        total_representative_samples=len(timestamps),
        candidate_samples=candidate_count,
        candidate_sample_rate=(candidate_count / len(timestamps) if len(timestamps) else None),
        candidate_samples_inside_gt=(inside_candidates if total_intervals else None),
        candidate_samples_outside_gt=(outside_candidates if total_intervals else None),
        frame_candidate_precision=(
            inside_candidates / candidate_count
            if total_intervals and candidate_count
            else None
        ),
        category_recall=_recall_breakdowns(
            intervals,
            exact_detections,
            tolerant_detections,
            attribute="category",
        ),
        severity_recall=_recall_breakdowns(
            intervals,
            exact_detections,
            tolerant_detections,
            attribute="severity",
        ),
        missed_interval_details=tuple(missed_details),
        estimated_vlm_workload=_estimated_vlm_workload(
            candidate_timestamps,
            duration_us=duration_us,
            context_seconds=configuration.window_context_seconds,
            merge_gap_seconds=configuration.window_merge_gap_seconds,
        ),
    )


def _recall_breakdowns(
    intervals: Sequence[GroundTruthInterval],
    exact_detections: Sequence[bool],
    tolerant_detections: Sequence[bool],
    *,
    attribute: Literal["category", "severity"],
) -> tuple[RecallBreakdown, ...]:
    grouped: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for interval, exact, tolerant in zip(
        intervals,
        exact_detections,
        tolerant_detections,
        strict=True,
    ):
        value = getattr(interval, attribute)
        if value is not None:
            grouped[value].append((exact, tolerant))
    return tuple(
        RecallBreakdown(
            value=value,
            total_intervals=len(detections),
            detected_intervals=sum(exact for exact, _ in detections),
            missed_intervals=len(detections) - sum(exact for exact, _ in detections),
            interval_recall=sum(exact for exact, _ in detections) / len(detections),
            tolerant_detected_intervals=sum(tolerant for _, tolerant in detections),
            tolerant_missed_intervals=(
                len(detections) - sum(tolerant for _, tolerant in detections)
            ),
            tolerant_interval_recall=(
                sum(tolerant for _, tolerant in detections) / len(detections)
            ),
        )
        for value, detections in sorted(grouped.items())
    )


def _estimated_vlm_workload(
    candidate_timestamps: np.ndarray,
    *,
    duration_us: int,
    context_seconds: float,
    merge_gap_seconds: float,
) -> EstimatedVLMWorkload:
    context_us = round(context_seconds * MICROSECONDS_PER_SECOND)
    merge_gap_us = round(merge_gap_seconds * MICROSECONDS_PER_SECOND)
    windows = [
        (max(0, int(timestamp) - context_us), min(duration_us, int(timestamp) + context_us))
        for timestamp in candidate_timestamps
    ]
    merged: list[list[int]] = []
    for start_us, end_us in windows:
        if not merged or start_us > merged[-1][1] + merge_gap_us:
            merged.append([start_us, end_us])
        else:
            merged[-1][1] = max(merged[-1][1], end_us)
    durations_us = [end_us - start_us for start_us, end_us in merged]
    total_us = sum(durations_us)
    return EstimatedVLMWorkload(
        raw_candidate_samples=len(candidate_timestamps),
        merged_candidate_windows=len(merged),
        total_candidate_window_seconds=total_us / MICROSECONDS_PER_SECOND,
        movie_fraction=total_us / duration_us,
        average_window_seconds=(
            total_us / len(merged) / MICROSECONDS_PER_SECOND if merged else 0.0
        ),
        maximum_window_seconds=(
            max(durations_us) / MICROSECONDS_PER_SECOND if durations_us else 0.0
        ),
    )


def _high_recall_view(
    policy_results: Sequence[PolicyEvaluation],
    minimum_recall: float | None,
) -> tuple[PolicySummary, ...]:
    eligible = [
        result
        for result in policy_results
        if result.interval_recall is not None
        and (minimum_recall is None or result.interval_recall >= minimum_recall)
    ]
    eligible.sort(
        key=lambda result: (
            -float(result.interval_recall),
            result.estimated_vlm_workload.movie_fraction,
            result.candidate_sample_rate
            if result.candidate_sample_rate is not None
            else math.inf,
            result.policy.nsfw_threshold,
            result.policy.nsfl_threshold,
        )
    )
    return tuple(
        PolicySummary(
            nsfw_threshold=result.policy.nsfw_threshold,
            nsfl_threshold=result.policy.nsfl_threshold,
            interval_recall=float(result.interval_recall),
            tolerant_interval_recall=float(result.tolerant_interval_recall_5s),
            candidate_sample_rate=result.candidate_sample_rate,
            estimated_vlm_movie_fraction=(
                result.estimated_vlm_workload.movie_fraction
            ),
            estimated_vlm_windows=(
                result.estimated_vlm_workload.merged_candidate_windows
            ),
        )
        for result in eligible
    )


def _ground_truth_summary(
    intervals: Sequence[GroundTruthInterval],
    annotation_source: Literal["stage1_ground_truth", "cut_json"],
) -> GroundTruthSummary:
    categories = tuple(sorted({item.category for item in intervals if item.category}))
    severities = tuple(sorted({item.severity for item in intervals if item.severity}))
    overlap_pairs = sum(
        1
        for index, left in enumerate(intervals)
        for right in intervals[index + 1 :]
        if right.start_us <= left.end_us and left.start_us <= right.end_us
    )
    return GroundTruthSummary(
        annotation_source=annotation_source,
        total_intervals=len(intervals),
        categories=categories,
        severities=severities,
        category_metrics_available=bool(categories),
        severity_metrics_available=bool(severities),
        overlapping_interval_pairs=overlap_pairs,
        overlap_handling=(
            "Annotations remain distinct for interval/category/severity recall; their union is used only for frame-level inside/outside classification."
        ),
    )


def _masked_max(values: np.ndarray, mask: np.ndarray) -> float | None:
    return float(values[mask].max()) if np.any(mask) else None


def _nearest_representative(
    timestamps: np.ndarray,
    start_us: int,
    end_us: int,
) -> tuple[int | None, int | None]:
    if timestamps.size == 0:
        return None, None
    distances = np.where(
        timestamps < start_us,
        start_us - timestamps,
        np.where(timestamps > end_us, timestamps - end_us, 0),
    )
    nearest_index = int(np.argmin(distances))
    return int(timestamps[nearest_index]), int(distances[nearest_index])


def _ground_truth_from_cut_payload(
    payload: dict,
    default_video_filename: str,
) -> GroundTruthArtifact:
    raw_cuts = payload.get("cuts")
    if not isinstance(raw_cuts, list):
        raise Stage1EvaluationDataError("Cut JSON must contain a cuts array.")
    raw_video = payload.get("video")
    filename = default_video_filename
    if isinstance(raw_video, dict) and raw_video.get("filename"):
        filename = str(raw_video["filename"])
    intervals = []
    for index, cut in enumerate(raw_cuts):
        if not isinstance(cut, dict):
            raise Stage1EvaluationDataError(f"Cut {index} must be an object.")
        if "start" not in cut or "end" not in cut:
            raise Stage1EvaluationDataError(f"Cut {index} must contain start and end.")
        start_seconds = _cut_time_to_seconds(cut["start"], f"cut {index} start")
        end_seconds = _cut_time_to_seconds(cut["end"], f"cut {index} end")
        intervals.append(
            GroundTruthInterval(
                start=seconds_to_ffmpeg_time(start_seconds),
                end=seconds_to_ffmpeg_time(end_seconds),
            )
        )
    return GroundTruthArtifact(
        video=GroundTruthVideo(filename=filename),
        intervals=tuple(intervals),
    )


def _cut_time_to_seconds(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise Stage1EvaluationDataError(f"{label} must be a number or timecode.")
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str) and ":" in value:
        try:
            seconds = timecode_to_seconds(value)
        except ValueError as exc:
            raise Stage1EvaluationDataError(f"{label} has invalid timecode syntax.") from exc
    else:
        raise Stage1EvaluationDataError(f"{label} must be a number or timecode.")
    if not math.isfinite(seconds) or seconds < 0.0:
        raise Stage1EvaluationDataError(f"{label} must be finite and non-negative.")
    return seconds


def _validate_ground_truth_duration(
    ground_truth: GroundTruthArtifact,
    duration_us: int,
) -> None:
    for index, interval in enumerate(ground_truth.intervals):
        if interval.end_us > duration_us:
            raise Stage1EvaluationDataError(
                f"Ground-truth interval {index} ends after the movie duration "
                f"({interval.end} > {seconds_to_ffmpeg_time(duration_us / MICROSECONDS_PER_SECOND)})."
            )


def _timecode_to_microseconds(value: str, label: str) -> int:
    try:
        seconds = timecode_to_seconds(value)
    except ValueError as exc:
        raise ValueError(f"{label} has invalid timecode syntax: {value!r}") from exc
    if seconds < 0.0:
        raise ValueError(f"{label} cannot be negative")
    return round(seconds * MICROSECONDS_PER_SECOND)


def _atomic_write_text(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
