"""Offline candidate-event clustering and pixel-free VLM-frame planning.

This evaluation consumes only persisted Stage-1 scores, prompt-bank provenance,
and annotations. It imports no model, FFmpeg, or media-processing runtime.
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from collections.abc import Sequence
from itertools import pairwise, product
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from services.analysis.semantic_sampling_robustness import select_phase_offset_samples
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    Stage1ScoreArtifact,
)
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

CLUSTERING_EVALUATION_SCHEMA_VERSION = 1
SEMANTIC_GAP_SECONDS = 10.0
SEMANTIC_PHASE_SECONDS = 0.0
MERGE_GAPS_SECONDS = (0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0)
CONTEXT_SECONDS = (0.0, 1.0, 2.0, 3.0, 5.0)
MAX_EVENT_DURATIONS_SECONDS = (15.0, 20.0, 30.0, 45.0, 60.0)
MAX_SELECTED_FRAMES = 6


class CandidateClusteringError(Stage1UnionEvaluationError):
    """An offline clustering input or policy artifact is invalid."""


class ExperimentalCandidatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["phase_robustness_phase_0"] = "phase_robustness_phase_0"
    semantic_gap_seconds: float = Field(gt=0.0)
    semantic_phase_seconds: float = Field(ge=0.0)
    onnx_baseline: str
    nsfw_threshold: float = Field(ge=0.0, le=1.0)
    nsfl_threshold: float = Field(ge=0.0, le=1.0)
    semantic_strategy: str
    weapons_threshold: float
    drugs_threshold: float
    robustness_candidate_sample_rate: float | None = Field(default=None, ge=0.0)


class CandidateSample(BaseModel):
    """Pixel-free detector evidence for one exported representative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str
    timestamp_us: int = Field(ge=0)
    sample_reasons: tuple[str, ...]
    detectors: tuple[Literal["onnx_safety", "tinyclip_semantic"], ...]
    onnx_nsfw: float = Field(ge=0.0, le=1.0)
    onnx_nsfl: float = Field(ge=0.0, le=1.0)
    onnx_triggered: bool
    tinyclip_triggered: bool
    tinyclip_weapons_triggered: bool
    tinyclip_drugs_triggered: bool
    tinyclip_weapons_score: float | None = None
    tinyclip_drugs_score: float | None = None


class SelectedEventFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample: CandidateSample
    selection_reasons: tuple[str, ...]


class CandidateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    candidate_start_timestamp_us: int = Field(ge=0)
    candidate_end_timestamp_us: int = Field(ge=0)
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    candidate_count: int = Field(gt=0)
    detector_profile: Literal["onnx_only", "tinyclip_only", "both"]
    selected_frames: tuple[SelectedEventFrame, ...] = Field(min_length=1, max_length=6)
    largest_selected_frame_gap_seconds: float = Field(ge=0.0)
    start_to_first_selected_seconds: float = Field(ge=0.0)
    last_selected_to_end_seconds: float = Field(ge=0.0)


class ClusteringConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    merge_gap_seconds: float = Field(ge=0.0)
    context_seconds: float = Field(ge=0.0)
    maximum_event_duration_seconds: float = Field(gt=0.0)


class CategoryCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    total_intervals: int = Field(ge=1)
    exact_detected_intervals: int = Field(ge=0)
    exact_recall: float = Field(ge=0.0, le=1.0)
    tolerant_detected_intervals: int = Field(ge=0)
    tolerant_recall: float = Field(ge=0.0, le=1.0)


class ClusteringMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_candidate_samples: int = Field(ge=0)
    candidate_events: int = Field(ge=0)
    candidate_to_event_ratio: float | None = Field(default=None, ge=0.0)
    vlm_call_reduction_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    average_event_duration_seconds: float = Field(ge=0.0)
    median_event_duration_seconds: float = Field(ge=0.0)
    p90_event_duration_seconds: float = Field(ge=0.0)
    maximum_event_duration_seconds: float = Field(ge=0.0)
    total_event_duration_seconds: float = Field(ge=0.0)
    movie_fraction: float = Field(ge=0.0, le=1.0)
    onnx_only_events: int = Field(ge=0)
    tinyclip_only_events: int = Field(ge=0)
    mixed_detector_events: int = Field(ge=0)
    exact_detected_intervals: int = Field(ge=0)
    exact_interval_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    tolerant_detected_intervals: int = Field(ge=0)
    tolerant_interval_recall_5s: float | None = Field(default=None, ge=0.0, le=1.0)
    missed_intervals: tuple[str, ...]
    category_recall: tuple[CategoryCoverage, ...]
    total_vlm_images: int = Field(ge=0)
    average_images_per_call: float = Field(ge=0.0)
    maximum_images_per_call: int = Field(ge=0, le=6)
    events_using_all_six_frames_fraction: float = Field(ge=0.0, le=1.0)


class ClusteringEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configuration: ClusteringConfiguration
    metrics: ClusteringMetrics


class TargetEventExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    interval_start: str
    interval_end: str
    events: tuple[CandidateEvent, ...]


class CandidateClusteringReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = CLUSTERING_EVALUATION_SCHEMA_VERSION
    offline_only: bool = True
    video_filename: str
    video_duration_us: int
    experimental_policy_for_clustering_benchmark: ExperimentalCandidatePolicy
    raw_candidate_count: int = Field(ge=0)
    grid: tuple[ClusteringConfiguration, ...]
    evaluations: tuple[ClusteringEvaluation, ...]
    exact_recall_pareto: tuple[ClusteringEvaluation, ...]
    best_measured_clustering_configuration: ClusteringEvaluation | None
    target_event_examples: tuple[TargetEventExample, ...]
    metric_definitions: dict[str, str]


class ExperimentalCandidateEventsArtifact(BaseModel):
    """Pixel-free event handoff for a later experimental VLM benchmark."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = CLUSTERING_EVALUATION_SCHEMA_VERSION
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    policy: ExperimentalCandidatePolicy
    clustering_configuration: ClusteringConfiguration
    events: tuple[CandidateEvent, ...]


def resolve_experimental_policy(
    union_evaluation_path: str | Path,
    robustness_evaluation_path: str | Path,
) -> ExperimentalCandidatePolicy:
    """Read the phase-zero 10-second policy and its ONNX baseline from artifacts."""
    try:
        union = json.loads(Path(union_evaluation_path).read_text(encoding="utf-8"))
        robustness = json.loads(
            Path(robustness_evaluation_path).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateClusteringError(
            f"Unable to read policy evaluation artifact ({type(exc).__name__})."
        ) from exc
    try:
        gap = next(
            item
            for item in robustness["gap_results"]
            if math.isclose(float(item["gap_seconds"]), SEMANTIC_GAP_SECONDS)
        )
        phase = next(
            item
            for item in gap["phase_results"]
            if math.isclose(float(item["phase_seconds"]), SEMANTIC_PHASE_SECONDS)
        )
        semantic = phase["smallest_candidate_rate_exact_recall_policy"]
        if semantic is None or not math.isclose(
            float(semantic["interval_recall"]), 1.0
        ):
            raise KeyError("no exact-recall phase-zero policy")
        onnx = next(
            item
            for item in union["onnx_baselines"]
            if item["policy"]["name"] == semantic["onnx_baseline"]
        )["policy"]
    except (KeyError, StopIteration, TypeError, ValueError) as exc:
        raise CandidateClusteringError(
            "Evaluation artifacts do not contain a resolvable 10-second phase-zero "
            "exact-recall policy."
        ) from exc
    return ExperimentalCandidatePolicy(
        semantic_gap_seconds=SEMANTIC_GAP_SECONDS,
        semantic_phase_seconds=SEMANTIC_PHASE_SECONDS,
        onnx_baseline=onnx["name"],
        nsfw_threshold=onnx["nsfw_threshold"],
        nsfl_threshold=onnx["nsfl_threshold"],
        semantic_strategy=semantic["semantic_strategy"],
        weapons_threshold=semantic["weapons_threshold"],
        drugs_threshold=semantic["drugs_threshold"],
        robustness_candidate_sample_rate=semantic.get("candidate_sample_rate"),
    )


def reconstruct_candidates(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    prompt_bank: OfflinePromptBank,
    policy: ExperimentalCandidatePolicy,
    configuration: Stage1UnionEvaluationConfiguration | None = None,
) -> tuple[CandidateSample, ...]:
    """Rebuild timestamped union candidates from scores, without inference."""
    config = configuration or Stage1UnionEvaluationConfiguration()
    aligned = align_artifacts(safety, semantic, prompt_bank, config)
    timestamps = np.asarray(
        [sample.timestamp_us for sample in safety.samples], dtype=np.int64
    )
    availability = select_phase_offset_samples(
        timestamps, policy.semantic_gap_seconds, policy.semantic_phase_seconds
    )
    strategies = _strategy_scores(_prompt_score_arrays(aligned.semantic))
    if policy.semantic_strategy not in strategies:
        raise CandidateClusteringError(
            f"Semantic strategy is unavailable in the raw score artifact: {policy.semantic_strategy}"
        )
    values = strategies[policy.semantic_strategy]
    result: list[CandidateSample] = []
    for index, (safety_sample, semantic_sample) in enumerate(
        zip(safety.samples, aligned.semantic, strict=True)
    ):
        onnx_trigger = (
            safety_sample.nsfw >= policy.nsfw_threshold
            or safety_sample.nsfl >= policy.nsfl_threshold
        )
        weapons_trigger = bool(availability[index]) and (
            values["weapons"][index] >= policy.weapons_threshold
        )
        drugs_trigger = bool(availability[index]) and (
            values["drugs"][index] >= policy.drugs_threshold
        )
        semantic_trigger = weapons_trigger or drugs_trigger
        if not onnx_trigger and not semantic_trigger:
            continue
        detectors: list[Literal["onnx_safety", "tinyclip_semantic"]] = []
        if onnx_trigger:
            detectors.append("onnx_safety")
        if semantic_trigger:
            detectors.append("tinyclip_semantic")
        result.append(
            CandidateSample(
                sample_id=safety_sample.sample_id,
                timestamp_us=safety_sample.timestamp_us,
                sample_reasons=safety_sample.sample_reasons,
                detectors=tuple(detectors),
                onnx_nsfw=safety_sample.nsfw,
                onnx_nsfl=safety_sample.nsfl,
                onnx_triggered=onnx_trigger,
                tinyclip_triggered=semantic_trigger,
                tinyclip_weapons_triggered=weapons_trigger,
                tinyclip_drugs_triggered=drugs_trigger,
                tinyclip_weapons_score=(
                    float(values["weapons"][index]) if availability[index] else None
                ),
                tinyclip_drugs_score=(
                    float(values["drugs"][index]) if availability[index] else None
                ),
            )
        )
    return tuple(result)


def cluster_candidates(
    candidates: Sequence[CandidateSample],
    *,
    merge_gap_seconds: float,
    context_seconds: float,
    maximum_event_duration_seconds: float,
    movie_duration_us: int,
) -> tuple[CandidateEvent, ...]:
    """Cluster timestamp-adjacent candidates then split oversized groups by gap."""
    if not candidates:
        return ()
    if (
        min(merge_gap_seconds, context_seconds) < 0.0
        or maximum_event_duration_seconds <= 0.0
    ):
        raise CandidateClusteringError(
            "Clustering durations must be non-negative and max > 0."
        )
    ordered = tuple(sorted(candidates, key=lambda item: item.timestamp_us))
    if len({item.timestamp_us for item in ordered}) != len(ordered):
        raise CandidateClusteringError("Candidate timestamps must be unique.")
    merge_gap_us = round(merge_gap_seconds * MICROSECONDS_PER_SECOND)
    context_us = round(context_seconds * MICROSECONDS_PER_SECOND)
    maximum_us = round(maximum_event_duration_seconds * MICROSECONDS_PER_SECOND)
    groups: list[list[CandidateSample]] = [[ordered[0]]]
    for candidate in ordered[1:]:
        if candidate.timestamp_us - groups[-1][-1].timestamp_us <= merge_gap_us:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    split_groups = [
        segment
        for group in groups
        for segment in _split_oversized_group(
            group, context_us=context_us, maximum_duration_us=maximum_us
        )
    ]
    return tuple(
        _event_from_group(
            group,
            event_id=f"event:{index:04d}",
            context_us=context_us,
            movie_duration_us=movie_duration_us,
        )
        for index, group in enumerate(split_groups)
    )


def select_event_frames(
    candidates: Sequence[CandidateSample],
) -> tuple[SelectedEventFrame, ...]:
    """Choose up to six scored, deduplicated, temporally diverse candidates."""
    ordered = tuple(sorted(candidates, key=lambda item: item.timestamp_us))
    if not ordered:
        return ()
    roles: dict[int, list[str]] = {}

    def add(index: int, role: str) -> None:
        roles.setdefault(index, []).append(role)

    onnx_indices = [index for index, item in enumerate(ordered) if item.onnx_triggered]
    if onnx_indices:
        add(
            max(onnx_indices, key=lambda item: _onnx_strength(ordered[item])),
            "strongest_onnx",
        )
    weapon_indices = [
        index
        for index, item in enumerate(ordered)
        if item.tinyclip_weapons_triggered and item.tinyclip_weapons_score is not None
    ]
    if weapon_indices:
        add(
            max(weapon_indices, key=lambda item: ordered[item].tinyclip_weapons_score),
            "strongest_tinyclip_weapons",
        )
    drug_indices = [
        index
        for index, item in enumerate(ordered)
        if item.tinyclip_drugs_triggered and item.tinyclip_drugs_score is not None
    ]
    if drug_indices:
        add(
            max(drug_indices, key=lambda item: ordered[item].tinyclip_drugs_score),
            "strongest_tinyclip_drugs",
        )
    add(0, "earliest_candidate")
    add(len(ordered) - 1, "latest_candidate")
    while len(roles) < min(MAX_SELECTED_FRAMES, len(ordered)):
        selected_times = [ordered[index].timestamp_us for index in roles]
        remaining = [index for index in range(len(ordered)) if index not in roles]
        next_index = max(
            remaining,
            key=lambda index: (
                min(
                    abs(ordered[index].timestamp_us - timestamp)
                    for timestamp in selected_times
                ),
                -ordered[index].timestamp_us,
            ),
        )
        add(next_index, "temporal_diversity")
    return tuple(
        SelectedEventFrame(sample=ordered[index], selection_reasons=tuple(reasons))
        for index, reasons in sorted(
            roles.items(), key=lambda item: ordered[item[0]].timestamp_us
        )
    )


def evaluate_candidate_clustering(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    ground_truth: GroundTruthArtifact,
    prompt_bank: OfflinePromptBank,
    policy: ExperimentalCandidatePolicy,
    configuration: Stage1UnionEvaluationConfiguration | None = None,
    *,
    merge_gaps_seconds: Sequence[float] = MERGE_GAPS_SECONDS,
    contexts_seconds: Sequence[float] = CONTEXT_SECONDS,
    maximum_event_durations_seconds: Sequence[float] = MAX_EVENT_DURATIONS_SECONDS,
) -> CandidateClusteringReport:
    config = configuration or Stage1UnionEvaluationConfiguration()
    if ground_truth.video.filename.casefold() != safety.video.filename.casefold():
        raise CandidateClusteringError("Ground truth refers to a different video.")
    candidates = reconstruct_candidates(safety, semantic, prompt_bank, policy, config)
    configurations = tuple(
        ClusteringConfiguration(
            merge_gap_seconds=merge_gap,
            context_seconds=context,
            maximum_event_duration_seconds=max_duration,
        )
        for merge_gap, context, max_duration in product(
            merge_gaps_seconds, contexts_seconds, maximum_event_durations_seconds
        )
    )
    evaluations = tuple(
        _evaluate_configuration(
            candidates,
            item,
            ground_truth.intervals,
            movie_duration_us=safety.video.duration_us,
        )
        for item in configurations
    )
    pareto = tuple(
        sorted(
            (
                item
                for item in evaluations
                if math.isclose(float(item.metrics.exact_interval_recall or 0.0), 1.0)
            ),
            key=lambda item: (
                item.metrics.candidate_events,
                item.metrics.total_vlm_images,
                item.metrics.total_event_duration_seconds,
                item.metrics.maximum_event_duration_seconds,
                item.configuration.merge_gap_seconds,
                item.configuration.context_seconds,
                item.configuration.maximum_event_duration_seconds,
            ),
        )
    )
    best = pareto[0] if pareto else None
    best_events = (
        _events_for_evaluation(candidates, best.configuration, safety.video.duration_us)
        if best
        else ()
    )
    return CandidateClusteringReport(
        video_filename=safety.video.filename,
        video_duration_us=safety.video.duration_us,
        experimental_policy_for_clustering_benchmark=policy,
        raw_candidate_count=len(candidates),
        grid=configurations,
        evaluations=evaluations,
        exact_recall_pareto=pareto,
        best_measured_clustering_configuration=best,
        target_event_examples=_target_examples(best_events, ground_truth.intervals),
        metric_definitions={
            "policy": "The policy is read from the saved 10-second, phase-zero robustness result and is explicitly experimental only.",
            "clustering": "Consecutive candidate timestamps join when their separation is <= merge gap. Oversized groups split recursively at their largest internal timestamp gap; scene boundaries are not used because no boundary timestamp contract is consumed here.",
            "coverage": "Exact/tolerant coverage is based on candidate timestamps inside each annotation, so clustering and context padding cannot fabricate a Stage-1 detection.",
            "frame_selection": "At most six existing candidate representatives are selected by detector strength, event endpoints, and farthest temporal diversity; pixels and tensors are not persisted.",
        },
    )


def write_clustering_csv(report: CandidateClusteringReport, path: str | Path) -> Path:
    output = io.StringIO(newline="")
    fields = (
        "merge_gap_seconds",
        "context_seconds",
        "maximum_event_duration_seconds",
        "raw_candidate_samples",
        "candidate_events",
        "candidate_to_event_ratio",
        "vlm_call_reduction_fraction",
        "total_vlm_images",
        "average_images_per_call",
        "total_event_duration_seconds",
        "maximum_event_duration_seconds_observed",
        "movie_fraction",
        "exact_interval_recall",
        "tolerant_interval_recall_5s",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for item in report.evaluations:
        metrics = item.metrics
        writer.writerow(
            {
                "merge_gap_seconds": item.configuration.merge_gap_seconds,
                "context_seconds": item.configuration.context_seconds,
                "maximum_event_duration_seconds": item.configuration.maximum_event_duration_seconds,
                "raw_candidate_samples": metrics.raw_candidate_samples,
                "candidate_events": metrics.candidate_events,
                "candidate_to_event_ratio": metrics.candidate_to_event_ratio,
                "vlm_call_reduction_fraction": metrics.vlm_call_reduction_fraction,
                "total_vlm_images": metrics.total_vlm_images,
                "average_images_per_call": metrics.average_images_per_call,
                "total_event_duration_seconds": metrics.total_event_duration_seconds,
                "maximum_event_duration_seconds_observed": metrics.maximum_event_duration_seconds,
                "movie_fraction": metrics.movie_fraction,
                "exact_interval_recall": metrics.exact_interval_recall,
                "tolerant_interval_recall_5s": metrics.tolerant_interval_recall_5s,
            }
        )
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output.getvalue(), encoding="utf-8", newline="")
    return output_path


def build_experimental_events_artifact(
    report: CandidateClusteringReport,
    candidates: Sequence[CandidateSample],
) -> ExperimentalCandidateEventsArtifact | None:
    """Materialize only the selected best-measured pixel-free event plan."""
    best = report.best_measured_clustering_configuration
    if best is None:
        return None
    events = _events_for_evaluation(
        candidates,
        best.configuration,
        report.video_duration_us,
    )
    return ExperimentalCandidateEventsArtifact(
        video_filename=report.video_filename,
        video_duration_us=report.video_duration_us,
        policy=report.experimental_policy_for_clustering_benchmark,
        clustering_configuration=best.configuration,
        events=events,
    )


def _evaluate_configuration(
    candidates: Sequence[CandidateSample],
    configuration: ClusteringConfiguration,
    intervals: Sequence[GroundTruthInterval],
    *,
    movie_duration_us: int,
) -> ClusteringEvaluation:
    events = _events_for_evaluation(candidates, configuration, movie_duration_us)
    exact, tolerant, missed = _coverage(candidates, intervals, movie_duration_us)
    durations = [event.duration_seconds for event in events]
    detector_profiles = [event.detector_profile for event in events]
    selected_counts = [len(event.selected_frames) for event in events]
    total = len(intervals)
    return ClusteringEvaluation(
        configuration=configuration,
        metrics=ClusteringMetrics(
            raw_candidate_samples=len(candidates),
            candidate_events=len(events),
            candidate_to_event_ratio=(
                len(candidates) / len(events) if events else None
            ),
            vlm_call_reduction_fraction=(
                1.0 - len(events) / len(candidates) if candidates else None
            ),
            average_event_duration_seconds=statistics.fmean(durations)
            if durations
            else 0.0,
            median_event_duration_seconds=statistics.median(durations)
            if durations
            else 0.0,
            p90_event_duration_seconds=float(np.percentile(durations, 90))
            if durations
            else 0.0,
            maximum_event_duration_seconds=max(durations, default=0.0),
            total_event_duration_seconds=sum(durations),
            movie_fraction=(
                _union_event_duration_us(events) / movie_duration_us
                if movie_duration_us
                else 0.0
            ),
            onnx_only_events=detector_profiles.count("onnx_only"),
            tinyclip_only_events=detector_profiles.count("tinyclip_only"),
            mixed_detector_events=detector_profiles.count("both"),
            exact_detected_intervals=sum(exact),
            exact_interval_recall=(sum(exact) / total if total else None),
            tolerant_detected_intervals=sum(tolerant),
            tolerant_interval_recall_5s=(sum(tolerant) / total if total else None),
            missed_intervals=tuple(missed),
            category_recall=_category_coverage(intervals, exact, tolerant),
            total_vlm_images=sum(selected_counts),
            average_images_per_call=statistics.fmean(selected_counts)
            if selected_counts
            else 0.0,
            maximum_images_per_call=max(selected_counts, default=0),
            events_using_all_six_frames_fraction=(
                selected_counts.count(6) / len(events) if events else 0.0
            ),
        ),
    )


def _events_for_evaluation(
    candidates: Sequence[CandidateSample],
    configuration: ClusteringConfiguration | None,
    movie_duration_us: int,
) -> tuple[CandidateEvent, ...]:
    if configuration is None:
        return ()
    return cluster_candidates(
        candidates,
        merge_gap_seconds=configuration.merge_gap_seconds,
        context_seconds=configuration.context_seconds,
        maximum_event_duration_seconds=configuration.maximum_event_duration_seconds,
        movie_duration_us=movie_duration_us,
    )


def _split_oversized_group(
    group: Sequence[CandidateSample], *, context_us: int, maximum_duration_us: int
) -> tuple[tuple[CandidateSample, ...], ...]:
    ordered = tuple(group)
    padded_duration = (
        ordered[-1].timestamp_us - ordered[0].timestamp_us + 2 * context_us
    )
    if padded_duration <= maximum_duration_us or len(ordered) == 1:
        return (ordered,)
    gaps = [
        ordered[index + 1].timestamp_us - ordered[index].timestamp_us
        for index in range(len(ordered) - 1)
    ]
    split_index = max(range(len(gaps)), key=lambda index: (gaps[index], -index)) + 1
    return _split_oversized_group(
        ordered[:split_index],
        context_us=context_us,
        maximum_duration_us=maximum_duration_us,
    ) + _split_oversized_group(
        ordered[split_index:],
        context_us=context_us,
        maximum_duration_us=maximum_duration_us,
    )


def _event_from_group(
    group: Sequence[CandidateSample],
    *,
    event_id: str,
    context_us: int,
    movie_duration_us: int,
) -> CandidateEvent:
    selected = select_event_frames(group)
    start = max(0, group[0].timestamp_us - context_us)
    end = min(movie_duration_us, group[-1].timestamp_us + context_us)
    selected_times = [item.sample.timestamp_us for item in selected]
    gaps = [later - earlier for earlier, later in pairwise(selected_times)]
    detector_set = {detector for item in group for detector in item.detectors}
    profile: Literal["onnx_only", "tinyclip_only", "both"]
    if detector_set == {"onnx_safety"}:
        profile = "onnx_only"
    elif detector_set == {"tinyclip_semantic"}:
        profile = "tinyclip_only"
    else:
        profile = "both"
    return CandidateEvent(
        event_id=event_id,
        candidate_start_timestamp_us=group[0].timestamp_us,
        candidate_end_timestamp_us=group[-1].timestamp_us,
        start_timestamp_us=start,
        end_timestamp_us=end,
        duration_seconds=(end - start) / MICROSECONDS_PER_SECOND,
        candidate_count=len(group),
        detector_profile=profile,
        selected_frames=selected,
        largest_selected_frame_gap_seconds=max(gaps, default=0)
        / MICROSECONDS_PER_SECOND,
        start_to_first_selected_seconds=(selected_times[0] - start)
        / MICROSECONDS_PER_SECOND,
        last_selected_to_end_seconds=(end - selected_times[-1])
        / MICROSECONDS_PER_SECOND,
    )


def _coverage(
    candidates: Sequence[CandidateSample],
    intervals: Sequence[GroundTruthInterval],
    movie_duration_us: int,
) -> tuple[list[bool], list[bool], list[str]]:
    timestamps = np.asarray([item.timestamp_us for item in candidates], dtype=np.int64)
    exact: list[bool] = []
    tolerant: list[bool] = []
    missed: list[str] = []
    tolerance_us = 5 * MICROSECONDS_PER_SECOND
    for interval in intervals:
        detected = bool(
            np.any((timestamps >= interval.start_us) & (timestamps <= interval.end_us))
        )
        tolerant_detected = bool(
            np.any(
                (timestamps >= max(0, interval.start_us - tolerance_us))
                & (timestamps <= min(movie_duration_us, interval.end_us + tolerance_us))
            )
        )
        exact.append(detected)
        tolerant.append(tolerant_detected)
        if not detected:
            missed.append(
                f"{interval.category or 'uncategorized'}:{interval.start}-{interval.end}"
            )
    return exact, tolerant, missed


def _category_coverage(
    intervals: Sequence[GroundTruthInterval],
    exact: Sequence[bool],
    tolerant: Sequence[bool],
) -> tuple[CategoryCoverage, ...]:
    grouped: dict[str, list[tuple[bool, bool]]] = {}
    for interval, exact_found, tolerant_found in zip(
        intervals, exact, tolerant, strict=True
    ):
        if interval.category is not None:
            grouped.setdefault(interval.category, []).append(
                (exact_found, tolerant_found)
            )
    return tuple(
        CategoryCoverage(
            category=category,
            total_intervals=len(values),
            exact_detected_intervals=sum(item[0] for item in values),
            exact_recall=sum(item[0] for item in values) / len(values),
            tolerant_detected_intervals=sum(item[1] for item in values),
            tolerant_recall=sum(item[1] for item in values) / len(values),
        )
        for category, values in sorted(grouped.items())
    )


def _target_examples(
    events: Sequence[CandidateEvent], intervals: Sequence[GroundTruthInterval]
) -> tuple[TargetEventExample, ...]:
    targets = [
        interval
        for interval in intervals
        if interval.category in {"drugs", "weapons"}
        and (interval.start, interval.end)
        in {
            ("00:12:55.000", "00:13:28.000"),
            ("01:07:46.000", "01:08:13.000"),
        }
    ]
    return tuple(
        TargetEventExample(
            category=interval.category or "uncategorized",
            interval_start=interval.start,
            interval_end=interval.end,
            events=tuple(
                event
                for event in events
                if event.candidate_end_timestamp_us >= interval.start_us
                and event.candidate_start_timestamp_us <= interval.end_us
            ),
        )
        for interval in targets
    )


def _onnx_strength(item: CandidateSample) -> float:
    return max(item.onnx_nsfw, item.onnx_nsfl)


def _union_event_duration_us(events: Sequence[CandidateEvent]) -> int:
    if not events:
        return 0
    merged_start = events[0].start_timestamp_us
    merged_end = events[0].end_timestamp_us
    total = 0
    for event in events[1:]:
        if event.start_timestamp_us <= merged_end:
            merged_end = max(merged_end, event.end_timestamp_us)
            continue
        total += merged_end - merged_start
        merged_start = event.start_timestamp_us
        merged_end = event.end_timestamp_us
    return total + merged_end - merged_start
