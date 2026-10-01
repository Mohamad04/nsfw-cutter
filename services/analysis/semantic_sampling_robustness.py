"""Offline phase-offset robustness checks for sparse TinyCLIP sampling.

Only persisted score and annotation artifacts are consumed.  No media is
opened and no inference runtime is imported.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from itertools import product
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from services.analysis.semantic_sampling_ablation import (
    FULL_ENCODER_SECONDS,
    SamplingPolicySummary,
    _evaluate_policy_grid,
    _least_expanded_workload_grid,
    _policy_key,
    _summary,
)
from services.analysis.stage1_evaluation import GroundTruthArtifact, Stage1ScoreArtifact
from services.analysis.stage1_union_evaluation import (
    MICROSECONDS_PER_SECOND,
    OfflinePromptBank,
    SemanticScoreArtifact,
    Stage1UnionEvaluationConfiguration,
    Stage1UnionEvaluationError,
    _prompt_score_arrays,
    _strategy_scores,
    align_artifacts,
)

SEMANTIC_SAMPLING_ROBUSTNESS_SCHEMA_VERSION = 1
DEFAULT_ROBUSTNESS_GAPS_SECONDS = (3.0, 5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 30.0)
DEFAULT_PHASE_STEP_SECONDS = 1.0
TARGET_CATEGORIES = {"drugs", "weapons"}


class SemanticSamplingRobustnessError(Stage1UnionEvaluationError):
    """Raised when offline robustness settings or artifacts are invalid."""


class RobustTargetInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    start: str
    end: str
    retained_semantic_samples_inside: int
    retained_semantic_samples_tolerant_5s: int
    nearest_retained_semantic_timestamp_us: int | None
    nearest_retained_semantic_distance_us: int | None
    strongest_relevant_margin: float | None
    strongest_relevant_margin_timestamp_us: int | None
    semantic_detected: bool
    union_detected: bool


class PhaseEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase_seconds: float
    retained_semantic_samples: int
    retained_workload_fraction: float
    linear_encoder_seconds_estimate: float
    highest_exact_union_recall: float
    highest_tolerant_union_recall: float
    exact_recall_policy_count: int
    best_measured_policy: SamplingPolicySummary
    smallest_candidate_rate_exact_recall_policy: SamplingPolicySummary | None
    target_intervals: tuple[RobustTargetInterval, ...]


class FailurePhaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gap_seconds: float
    phase_seconds: float
    highest_exact_union_recall: float
    missed_intervals: tuple[str, ...]
    nearest_retained_semantic_timestamps_us: tuple[int | None, ...]


class TargetGapSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    start: str
    end: str
    minimum_retained_samples_inside: int
    minimum_retained_samples_tolerant_5s: int
    phases_semantically_detected: int
    phases_union_detected: int
    total_phases: int


class GapRobustnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gap_seconds: float
    phase_offsets_seconds: tuple[float, ...]
    minimum_retained_semantic_samples: int
    maximum_retained_semantic_samples: int
    average_retained_semantic_samples: float
    worst_case_exact_recall: float
    worst_case_tolerant_recall: float
    phase_success_rate_100_recall: float
    robust_exact_recall_1: bool
    candidate_sample_rate_min: float | None
    candidate_sample_rate_max: float | None
    candidate_samples_min: int | None
    candidate_samples_max: int | None
    most_compact_workload_policy: SamplingPolicySummary | None
    target_interval_summary: tuple[TargetGapSummary, ...]
    phase_results: tuple[PhaseEvaluation, ...]


class SemanticSamplingRobustnessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SEMANTIC_SAMPLING_ROBUSTNESS_SCHEMA_VERSION
    offline_only: bool = True
    video_filename: str
    video_duration_us: int
    source_sample_count: int
    gap_grid_seconds: tuple[float, ...]
    phase_step_seconds: float
    phase_grid_definition: str
    union_configuration: Stage1UnionEvaluationConfiguration
    workload_temporal_context_seconds: float
    workload_temporal_merge_gap_seconds: float
    measured_full_tinyclip_encoder_seconds: float
    gap_results: tuple[GapRobustnessResult, ...]
    first_phase_robustness_failure: FailurePhaseReport | None
    largest_robust_measured_gap_seconds: float | None
    metric_definitions: dict[str, str]


def select_phase_offset_samples(
    timestamps_us: Sequence[int], gap_seconds: float, phase_seconds: float
) -> np.ndarray:
    """Select the first representative at/after each ``phase + k * gap`` target."""
    _validate_gap_phase(gap_seconds, phase_seconds)
    timestamps = np.asarray(timestamps_us, dtype=np.int64)
    if timestamps.ndim != 1 or timestamps.size == 0:
        raise SemanticSamplingRobustnessError(
            "Semantic timestamps must be a non-empty one-dimensional sequence."
        )
    if np.any(timestamps[1:] <= timestamps[:-1]):
        raise SemanticSamplingRobustnessError(
            "Semantic timestamps must be strictly increasing."
        )
    duration_us = int(timestamps[-1])
    gap_us = round(gap_seconds * MICROSECONDS_PER_SECOND)
    phase_us = round(phase_seconds * MICROSECONDS_PER_SECOND)
    targets = np.arange(phase_us, duration_us + 1, gap_us, dtype=np.int64)
    selected_indices = np.searchsorted(timestamps, targets, side="left")
    selected_indices = selected_indices[selected_indices < timestamps.size]
    selected = np.zeros(timestamps.size, dtype=bool)
    selected[np.unique(selected_indices)] = True
    return selected


def phase_offset_grid(gap_seconds: float, step_seconds: float) -> tuple[float, ...]:
    """Return deterministic dense phases plus the required quarter offsets."""
    if not math.isfinite(step_seconds) or step_seconds <= 0.0:
        raise SemanticSamplingRobustnessError("Phase step must be finite and > 0.")
    _validate_gap_phase(gap_seconds, 0.0)
    dense = np.arange(0.0, gap_seconds, step_seconds, dtype=np.float64)
    required = np.asarray(
        (0.0, gap_seconds * 0.25, gap_seconds * 0.5, gap_seconds * 0.75)
    )
    return tuple(float(item) for item in np.unique(np.concatenate((dense, required))))


def evaluate_semantic_sampling_robustness(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    ground_truth: GroundTruthArtifact,
    prompt_bank: OfflinePromptBank,
    configuration: Stage1UnionEvaluationConfiguration | None = None,
    *,
    gaps_seconds: Sequence[float] = DEFAULT_ROBUSTNESS_GAPS_SECONDS,
    phase_step_seconds: float = DEFAULT_PHASE_STEP_SECONDS,
) -> SemanticSamplingRobustnessReport:
    """Evaluate every union policy across timestamp gaps and phase offsets."""
    config = configuration or Stage1UnionEvaluationConfiguration()
    aligned = align_artifacts(safety, semantic, prompt_bank, config)
    if ground_truth.video.filename.casefold() != safety.video.filename.casefold():
        raise SemanticSamplingRobustnessError(
            "Ground truth refers to a different video."
        )
    if not gaps_seconds or any(
        not math.isfinite(item) or item <= 0 for item in gaps_seconds
    ):
        raise SemanticSamplingRobustnessError(
            "Sampling gaps must be finite values > 0."
        )
    if len(set(gaps_seconds)) != len(gaps_seconds):
        raise SemanticSamplingRobustnessError("Sampling gaps must be unique.")
    timestamps = np.asarray(
        [sample.timestamp_us for sample in safety.samples], dtype=np.int64
    )
    intervals = tuple(
        sorted(ground_truth.intervals, key=lambda item: (item.start_us, item.end_us))
    )
    strategy_scores = _strategy_scores(_prompt_score_arrays(aligned.semantic))
    temporal_grid = tuple(product(config.context_seconds, config.merge_gap_seconds))
    workload_context, workload_gap = _least_expanded_workload_grid(config)
    gap_results: list[GapRobustnessResult] = []
    failures: list[FailurePhaseReport] = []
    for gap in gaps_seconds:
        phases = phase_offset_grid(gap, phase_step_seconds)
        phase_results: list[PhaseEvaluation] = []
        for phase in phases:
            availability = select_phase_offset_samples(timestamps, gap, phase)
            policies = _evaluate_policy_grid(
                timestamps=timestamps,
                availability=availability,
                safety=safety,
                strategy_scores=strategy_scores,
                intervals=intervals,
                duration_us=safety.video.duration_us,
                config=config,
                temporal_grid=temporal_grid,
            )
            phase_result = _phase_result(
                phase,
                availability,
                policies,
                timestamps,
                intervals,
                strategy_scores,
                workload_context,
                workload_gap,
            )
            phase_results.append(phase_result)
            if not phase_result.exact_recall_policy_count:
                failures.append(
                    _failure_report(
                        gap, phase_result, availability, timestamps, intervals
                    )
                )
        gap_results.append(_gap_result(gap, phases, phase_results))
    robust = [item.gap_seconds for item in gap_results if item.robust_exact_recall_1]
    return SemanticSamplingRobustnessReport(
        video_filename=safety.video.filename,
        video_duration_us=safety.video.duration_us,
        source_sample_count=len(timestamps),
        gap_grid_seconds=tuple(gaps_seconds),
        phase_step_seconds=phase_step_seconds,
        phase_grid_definition=(
            "Offsets are the union of [0, step, 2*step, ... < gap] and "
            "[0, 25%, 50%, 75% of gap], sorted and deduplicated."
        ),
        union_configuration=config,
        workload_temporal_context_seconds=workload_context,
        workload_temporal_merge_gap_seconds=workload_gap,
        measured_full_tinyclip_encoder_seconds=FULL_ENCODER_SECONDS,
        gap_results=tuple(gap_results),
        first_phase_robustness_failure=(failures[0] if failures else None),
        largest_robust_measured_gap_seconds=(max(robust) if robust else None),
        metric_definitions={
            "phase_sampling": "For each target P + kG, select the first exported representative at or after that target. Nonzero phases do not force the first movie representative.",
            "union_coverage": "ONNX scores are evaluated on every representative. TinyCLIP candidates exist only at selected timestamps and are never interpolated.",
            "robust_exact_recall_1": "Every tested phase for the gap has at least one union policy with exact recall 1.0 across all annotated intervals.",
            "linear_encoder_estimate": "249.750 seconds * selected TinyCLIP frames / 13,242. This is a linear workload estimate, not measured runtime.",
            "workload": "Most compact workload uses the configured grid's smallest context/merge-gap pair and is an evaluation-only VLM workload proxy.",
        },
    )


def write_sampling_robustness_csv(
    report: SemanticSamplingRobustnessReport, path: str | Path
) -> Path:
    output = io.StringIO(newline="")
    fields = (
        "gap_seconds",
        "phase_count",
        "minimum_semantic_frames",
        "maximum_semantic_frames",
        "average_semantic_frames",
        "worst_case_exact_recall",
        "worst_case_tolerant_recall",
        "phase_success_rate_100_recall",
        "robust_exact_recall_1",
        "candidate_rate_min",
        "candidate_rate_max",
        "merged_candidate_regions",
        "movie_fraction",
        "estimated_vlm_images",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in report.gap_results:
        summary = item.most_compact_workload_policy
        writer.writerow(
            {
                "gap_seconds": item.gap_seconds,
                "phase_count": len(item.phase_offsets_seconds),
                "minimum_semantic_frames": item.minimum_retained_semantic_samples,
                "maximum_semantic_frames": item.maximum_retained_semantic_samples,
                "average_semantic_frames": item.average_retained_semantic_samples,
                "worst_case_exact_recall": item.worst_case_exact_recall,
                "worst_case_tolerant_recall": item.worst_case_tolerant_recall,
                "phase_success_rate_100_recall": item.phase_success_rate_100_recall,
                "robust_exact_recall_1": item.robust_exact_recall_1,
                "candidate_rate_min": item.candidate_sample_rate_min,
                "candidate_rate_max": item.candidate_sample_rate_max,
                "merged_candidate_regions": summary.merged_candidate_regions
                if summary
                else None,
                "movie_fraction": summary.movie_fraction if summary else None,
                "estimated_vlm_images": summary.estimated_vlm_images
                if summary
                else None,
            }
        )
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output.getvalue(), encoding="utf-8", newline="")
    return output_path


def _phase_result(
    phase: float,
    availability: np.ndarray,
    policies: Sequence[object],
    timestamps: np.ndarray,
    intervals: Sequence[object],
    strategy_scores: dict[str, dict[str, np.ndarray]],
    context: float,
    merge_gap: float,
) -> PhaseEvaluation:
    ranked = sorted(policies, key=lambda item: _policy_key(item, context, merge_gap))
    exact = [
        item
        for item in policies
        if math.isclose(float(item.metrics.interval_recall or 0.0), 1.0)
    ]
    exact.sort(key=lambda item: _policy_key(item, context, merge_gap))
    chosen = exact[0] if exact else ranked[0]
    retained = int(availability.sum())
    return PhaseEvaluation(
        phase_seconds=phase,
        retained_semantic_samples=retained,
        retained_workload_fraction=retained / len(availability),
        linear_encoder_seconds_estimate=FULL_ENCODER_SECONDS
        * retained
        / len(availability),
        highest_exact_union_recall=float(ranked[0].metrics.interval_recall or 0.0),
        highest_tolerant_union_recall=max(
            float(item.metrics.tolerant_interval_recall_5s or 0.0) for item in policies
        ),
        exact_recall_policy_count=len(exact),
        best_measured_policy=_summary(ranked[0], context, merge_gap),
        smallest_candidate_rate_exact_recall_policy=(
            _summary(exact[0], context, merge_gap) if exact else None
        ),
        target_intervals=_target_intervals(
            chosen, availability, timestamps, intervals, strategy_scores
        ),
    )


def _gap_result(
    gap: float, phases: Sequence[float], results: Sequence[PhaseEvaluation]
) -> GapRobustnessResult:
    successes = [item for item in results if item.exact_recall_policy_count]
    summaries = [item.smallest_candidate_rate_exact_recall_policy for item in successes]
    summaries = [item for item in summaries if item is not None]
    compact = (
        min(
            summaries,
            key=lambda item: (
                item.candidate_sample_rate
                if item.candidate_sample_rate is not None
                else math.inf,
                item.estimated_vlm_images,
            ),
        )
        if summaries
        else None
    )
    rates = [
        item.candidate_sample_rate
        for item in summaries
        if item.candidate_sample_rate is not None
    ]
    counts = [item.candidate_samples for item in summaries]
    return GapRobustnessResult(
        gap_seconds=gap,
        phase_offsets_seconds=tuple(phases),
        minimum_retained_semantic_samples=min(
            item.retained_semantic_samples for item in results
        ),
        maximum_retained_semantic_samples=max(
            item.retained_semantic_samples for item in results
        ),
        average_retained_semantic_samples=sum(
            item.retained_semantic_samples for item in results
        )
        / len(results),
        worst_case_exact_recall=min(
            item.highest_exact_union_recall for item in results
        ),
        worst_case_tolerant_recall=min(
            item.highest_tolerant_union_recall for item in results
        ),
        phase_success_rate_100_recall=len(successes) / len(results),
        robust_exact_recall_1=len(successes) == len(results),
        candidate_sample_rate_min=min(rates) if rates else None,
        candidate_sample_rate_max=max(rates) if rates else None,
        candidate_samples_min=min(counts) if counts else None,
        candidate_samples_max=max(counts) if counts else None,
        most_compact_workload_policy=compact,
        target_interval_summary=_target_gap_summary(results),
        phase_results=tuple(results),
    )


def _target_intervals(
    item: object,
    availability: np.ndarray,
    timestamps: np.ndarray,
    intervals: Sequence[object],
    strategy_scores: dict[str, dict[str, np.ndarray]],
) -> tuple[RobustTargetInterval, ...]:
    reports = []
    for interval in intervals:
        category = getattr(interval, "category", "").casefold()
        if category not in TARGET_CATEGORIES:
            continue
        exact_mask = (timestamps >= interval.start_us) & (timestamps <= interval.end_us)
        tolerance = 5 * MICROSECONDS_PER_SECOND
        tolerant_mask = (timestamps >= max(0, interval.start_us - tolerance)) & (
            timestamps <= interval.end_us + tolerance
        )
        retained_exact = availability & exact_mask
        values = strategy_scores["max_positive_vs_control_max_margin"][category]
        if np.any(retained_exact):
            index = int(
                np.flatnonzero(retained_exact)[np.argmax(values[retained_exact])]
            )
            strongest, strongest_time = float(values[index]), int(timestamps[index])
        else:
            strongest, strongest_time = None, None
        nearest_time, nearest_distance = _nearest_available(
            timestamps, availability, interval.start_us, interval.end_us
        )
        reports.append(
            RobustTargetInterval(
                category=category,
                start=interval.start,
                end=interval.end,
                retained_semantic_samples_inside=int(retained_exact.sum()),
                retained_semantic_samples_tolerant_5s=int(
                    (availability & tolerant_mask).sum()
                ),
                nearest_retained_semantic_timestamp_us=nearest_time,
                nearest_retained_semantic_distance_us=nearest_distance,
                strongest_relevant_margin=strongest,
                strongest_relevant_margin_timestamp_us=strongest_time,
                semantic_detected=bool(np.any(item.semantic_mask & exact_mask)),
                union_detected=bool(np.any(item.union_mask & exact_mask)),
            )
        )
    return tuple(reports)


def _target_gap_summary(
    results: Sequence[PhaseEvaluation],
) -> tuple[TargetGapSummary, ...]:
    grouped: dict[tuple[str, str, str], list[RobustTargetInterval]] = {}
    for result in results:
        for item in result.target_intervals:
            grouped.setdefault((item.category, item.start, item.end), []).append(item)
    return tuple(
        TargetGapSummary(
            category=key[0],
            start=key[1],
            end=key[2],
            minimum_retained_samples_inside=min(
                item.retained_semantic_samples_inside for item in values
            ),
            minimum_retained_samples_tolerant_5s=min(
                item.retained_semantic_samples_tolerant_5s for item in values
            ),
            phases_semantically_detected=sum(item.semantic_detected for item in values),
            phases_union_detected=sum(item.union_detected for item in values),
            total_phases=len(values),
        )
        for key, values in sorted(grouped.items())
    )


def _failure_report(
    gap: float,
    result: PhaseEvaluation,
    availability: np.ndarray,
    timestamps: np.ndarray,
    intervals: Sequence[object],
) -> FailurePhaseReport:
    missed = result.best_measured_policy.missed_intervals
    timestamps_for_missed = []
    for item in missed:
        category, time_range = item.split(":", maxsplit=1)
        matching = next(
            interval
            for interval in intervals
            if (interval.category or "uncategorized") == category
            and f"{interval.start}-{interval.end}" == time_range
        )
        nearest, _ = _nearest_available(
            timestamps, availability, matching.start_us, matching.end_us
        )
        timestamps_for_missed.append(nearest)
    return FailurePhaseReport(
        gap_seconds=gap,
        phase_seconds=result.phase_seconds,
        highest_exact_union_recall=result.highest_exact_union_recall,
        missed_intervals=missed,
        nearest_retained_semantic_timestamps_us=tuple(timestamps_for_missed),
    )


def _nearest_available(
    timestamps: np.ndarray, availability: np.ndarray, start_us: int, end_us: int
) -> tuple[int | None, int | None]:
    if not np.any(availability):
        return None, None
    distances = np.where(
        timestamps < start_us,
        start_us - timestamps,
        np.where(timestamps > end_us, timestamps - end_us, 0),
    )
    distances = np.where(availability, distances, np.iinfo(np.int64).max)
    index = int(np.argmin(distances))
    return int(timestamps[index]), int(distances[index])


def _validate_gap_phase(gap_seconds: float, phase_seconds: float) -> None:
    if not math.isfinite(gap_seconds) or gap_seconds <= 0.0:
        raise SemanticSamplingRobustnessError("Sampling gap must be finite and > 0.")
    if not math.isfinite(phase_seconds) or not 0.0 <= phase_seconds < gap_seconds:
        raise SemanticSamplingRobustnessError(
            "Phase must be finite and satisfy 0 <= phase < gap."
        )
