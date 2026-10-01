"""Offline TinyCLIP timestamp-sampling ablation.

This module reads exported scores only.  It deliberately imports no media or
model runtime, and masks unavailable TinyCLIP samples rather than interpolating
their scores onto other representatives.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict

from services.analysis.stage1_evaluation import GroundTruthArtifact, Stage1ScoreArtifact
from services.analysis.stage1_union_evaluation import (
    MICROSECONDS_PER_SECOND,
    OfflinePromptBank,
    ONNXBaselinePolicy,
    SemanticPolicy,
    SemanticScoreArtifact,
    Stage1UnionEvaluationConfiguration,
    Stage1UnionEvaluationError,
    _candidate_metrics,
    _observed_threshold_grid,
    _onnx_baselines,
    _prompt_score_arrays,
    _strategy_scores,
    align_artifacts,
)

SEMANTIC_SAMPLING_ABLATION_SCHEMA_VERSION = 1
DEFAULT_GAPS_SECONDS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0)
SCENE_TRANSITION_REASON = "scene_transition"
FULL_ENCODER_SECONDS = 249.750


class SemanticSamplingAblationError(Stage1UnionEvaluationError):
    """Raised when offline sampling-ablation inputs are incompatible."""


class SamplingPolicySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    onnx_baseline: str
    semantic_strategy: str
    weapons_threshold: float
    drugs_threshold: float
    interval_recall: float
    tolerant_interval_recall: float
    candidate_sample_rate: float | None
    candidate_samples: int
    category_recall: dict[str, float]
    missed_intervals: tuple[str, ...]
    merged_candidate_regions: int
    movie_fraction: float
    estimated_vlm_images: int


class TargetIntervalRobustness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    start: str
    end: str
    retained_semantic_samples_inside: int
    nearest_retained_semantic_timestamp_us: int | None
    nearest_retained_semantic_distance_us: int | None
    strongest_relevant_margin: float | None
    strongest_relevant_margin_timestamp_us: int | None
    semantic_detected: bool
    union_detected: bool


class SamplingConfigurationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str
    gap_seconds: float
    retained_semantic_samples: int
    retained_workload_fraction: float
    approximate_reduction_factor: float | None
    linear_encoder_seconds_estimate: float
    highest_exact_union_recall: float
    highest_tolerant_union_recall: float
    exact_recall_policy_count: int
    best_measured_policy: SamplingPolicySummary
    smallest_candidate_rate_exact_recall_policy: SamplingPolicySummary | None
    target_intervals: tuple[TargetIntervalRobustness, ...]


class SemanticSamplingAblationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SEMANTIC_SAMPLING_ABLATION_SCHEMA_VERSION
    offline_only: bool = True
    video_filename: str
    video_duration_us: int
    source_sample_count: int
    semantic_scene_aware_mode_available: bool
    scene_aware_reason: str | None
    union_configuration: Stage1UnionEvaluationConfiguration
    workload_temporal_context_seconds: float
    workload_temporal_merge_gap_seconds: float
    measured_full_tinyclip_encoder_seconds: float
    results: tuple[SamplingConfigurationResult, ...]
    exact_recall_pareto: tuple[SamplingConfigurationResult, ...]
    metric_definitions: dict[str, str]


@dataclass(frozen=True)
class _PolicyResult:
    onnx_policy: ONNXBaselinePolicy
    semantic_policy: SemanticPolicy
    semantic_mask: np.ndarray
    union_mask: np.ndarray
    metrics: object


def select_timestamp_samples(
    timestamps_us: Sequence[int], gap_seconds: float
) -> np.ndarray:
    """Select first representative then the first at/after each elapsed gap."""
    if not math.isfinite(gap_seconds) or gap_seconds <= 0.0:
        raise SemanticSamplingAblationError(
            "Semantic sampling gap must be finite and > 0."
        )
    timestamps = np.asarray(timestamps_us, dtype=np.int64)
    if timestamps.ndim != 1 or timestamps.size == 0:
        raise SemanticSamplingAblationError(
            "Semantic timestamps must be a non-empty sequence."
        )
    if np.any(timestamps[1:] <= timestamps[:-1]):
        raise SemanticSamplingAblationError(
            "Semantic timestamps must be strictly increasing."
        )
    gap_us = round(gap_seconds * MICROSECONDS_PER_SECOND)
    selected = np.zeros(timestamps.size, dtype=bool)
    selected[0] = True
    last_timestamp = int(timestamps[0])
    for index, timestamp in enumerate(timestamps[1:], start=1):
        if int(timestamp) - last_timestamp >= gap_us:
            selected[index] = True
            last_timestamp = int(timestamp)
    return selected


def scene_aware_mask(samples: Sequence[object]) -> np.ndarray | None:
    """Return the persisted scene-transition selection, or ``None`` if absent."""
    if not all(hasattr(sample, "sample_reasons") for sample in samples):
        return None
    return np.asarray(
        [SCENE_TRANSITION_REASON in sample.sample_reasons for sample in samples],
        dtype=bool,
    )


def evaluate_semantic_sampling_ablation(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    ground_truth: GroundTruthArtifact,
    prompt_bank: OfflinePromptBank,
    configuration: Stage1UnionEvaluationConfiguration | None = None,
    *,
    gaps_seconds: Sequence[float] = DEFAULT_GAPS_SECONDS,
) -> SemanticSamplingAblationReport:
    """Re-evaluate the full existing union policy grid with TinyCLIP masked."""
    config = configuration or Stage1UnionEvaluationConfiguration()
    aligned = align_artifacts(safety, semantic, prompt_bank, config)
    if ground_truth.video.filename.casefold() != safety.video.filename.casefold():
        raise SemanticSamplingAblationError("Ground truth refers to a different video.")
    if not gaps_seconds or any(
        not math.isfinite(gap) or gap <= 0.0 for gap in gaps_seconds
    ):
        raise SemanticSamplingAblationError(
            "Sampling gaps must be finite positive values."
        )
    if len(set(gaps_seconds)) != len(gaps_seconds):
        raise SemanticSamplingAblationError("Sampling gaps must be unique.")
    timestamps = np.asarray(
        [sample.timestamp_us for sample in safety.samples], dtype=np.int64
    )
    scene_mask = scene_aware_mask(aligned.semantic)
    prompt_scores = _prompt_score_arrays(aligned.semantic)
    strategy_scores = _strategy_scores(prompt_scores)
    intervals = tuple(
        sorted(ground_truth.intervals, key=lambda item: (item.start_us, item.end_us))
    )
    temporal_grid = tuple(product(config.context_seconds, config.merge_gap_seconds))
    workload_context, workload_gap = _least_expanded_workload_grid(config)
    results: list[SamplingConfigurationResult] = []
    for hybrid in (False, True):
        if hybrid and scene_mask is None:
            continue
        for gap in gaps_seconds:
            availability = select_timestamp_samples(timestamps, gap)
            if hybrid:
                availability |= scene_mask
            policy_results = _evaluate_policy_grid(
                timestamps=timestamps,
                availability=availability,
                safety=safety,
                strategy_scores=strategy_scores,
                intervals=intervals,
                duration_us=safety.video.duration_us,
                config=config,
                temporal_grid=temporal_grid,
            )
            results.append(
                _sampling_result(
                    mode=("temporal_plus_scene_transition" if hybrid else "temporal"),
                    gap_seconds=gap,
                    availability=availability,
                    policy_results=policy_results,
                    timestamps=timestamps,
                    intervals=intervals,
                    strategy_scores=strategy_scores,
                    workload_context=workload_context,
                    workload_gap=workload_gap,
                )
            )
    ordered_results = tuple(results)
    exact_pareto = tuple(
        sorted(
            (item for item in ordered_results if item.exact_recall_policy_count),
            key=lambda item: (
                item.retained_semantic_samples,
                item.smallest_candidate_rate_exact_recall_policy.candidate_sample_rate
                if item.smallest_candidate_rate_exact_recall_policy is not None
                else math.inf,
                item.smallest_candidate_rate_exact_recall_policy.estimated_vlm_images
                if item.smallest_candidate_rate_exact_recall_policy is not None
                else math.inf,
                item.mode,
                item.gap_seconds,
            ),
        )
    )
    return SemanticSamplingAblationReport(
        video_filename=safety.video.filename,
        video_duration_us=safety.video.duration_us,
        source_sample_count=len(timestamps),
        semantic_scene_aware_mode_available=scene_mask is not None,
        scene_aware_reason=(
            SCENE_TRANSITION_REASON if scene_mask is not None else None
        ),
        union_configuration=config,
        workload_temporal_context_seconds=workload_context,
        workload_temporal_merge_gap_seconds=workload_gap,
        measured_full_tinyclip_encoder_seconds=FULL_ENCODER_SECONDS,
        results=ordered_results,
        exact_recall_pareto=exact_pareto,
        metric_definitions={
            "sampling": "The first representative is retained, then the first later representative at or beyond the configured global timestamp gap. No score is interpolated onto skipped samples.",
            "scene_aware": "The hybrid mode retains persisted scene_transition representatives in addition to the timestamp selection.",
            "onnx_coverage": "ONNX candidates remain calculated on every representative; only TinyCLIP semantic candidates are masked.",
            "linear_encoder_estimate": "249.750 seconds multiplied by retained TinyCLIP samples divided by 13,242. This is a linear workload estimate, not a benchmark.",
            "workload": "Region and VLM-image fields use the least-expanded configured temporal workload grid and remain evaluation-only proxies.",
        },
    )


def write_sampling_ablation_csv(
    report: SemanticSamplingAblationReport, path: str | Path
) -> Path:
    output = io.StringIO(newline="")
    fields = (
        "mode",
        "gap_seconds",
        "retained_semantic_samples",
        "retained_workload_fraction",
        "linear_encoder_seconds_estimate",
        "highest_exact_union_recall",
        "exact_recall_policy_count",
        "candidate_sample_rate",
        "onnx_baseline",
        "semantic_strategy",
        "weapons_threshold",
        "drugs_threshold",
        "merged_candidate_regions",
        "estimated_vlm_images",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in report.results:
        summary = (
            item.smallest_candidate_rate_exact_recall_policy
            or item.best_measured_policy
        )
        writer.writerow(
            {
                "mode": item.mode,
                "gap_seconds": item.gap_seconds,
                "retained_semantic_samples": item.retained_semantic_samples,
                "retained_workload_fraction": item.retained_workload_fraction,
                "linear_encoder_seconds_estimate": item.linear_encoder_seconds_estimate,
                "highest_exact_union_recall": item.highest_exact_union_recall,
                "exact_recall_policy_count": item.exact_recall_policy_count,
                "candidate_sample_rate": summary.candidate_sample_rate,
                "onnx_baseline": summary.onnx_baseline,
                "semantic_strategy": summary.semantic_strategy,
                "weapons_threshold": summary.weapons_threshold,
                "drugs_threshold": summary.drugs_threshold,
                "merged_candidate_regions": summary.merged_candidate_regions,
                "estimated_vlm_images": summary.estimated_vlm_images,
            }
        )
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output.getvalue(), encoding="utf-8", newline="")
    return output_path


def _evaluate_policy_grid(
    *,
    timestamps: np.ndarray,
    availability: np.ndarray,
    safety: Stage1ScoreArtifact,
    strategy_scores: dict[str, dict[str, np.ndarray]],
    intervals: Sequence[object],
    duration_us: int,
    config: Stage1UnionEvaluationConfiguration,
    temporal_grid: Sequence[tuple[float, float]],
) -> tuple[_PolicyResult, ...]:
    semantic_entries: list[tuple[SemanticPolicy, np.ndarray]] = []
    for strategy, values in strategy_scores.items():
        weapon_thresholds = _observed_threshold_grid(
            values["weapons"], config.semantic_threshold_count
        )
        drug_thresholds = _observed_threshold_grid(
            values["drugs"], config.semantic_threshold_count
        )
        for weapon_threshold, drug_threshold in product(
            weapon_thresholds, drug_thresholds
        ):
            policy = SemanticPolicy(
                strategy=strategy,
                weapons_threshold=weapon_threshold,
                drugs_threshold=drug_threshold,
            )
            candidate = availability & (
                (values["weapons"] >= weapon_threshold)
                | (values["drugs"] >= drug_threshold)
            )
            semantic_entries.append((policy, candidate))
    nsfw = np.asarray([sample.nsfw for sample in safety.samples], dtype=np.float64)
    nsfl = np.asarray([sample.nsfl for sample in safety.samples], dtype=np.float64)
    results: list[_PolicyResult] = []
    for onnx_policy in _onnx_baselines():
        onnx_mask = (nsfw >= onnx_policy.nsfw_threshold) | (
            nsfl >= onnx_policy.nsfl_threshold
        )
        for semantic_policy, semantic_mask in semantic_entries:
            union_mask = onnx_mask | semantic_mask
            results.append(
                _PolicyResult(
                    onnx_policy,
                    semantic_policy,
                    semantic_mask,
                    union_mask,
                    _candidate_metrics(
                        union_mask,
                        timestamps=timestamps,
                        intervals=intervals,
                        duration_us=duration_us,
                        tolerance_seconds=config.tolerance_seconds,
                        temporal_grid=temporal_grid,
                        frames_per_region=config.frames_per_region,
                    ),
                )
            )
    return tuple(results)


def _sampling_result(
    *,
    mode: str,
    gap_seconds: float,
    availability: np.ndarray,
    policy_results: Sequence[_PolicyResult],
    timestamps: np.ndarray,
    intervals: Sequence[object],
    strategy_scores: dict[str, dict[str, np.ndarray]],
    workload_context: float,
    workload_gap: float,
) -> SamplingConfigurationResult:
    ranked = sorted(
        policy_results,
        key=lambda item: _policy_key(item, workload_context, workload_gap),
    )
    best = ranked[0]
    exact = [
        item
        for item in policy_results
        if math.isclose(float(item.metrics.interval_recall or 0.0), 1.0)
    ]
    exact.sort(key=lambda item: _policy_key(item, workload_context, workload_gap))
    retained = int(availability.sum())
    selected = exact[0] if exact else best
    return SamplingConfigurationResult(
        mode=mode,
        gap_seconds=gap_seconds,
        retained_semantic_samples=retained,
        retained_workload_fraction=retained / len(availability),
        approximate_reduction_factor=(
            len(availability) / retained if retained else None
        ),
        linear_encoder_seconds_estimate=FULL_ENCODER_SECONDS
        * retained
        / len(availability),
        highest_exact_union_recall=float(best.metrics.interval_recall or 0.0),
        highest_tolerant_union_recall=max(
            float(item.metrics.tolerant_interval_recall_5s or 0.0)
            for item in policy_results
        ),
        exact_recall_policy_count=len(exact),
        best_measured_policy=_summary(best, workload_context, workload_gap),
        smallest_candidate_rate_exact_recall_policy=(
            _summary(exact[0], workload_context, workload_gap) if exact else None
        ),
        target_intervals=_target_reports(
            selected, availability, timestamps, intervals, strategy_scores
        ),
    )


def _policy_key(
    item: _PolicyResult, context: float, merge_gap: float
) -> tuple[float, float, int, str, str, float, float]:
    workload = _workload(item.metrics, context, merge_gap)
    return (
        -float(item.metrics.interval_recall or 0.0),
        item.metrics.candidate_sample_rate
        if item.metrics.candidate_sample_rate is not None
        else math.inf,
        workload.estimated_vlm_images,
        item.onnx_policy.name,
        item.semantic_policy.strategy,
        item.semantic_policy.weapons_threshold,
        item.semantic_policy.drugs_threshold,
    )


def _summary(
    item: _PolicyResult, context: float, merge_gap: float
) -> SamplingPolicySummary:
    metrics = item.metrics
    workload = _workload(metrics, context, merge_gap)
    return SamplingPolicySummary(
        onnx_baseline=item.onnx_policy.name,
        semantic_strategy=item.semantic_policy.strategy,
        weapons_threshold=item.semantic_policy.weapons_threshold,
        drugs_threshold=item.semantic_policy.drugs_threshold,
        interval_recall=float(metrics.interval_recall or 0.0),
        tolerant_interval_recall=float(metrics.tolerant_interval_recall_5s or 0.0),
        candidate_sample_rate=metrics.candidate_sample_rate,
        candidate_samples=metrics.candidate_samples,
        category_recall={
            item.value: item.interval_recall for item in metrics.category_recall
        },
        missed_intervals=tuple(
            f"{item.category or 'uncategorized'}:{item.start}-{item.end}"
            for item in metrics.missed_interval_details
        ),
        merged_candidate_regions=workload.merged_candidate_regions,
        movie_fraction=workload.movie_fraction,
        estimated_vlm_images=workload.estimated_vlm_images,
    )


def _target_reports(
    item: _PolicyResult,
    availability: np.ndarray,
    timestamps: np.ndarray,
    intervals: Sequence[object],
    strategy_scores: dict[str, dict[str, np.ndarray]],
) -> tuple[TargetIntervalRobustness, ...]:
    targets = [
        interval
        for interval in intervals
        if getattr(interval, "category", "").casefold() in {"drugs", "weapons"}
    ]
    reports = []
    for interval in targets:
        category = interval.category.casefold()
        interval_mask = (timestamps >= interval.start_us) & (
            timestamps <= interval.end_us
        )
        retained_inside = availability & interval_mask
        # This diagnostic is intentionally a margin regardless of the policy
        # that happened to be best for the configuration.  It keeps target
        # robustness comparable across aggregation strategies.
        values = strategy_scores["max_positive_vs_control_max_margin"][category]
        value_mask = retained_inside
        if np.any(value_mask):
            index = int(np.flatnonzero(value_mask)[np.argmax(values[value_mask])])
            strongest, strongest_timestamp = (
                float(values[index]),
                int(timestamps[index]),
            )
        else:
            strongest, strongest_timestamp = None, None
        nearest_index = (
            int(
                np.argmin(
                    np.where(
                        availability,
                        np.where(
                            timestamps < interval.start_us,
                            interval.start_us - timestamps,
                            np.where(
                                timestamps > interval.end_us,
                                timestamps - interval.end_us,
                                0,
                            ),
                        ),
                        np.iinfo(np.int64).max,
                    )
                )
            )
            if np.any(availability)
            else None
        )
        nearest_timestamp = (
            int(timestamps[nearest_index]) if nearest_index is not None else None
        )
        nearest_distance = (
            int(
                max(
                    interval.start_us - timestamps[nearest_index],
                    0,
                    timestamps[nearest_index] - interval.end_us,
                )
            )
            if nearest_index is not None
            else None
        )
        reports.append(
            TargetIntervalRobustness(
                category=category,
                start=interval.start,
                end=interval.end,
                retained_semantic_samples_inside=int(retained_inside.sum()),
                nearest_retained_semantic_timestamp_us=nearest_timestamp,
                nearest_retained_semantic_distance_us=nearest_distance,
                strongest_relevant_margin=strongest,
                strongest_relevant_margin_timestamp_us=strongest_timestamp,
                semantic_detected=bool(np.any(item.semantic_mask & interval_mask)),
                union_detected=bool(np.any(item.union_mask & interval_mask)),
            )
        )
    return tuple(reports)


def _least_expanded_workload_grid(
    config: Stage1UnionEvaluationConfiguration,
) -> tuple[float, float]:
    return min(
        product(config.context_seconds, config.merge_gap_seconds),
        key=lambda item: (item[0], item[1]),
    )


def _workload(metrics: object, context: float, merge_gap: float) -> object:
    return next(
        item
        for item in metrics.temporal_workloads
        if item.context_seconds == context and item.merge_gap_seconds == merge_gap
    )
