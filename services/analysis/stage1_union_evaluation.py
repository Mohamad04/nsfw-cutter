"""Offline evaluation of exported ONNX safety and TinyCLIP semantic scores.

This module deliberately imports neither inference runtimes nor preprocessing
services. It operates only on persisted JSON artifacts and manual annotations.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import product
from pathlib import Path
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

from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    RecallBreakdown,
    Stage1EvaluationDataError,
    Stage1ScoreArtifact,
    Stage1ScoreVideo,
    load_ground_truth_artifact,
    load_score_artifact,
)

UNION_EVALUATION_SCHEMA_VERSION = 1
MICROSECONDS_PER_SECOND = 1_000_000
EXPECTED_REPRESENTATIVE_SAMPLES = 13_242
WEAPONS_CONCEPT_IDS = (
    "weapons.person_holding_gun",
    "weapons.firearm",
    "weapons.collection_of_guns",
    "weapons.aimed_at_someone",
)
DRUGS_CONCEPT_IDS = (
    "drugs.smoking_marijuana",
    "drugs.using_illegal_drugs",
    "drugs.paraphernalia",
)
CONTROL_CONCEPT_IDS = (
    "control.holding_phone",
    "control.holding_tool",
    "control.smoking_cigarette",
    "control.everyday_scene",
)
REQUIRED_CONCEPT_IDS = WEAPONS_CONCEPT_IDS + DRUGS_CONCEPT_IDS + CONTROL_CONCEPT_IDS


class Stage1UnionEvaluationError(Stage1EvaluationDataError):
    """An offline semantic/union input is malformed or incompatible."""


class OfflinePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class OfflinePromptBank(BaseModel):
    """The persisted evaluation prompt bank, without importing model code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bank_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompts: tuple[OfflinePrompt, ...] = Field(min_length=1)
    experimental: Literal[True] = True
    production_approved: Literal[False] = False

    @model_validator(mode="after")
    def unique_prompt_ids(self) -> OfflinePromptBank:
        concept_ids = [prompt.concept_id for prompt in self.prompts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("prompt-bank concept IDs must be unique")
        return self

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SemanticModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repo_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    checkpoint_sha256: str = Field(min_length=64, max_length=64)
    torch_version: str = Field(min_length=1)
    transformers_version: str = Field(min_length=1)
    device: str = Field(min_length=1)
    dtype: str = Field(min_length=1)
    processor_class: str = Field(min_length=1)
    tokenizer_class: str = Field(min_length=1)
    logit_scale_exp: float = Field(gt=0.0)
    experimental_model: Literal[True] = True
    production_license_cleared: Literal[False] = False

    @field_validator("logit_scale_exp")
    @classmethod
    def finite_scale(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("TinyCLIP logit scale must be finite")
        return value


class SemanticPromptBankProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bank_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    digest: str = Field(min_length=64, max_length=64)
    prompts: tuple[OfflinePrompt, ...] = Field(min_length=1)
    experimental: Literal[True] = True
    production_approved: Literal[False] = False


class SemanticScoreValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    cosine_similarity: float
    scaled_logit: float

    @field_validator("cosine_similarity", "scaled_logit")
    @classmethod
    def finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("semantic scores must be finite")
        return value


class SemanticScoreSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str = Field(min_length=1)
    timestamp_us: int = Field(ge=0)
    sample_reasons: tuple[str, ...]
    scores: tuple[SemanticScoreValue, ...] = Field(min_length=1)


class SemanticScoreArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_kind: Literal["tinyclip_semantic_raw_scores"]
    generated_at_utc: str = Field(min_length=1)
    video: Stage1ScoreVideo
    model: SemanticModelProvenance
    prompt_bank: SemanticPromptBankProvenance
    preprocessing: PreprocessingConfig
    samples: tuple[SemanticScoreSample, ...]

    @model_validator(mode="after")
    def ordered_unique_samples(self) -> SemanticScoreArtifact:
        timestamps = [sample.timestamp_us for sample in self.samples]
        sample_ids = [sample.sample_id for sample in self.samples]
        if timestamps != sorted(timestamps):
            raise ValueError("semantic score samples must be sorted by timestamp")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("semantic score timestamps must be unique")
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("semantic score sample IDs must be unique")
        if any(timestamp > self.video.duration_us for timestamp in timestamps):
            raise ValueError("semantic score timestamp exceeds movie duration")
        return self


class ScoreAlignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["sample_id", "timestamp"]
    timestamp_tolerance_us: int = Field(ge=0)
    expected_sample_count: int = Field(gt=0)
    safety_sample_count: int = Field(ge=0)
    semantic_sample_count: int = Field(ge=0)
    aligned_sample_count: int = Field(ge=0)
    video_filename_matches: bool
    duration_matches: bool
    safety_fingerprint: str | None
    semantic_fingerprint: str | None
    fingerprint_comparison: Literal["match", "unavailable"]
    preprocessing_matches: bool
    prompt_bank_digest: str
    prompt_bank_digest_matches: bool
    required_concepts: tuple[str, ...]


class ScoreDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    score_name: str
    population: Literal[
        "all_samples",
        "inside_weapons",
        "inside_drugs",
        "outside_all_ground_truth",
    ]
    sample_count: int = Field(ge=0)
    minimum: float | None = None
    maximum: float | None = None
    median: float | None = None
    p90: float | None = None
    p95: float | None = None
    p99: float | None = None


class ScorePeak(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float | None = None
    timestamp_us: int | None = Field(default=None, ge=0)


class StrategyIntervalPeaks(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: str
    weapons: ScorePeak
    drugs: ScorePeak
    controls: ScorePeak


class IntervalScoreSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    maximum_nsfw: ScorePeak
    maximum_nsfl: ScorePeak
    prompt_peaks: tuple[tuple[str, ScorePeak], ...]
    aggregation_peaks: tuple[StrategyIntervalPeaks, ...]


class IntervalPeakReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interval_index: int = Field(ge=0)
    start: str
    end: str
    category: str | None
    severity: str | None
    notes: str | None
    exact: IntervalScoreSnapshot
    tolerant_5s: IntervalScoreSnapshot


class SemanticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal[
        "max_positive_cosine",
        "mean_positive_cosine",
        "max_positive_vs_control_max_margin",
        "mean_positive_vs_control_max_margin",
    ]
    weapons_threshold: float
    drugs_threshold: float

    @field_validator("weapons_threshold", "drugs_threshold")
    @classmethod
    def finite_threshold(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("semantic thresholds must be finite")
        return value


class ONNXBaselinePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["A", "B", "C", "D"]
    nsfw_threshold: float = Field(ge=0.0, le=1.0)
    nsfl_threshold: float = Field(ge=0.0, le=1.0)


class MissedInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interval_index: int = Field(ge=0)
    start: str
    end: str
    category: str | None
    severity: str | None
    notes: str | None
    tolerant_detected: bool
    nearest_representative_timestamp_us: int | None = Field(default=None, ge=0)
    nearest_representative_distance_us: int | None = Field(default=None, ge=0)


class TemporalWorkload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_seconds: float = Field(ge=0.0)
    merge_gap_seconds: float = Field(ge=0.0)
    raw_candidate_samples: int = Field(ge=0)
    merged_candidate_regions: int = Field(ge=0)
    total_region_seconds: float = Field(ge=0.0)
    median_region_seconds: float = Field(ge=0.0)
    average_region_seconds: float = Field(ge=0.0)
    maximum_region_seconds: float = Field(ge=0.0)
    movie_fraction: float = Field(ge=0.0, le=1.0)
    frames_per_region: int = Field(gt=0)
    estimated_vlm_images: int = Field(ge=0)


class CandidateMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_intervals: int = Field(ge=0)
    detected_intervals: int = Field(ge=0)
    missed_intervals: int = Field(ge=0)
    interval_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    tolerant_detected_intervals: int = Field(ge=0)
    tolerant_missed_intervals: int = Field(ge=0)
    tolerant_interval_recall_5s: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_samples: int = Field(ge=0)
    total_representative_samples: int = Field(ge=0)
    candidate_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_samples_inside_gt: int | None = Field(default=None, ge=0)
    candidate_samples_outside_gt: int | None = Field(default=None, ge=0)
    frame_candidate_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    category_recall: tuple[RecallBreakdown, ...]
    severity_recall: tuple[RecallBreakdown, ...]
    semantic_target_category_recall: tuple[RecallBreakdown, ...]
    missed_interval_details: tuple[MissedInterval, ...]
    temporal_workloads: tuple[TemporalWorkload, ...]


class SemanticPolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: SemanticPolicy
    metrics: CandidateMetrics


class ONNXBaselineEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: ONNXBaselinePolicy
    metrics: CandidateMetrics


class UnionPolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    onnx_policy: ONNXBaselinePolicy
    semantic_policy: SemanticPolicy
    metrics: CandidateMetrics


class ParetoPolicySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    onnx_baseline: str
    semantic_strategy: str
    weapons_threshold: float
    drugs_threshold: float
    interval_recall: float
    tolerant_interval_recall: float
    candidate_sample_rate: float | None
    workload_context_seconds: float
    workload_merge_gap_seconds: float
    estimated_vlm_images: int
    merged_region_movie_fraction: float


class PerformanceContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["experimental_tinyclip_cpu_batch_2"] = (
        "experimental_tinyclip_cpu_batch_2"
    )
    combined_wall_seconds: float = 534.7643795
    media_throughput: float = 11.721748069422414
    movie_duration_seconds: float = 6268.373333
    note: str = "Previously measured benchmark provenance only; this offline evaluator did not rerun media preprocessing or inference."


class Stage1UnionEvaluationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_representative_samples: int = Field(
        default=EXPECTED_REPRESENTATIVE_SAMPLES,
        gt=0,
    )
    timestamp_tolerance_us: int = Field(default=0, ge=0)
    semantic_threshold_count: int = Field(default=7, ge=2, le=64)
    tolerance_seconds: float = Field(default=5.0, ge=0.0)
    context_seconds: tuple[float, ...] = (0.0, 1.0, 2.0, 5.0)
    merge_gap_seconds: tuple[float, ...] = (0.0, 1.0, 2.0)
    frames_per_region: int = Field(default=6, gt=0)

    @model_validator(mode="after")
    def valid_evaluation_grid(self) -> Stage1UnionEvaluationConfiguration:
        values = self.context_seconds + self.merge_gap_seconds
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError(
                "temporal context and merge-gap values must be finite >= 0"
            )
        if len(set(self.context_seconds)) != len(self.context_seconds):
            raise ValueError("temporal context values must be unique")
        if len(set(self.merge_gap_seconds)) != len(self.merge_gap_seconds):
            raise ValueError("temporal merge-gap values must be unique")
        return self


class Stage1UnionEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = UNION_EVALUATION_SCHEMA_VERSION
    configuration: Stage1UnionEvaluationConfiguration
    alignment: ScoreAlignment
    video: Stage1ScoreVideo
    safety_model: dict[str, object]
    semantic_model: SemanticModelProvenance
    preprocessing: PreprocessingConfig
    prompt_bank: SemanticPromptBankProvenance
    ground_truth_total_intervals: int = Field(ge=0)
    score_distributions: tuple[ScoreDistribution, ...]
    interval_peak_scores: tuple[IntervalPeakReport, ...]
    semantic_policies: tuple[SemanticPolicyEvaluation, ...]
    onnx_baselines: tuple[ONNXBaselineEvaluation, ...]
    union_policies: tuple[UnionPolicyEvaluation, ...]
    exact_recall_pareto: tuple[ParetoPolicySummary, ...]
    tolerant_recall_pareto: tuple[ParetoPolicySummary, ...]
    highest_exact_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    outside_ground_truth_prompt_rankings: tuple[ScoreDistribution, ...]
    performance_context: PerformanceContext
    metric_definitions: dict[str, str]


@dataclass(frozen=True)
class _AlignedScores:
    safety: Stage1ScoreArtifact
    semantic: tuple[SemanticScoreSample, ...]
    alignment: ScoreAlignment


def load_semantic_score_artifact(path: str | Path) -> SemanticScoreArtifact:
    resolved_path = Path(path)
    try:
        return SemanticScoreArtifact.model_validate_json(
            resolved_path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise Stage1UnionEvaluationError(
            f"TinyCLIP score artifact does not exist: {resolved_path}"
        ) from exc
    except OSError as exc:
        raise Stage1UnionEvaluationError(
            f"Unable to read TinyCLIP score artifact: {resolved_path}"
        ) from exc
    except ValidationError as exc:
        raise Stage1UnionEvaluationError(
            f"Invalid TinyCLIP score artifact '{resolved_path.name}': {exc}"
        ) from exc


def load_offline_prompt_bank(path: str | Path) -> OfflinePromptBank:
    resolved_path = Path(path)
    try:
        return OfflinePromptBank.model_validate_json(
            resolved_path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise Stage1UnionEvaluationError(
            f"TinyCLIP prompt bank does not exist: {resolved_path}"
        ) from exc
    except OSError as exc:
        raise Stage1UnionEvaluationError(
            f"Unable to read TinyCLIP prompt bank: {resolved_path}"
        ) from exc
    except ValidationError as exc:
        raise Stage1UnionEvaluationError(
            f"Invalid TinyCLIP prompt bank '{resolved_path.name}': {exc}"
        ) from exc


def load_union_inputs(
    safety_scores_path: str | Path,
    semantic_scores_path: str | Path,
    ground_truth_path: str | Path,
    prompt_bank_path: str | Path,
    configuration: Stage1UnionEvaluationConfiguration,
) -> tuple[
    Stage1ScoreArtifact,
    SemanticScoreArtifact,
    GroundTruthArtifact,
    OfflinePromptBank,
    _AlignedScores,
]:
    """Load and cross-validate all persisted artifacts without model imports."""
    safety = load_score_artifact(safety_scores_path)
    semantic = load_semantic_score_artifact(semantic_scores_path)
    prompt_bank = load_offline_prompt_bank(prompt_bank_path)
    ground_truth, _source = load_ground_truth_artifact(
        ground_truth_path,
        duration_us=safety.video.duration_us,
        default_video_filename=safety.video.filename,
    )
    aligned = align_artifacts(safety, semantic, prompt_bank, configuration)
    if ground_truth.video.filename.casefold() != safety.video.filename.casefold():
        raise Stage1UnionEvaluationError(
            "Safety scores and ground-truth video filenames differ: "
            f"'{safety.video.filename}' != '{ground_truth.video.filename}'."
        )
    return safety, semantic, ground_truth, prompt_bank, aligned


def align_artifacts(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    prompt_bank: OfflinePromptBank,
    configuration: Stage1UnionEvaluationConfiguration,
) -> _AlignedScores:
    """Align samples by stable identity; use validated timestamp fallback only."""
    if safety.video.filename.casefold() != semantic.video.filename.casefold():
        raise Stage1UnionEvaluationError(
            "Safety and TinyCLIP score video filenames differ: "
            f"'{safety.video.filename}' != '{semantic.video.filename}'."
        )
    if safety.video.duration_us != semantic.video.duration_us:
        raise Stage1UnionEvaluationError(
            "Safety and TinyCLIP score movie durations differ: "
            f"{safety.video.duration_us} != {semantic.video.duration_us}."
        )
    if safety.preprocessing != semantic.preprocessing:
        raise Stage1UnionEvaluationError(
            "Safety and TinyCLIP preprocessing configurations differ."
        )
    if len(safety.samples) != configuration.expected_representative_samples:
        raise Stage1UnionEvaluationError(
            "Safety score sample count differs from the configured expected count: "
            f"{len(safety.samples)} != {configuration.expected_representative_samples}."
        )
    if len(semantic.samples) != configuration.expected_representative_samples:
        raise Stage1UnionEvaluationError(
            "TinyCLIP score sample count differs from the configured expected count: "
            f"{len(semantic.samples)} != {configuration.expected_representative_samples}."
        )
    _validate_prompt_bank(semantic, prompt_bank)
    required_set = set(REQUIRED_CONCEPT_IDS)
    for sample in semantic.samples:
        concepts = [score.concept_id for score in sample.scores]
        if set(concepts) != required_set or len(concepts) != len(REQUIRED_CONCEPT_IDS):
            raise Stage1UnionEvaluationError(
                f"TinyCLIP sample '{sample.sample_id}' does not contain exactly the 11 required concepts."
            )

    safety_ids = {sample.sample_id for sample in safety.samples}
    semantic_by_id = {sample.sample_id: sample for sample in semantic.samples}
    if safety_ids == set(semantic_by_id):
        aligned_samples = tuple(
            semantic_by_id[sample.sample_id] for sample in safety.samples
        )
        if any(
            safety_sample.timestamp_us != semantic_sample.timestamp_us
            for safety_sample, semantic_sample in zip(
                safety.samples,
                aligned_samples,
                strict=True,
            )
        ):
            raise Stage1UnionEvaluationError(
                "Matching sample IDs have incompatible timestamps."
            )
        mode: Literal["sample_id", "timestamp"] = "sample_id"
    else:
        aligned_samples = _align_by_timestamp(
            safety.samples,
            semantic.samples,
            tolerance_us=configuration.timestamp_tolerance_us,
        )
        mode = "timestamp"
    safety_fingerprint = safety.video.fingerprint
    semantic_fingerprint = semantic.video.fingerprint
    if safety_fingerprint is not None and semantic_fingerprint is not None:
        if safety_fingerprint != semantic_fingerprint:
            raise Stage1UnionEvaluationError(
                "Safety and TinyCLIP video fingerprints differ."
            )
        fingerprint_comparison: Literal["match", "unavailable"] = "match"
    else:
        fingerprint_comparison = "unavailable"
    return _AlignedScores(
        safety=safety,
        semantic=aligned_samples,
        alignment=ScoreAlignment(
            mode=mode,
            timestamp_tolerance_us=configuration.timestamp_tolerance_us,
            expected_sample_count=configuration.expected_representative_samples,
            safety_sample_count=len(safety.samples),
            semantic_sample_count=len(semantic.samples),
            aligned_sample_count=len(aligned_samples),
            video_filename_matches=True,
            duration_matches=True,
            safety_fingerprint=safety_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            fingerprint_comparison=fingerprint_comparison,
            preprocessing_matches=True,
            prompt_bank_digest=semantic.prompt_bank.digest,
            prompt_bank_digest_matches=True,
            required_concepts=REQUIRED_CONCEPT_IDS,
        ),
    )


def evaluate_union_artifacts(
    safety: Stage1ScoreArtifact,
    semantic: SemanticScoreArtifact,
    ground_truth: GroundTruthArtifact,
    prompt_bank: OfflinePromptBank,
    configuration: Stage1UnionEvaluationConfiguration | None = None,
    semantic_availability_mask: np.ndarray | None = None,
) -> Stage1UnionEvaluationReport:
    config = configuration or Stage1UnionEvaluationConfiguration()
    aligned = align_artifacts(safety, semantic, prompt_bank, config)
    if ground_truth.video.filename.casefold() != safety.video.filename.casefold():
        raise Stage1UnionEvaluationError(
            "Ground truth refers to a different video filename."
        )
    intervals = tuple(sorted(ground_truth.intervals, key=_interval_sort_key))
    timestamps = np.asarray(
        [sample.timestamp_us for sample in safety.samples], dtype=np.int64
    )
    if semantic_availability_mask is None:
        semantic_availability = np.ones(len(timestamps), dtype=bool)
    else:
        semantic_availability = np.asarray(semantic_availability_mask, dtype=bool)
        if semantic_availability.ndim != 1 or len(semantic_availability) != len(
            timestamps
        ):
            raise Stage1UnionEvaluationError(
                "Semantic availability mask must be one-dimensional and match the aligned "
                "representative sample count."
            )
    nsfw = np.asarray([sample.nsfw for sample in safety.samples], dtype=np.float64)
    nsfl = np.asarray([sample.nsfl for sample in safety.samples], dtype=np.float64)
    prompt_scores = _prompt_score_arrays(aligned.semantic)
    strategy_scores = _strategy_scores(prompt_scores)
    temporal_grid = tuple(
        (context, merge_gap)
        for context, merge_gap in product(
            config.context_seconds, config.merge_gap_seconds
        )
    )
    masks = _population_masks(timestamps, intervals)
    distributions = _score_distributions(prompt_scores, strategy_scores, masks)
    interval_peaks = _interval_peak_reports(
        intervals,
        timestamps=timestamps,
        nsfw=nsfw,
        nsfl=nsfl,
        prompt_scores=prompt_scores,
        strategy_scores=strategy_scores,
        duration_us=safety.video.duration_us,
        tolerance_seconds=config.tolerance_seconds,
    )
    semantic_results: list[SemanticPolicyEvaluation] = []
    semantic_masks: list[tuple[SemanticPolicy, np.ndarray]] = []
    for strategy, values in strategy_scores.items():
        weapon_thresholds = _observed_threshold_grid(
            values["weapons"], config.semantic_threshold_count
        )
        drug_thresholds = _observed_threshold_grid(
            values["drugs"], config.semantic_threshold_count
        )
        for weapons_threshold, drugs_threshold in product(
            weapon_thresholds,
            drug_thresholds,
        ):
            policy = SemanticPolicy(
                strategy=strategy,
                weapons_threshold=weapons_threshold,
                drugs_threshold=drugs_threshold,
            )
            candidate_mask = semantic_availability & (
                (values["weapons"] >= weapons_threshold)
                | (values["drugs"] >= drugs_threshold)
            )
            semantic_masks.append((policy, candidate_mask))
            semantic_results.append(
                SemanticPolicyEvaluation(
                    policy=policy,
                    metrics=_candidate_metrics(
                        candidate_mask,
                        timestamps=timestamps,
                        intervals=intervals,
                        duration_us=safety.video.duration_us,
                        tolerance_seconds=config.tolerance_seconds,
                        temporal_grid=temporal_grid,
                        frames_per_region=config.frames_per_region,
                    ),
                )
            )
    onnx_masks: list[tuple[ONNXBaselinePolicy, np.ndarray]] = []
    onnx_results: list[ONNXBaselineEvaluation] = []
    for policy in _onnx_baselines():
        candidate_mask = (nsfw >= policy.nsfw_threshold) | (
            nsfl >= policy.nsfl_threshold
        )
        onnx_masks.append((policy, candidate_mask))
        onnx_results.append(
            ONNXBaselineEvaluation(
                policy=policy,
                metrics=_candidate_metrics(
                    candidate_mask,
                    timestamps=timestamps,
                    intervals=intervals,
                    duration_us=safety.video.duration_us,
                    tolerance_seconds=config.tolerance_seconds,
                    temporal_grid=temporal_grid,
                    frames_per_region=config.frames_per_region,
                ),
            )
        )
    union_results = tuple(
        UnionPolicyEvaluation(
            onnx_policy=onnx_policy,
            semantic_policy=semantic_policy,
            metrics=_candidate_metrics(
                onnx_mask | semantic_mask,
                timestamps=timestamps,
                intervals=intervals,
                duration_us=safety.video.duration_us,
                tolerance_seconds=config.tolerance_seconds,
                temporal_grid=temporal_grid,
                frames_per_region=config.frames_per_region,
            ),
        )
        for onnx_policy, onnx_mask in onnx_masks
        for semantic_policy, semantic_mask in semantic_masks
    )
    return Stage1UnionEvaluationReport(
        configuration=config,
        alignment=aligned.alignment,
        video=safety.video,
        safety_model=safety.model.model_dump(mode="json"),
        semantic_model=semantic.model,
        preprocessing=safety.preprocessing,
        prompt_bank=semantic.prompt_bank,
        ground_truth_total_intervals=len(intervals),
        score_distributions=distributions,
        interval_peak_scores=interval_peaks,
        semantic_policies=tuple(semantic_results),
        onnx_baselines=tuple(onnx_results),
        union_policies=union_results,
        exact_recall_pareto=_pareto_summaries(
            union_results,
            recall_field="interval_recall",
            required_recall=1.0,
        ),
        tolerant_recall_pareto=_pareto_summaries(
            union_results,
            recall_field="tolerant_interval_recall_5s",
            required_recall=1.0,
        ),
        highest_exact_recall=_highest_exact_recall(union_results),
        outside_ground_truth_prompt_rankings=tuple(
            sorted(
                (
                    item
                    for item in distributions
                    if item.population == "outside_all_ground_truth"
                    and item.score_name.startswith("prompt:")
                ),
                key=lambda item: (
                    -(item.p99 if item.p99 is not None else -math.inf),
                    item.score_name,
                ),
            )
        ),
        performance_context=PerformanceContext(),
        metric_definitions=_metric_definitions(),
    )


def write_union_policy_csv(
    report: Stage1UnionEvaluationReport, path: str | Path
) -> Path:
    output = io.StringIO(newline="")
    fields = (
        "onnx_baseline",
        "nsfw_threshold",
        "nsfl_threshold",
        "semantic_strategy",
        "weapons_threshold",
        "drugs_threshold",
        "interval_recall",
        "tolerant_interval_recall_5s",
        "candidate_samples",
        "candidate_sample_rate",
        "frame_candidate_precision",
        "context_seconds",
        "merge_gap_seconds",
        "merged_candidate_regions",
        "movie_fraction",
        "estimated_vlm_images",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for result in report.union_policies:
        for workload in result.metrics.temporal_workloads:
            writer.writerow(
                {
                    "onnx_baseline": result.onnx_policy.name,
                    "nsfw_threshold": result.onnx_policy.nsfw_threshold,
                    "nsfl_threshold": result.onnx_policy.nsfl_threshold,
                    "semantic_strategy": result.semantic_policy.strategy,
                    "weapons_threshold": result.semantic_policy.weapons_threshold,
                    "drugs_threshold": result.semantic_policy.drugs_threshold,
                    "interval_recall": result.metrics.interval_recall,
                    "tolerant_interval_recall_5s": (
                        result.metrics.tolerant_interval_recall_5s
                    ),
                    "candidate_samples": result.metrics.candidate_samples,
                    "candidate_sample_rate": result.metrics.candidate_sample_rate,
                    "frame_candidate_precision": result.metrics.frame_candidate_precision,
                    "context_seconds": workload.context_seconds,
                    "merge_gap_seconds": workload.merge_gap_seconds,
                    "merged_candidate_regions": workload.merged_candidate_regions,
                    "movie_fraction": workload.movie_fraction,
                    "estimated_vlm_images": workload.estimated_vlm_images,
                }
            )
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output.getvalue(), encoding="utf-8", newline="")
    return output_path


def _validate_prompt_bank(
    semantic: SemanticScoreArtifact,
    prompt_bank: OfflinePromptBank,
) -> None:
    if semantic.prompt_bank.digest != prompt_bank.digest:
        raise Stage1UnionEvaluationError(
            "TinyCLIP score prompt-bank digest does not match the supplied prompt bank."
        )
    artifact_prompts = tuple(
        (prompt.concept_id, prompt.text) for prompt in semantic.prompt_bank.prompts
    )
    supplied_prompts = tuple(
        (prompt.concept_id, prompt.text) for prompt in prompt_bank.prompts
    )
    if artifact_prompts != supplied_prompts:
        raise Stage1UnionEvaluationError(
            "TinyCLIP score prompt-bank prompts do not match the supplied prompt bank."
        )
    if (
        tuple(prompt.concept_id for prompt in prompt_bank.prompts)
        != REQUIRED_CONCEPT_IDS
    ):
        raise Stage1UnionEvaluationError(
            "Supplied prompt bank does not match the required evaluation-only groups."
        )


def _align_by_timestamp(
    safety_samples: Sequence[object],
    semantic_samples: Sequence[SemanticScoreSample],
    *,
    tolerance_us: int,
) -> tuple[SemanticScoreSample, ...]:
    if len(safety_samples) != len(semantic_samples):
        raise Stage1UnionEvaluationError(
            "Cannot timestamp-align score artifacts with different sample counts."
        )
    remaining = list(semantic_samples)
    aligned: list[SemanticScoreSample] = []
    for safety_sample in safety_samples:
        timestamp = safety_sample.timestamp_us
        index = min(
            range(len(remaining)),
            key=lambda candidate: abs(remaining[candidate].timestamp_us - timestamp),
        )
        candidate = remaining[index]
        if abs(candidate.timestamp_us - timestamp) > tolerance_us:
            raise Stage1UnionEvaluationError(
                "Timestamp fallback cannot align every score sample within the configured tolerance."
            )
        aligned.append(candidate)
        remaining.pop(index)
    return tuple(aligned)


def _prompt_score_arrays(
    samples: Sequence[SemanticScoreSample],
) -> dict[str, np.ndarray]:
    arrays = {concept_id: [] for concept_id in REQUIRED_CONCEPT_IDS}
    for sample in samples:
        values = {score.concept_id: score.cosine_similarity for score in sample.scores}
        for concept_id in REQUIRED_CONCEPT_IDS:
            arrays[concept_id].append(values[concept_id])
    return {
        concept_id: np.asarray(values, dtype=np.float64)
        for concept_id, values in arrays.items()
    }


def _strategy_scores(
    prompts: dict[str, np.ndarray],
) -> dict[str, dict[str, np.ndarray]]:
    weapons = np.stack(
        [prompts[concept_id] for concept_id in WEAPONS_CONCEPT_IDS], axis=1
    )
    drugs = np.stack([prompts[concept_id] for concept_id in DRUGS_CONCEPT_IDS], axis=1)
    controls = np.stack(
        [prompts[concept_id] for concept_id in CONTROL_CONCEPT_IDS], axis=1
    )
    control_max = controls.max(axis=1)
    weapon_max = weapons.max(axis=1)
    drugs_max = drugs.max(axis=1)
    weapon_mean = weapons.mean(axis=1)
    drugs_mean = drugs.mean(axis=1)
    return {
        "max_positive_cosine": {
            "weapons": weapon_max,
            "drugs": drugs_max,
            "controls": control_max,
        },
        "mean_positive_cosine": {
            "weapons": weapon_mean,
            "drugs": drugs_mean,
            "controls": control_max,
        },
        "max_positive_vs_control_max_margin": {
            "weapons": weapon_max - control_max,
            "drugs": drugs_max - control_max,
            "controls": control_max,
        },
        "mean_positive_vs_control_max_margin": {
            "weapons": weapon_mean - control_max,
            "drugs": drugs_mean - control_max,
            "controls": control_max,
        },
    }


def _population_masks(
    timestamps: np.ndarray,
    intervals: Sequence[GroundTruthInterval],
) -> dict[str, np.ndarray]:
    inside_all = np.zeros(timestamps.shape, dtype=bool)
    inside_weapons = np.zeros(timestamps.shape, dtype=bool)
    inside_drugs = np.zeros(timestamps.shape, dtype=bool)
    for interval in intervals:
        mask = (timestamps >= interval.start_us) & (timestamps <= interval.end_us)
        inside_all |= mask
        if _category_key(interval.category) == "weapons":
            inside_weapons |= mask
        if _category_key(interval.category) == "drugs":
            inside_drugs |= mask
    return {
        "all_samples": np.ones(timestamps.shape, dtype=bool),
        "inside_weapons": inside_weapons,
        "inside_drugs": inside_drugs,
        "outside_all_ground_truth": ~inside_all,
    }


def _score_distributions(
    prompts: dict[str, np.ndarray],
    strategies: dict[str, dict[str, np.ndarray]],
    masks: dict[str, np.ndarray],
) -> tuple[ScoreDistribution, ...]:
    series: dict[str, np.ndarray] = {
        f"prompt:{concept_id}": values for concept_id, values in prompts.items()
    }
    for strategy, values in strategies.items():
        series[f"{strategy}:weapons"] = values["weapons"]
        series[f"{strategy}:drugs"] = values["drugs"]
    return tuple(
        _distribution(name, population, values[mask])
        for name, values in series.items()
        for population, mask in masks.items()
    )


def _distribution(name: str, population: str, values: np.ndarray) -> ScoreDistribution:
    if values.size == 0:
        return ScoreDistribution(score_name=name, population=population, sample_count=0)
    quantiles = np.percentile(values, [50, 90, 95, 99])
    return ScoreDistribution(
        score_name=name,
        population=population,
        sample_count=int(values.size),
        minimum=float(values.min()),
        maximum=float(values.max()),
        median=float(quantiles[0]),
        p90=float(quantiles[1]),
        p95=float(quantiles[2]),
        p99=float(quantiles[3]),
    )


def _interval_peak_reports(
    intervals: Sequence[GroundTruthInterval],
    *,
    timestamps: np.ndarray,
    nsfw: np.ndarray,
    nsfl: np.ndarray,
    prompt_scores: dict[str, np.ndarray],
    strategy_scores: dict[str, dict[str, np.ndarray]],
    duration_us: int,
    tolerance_seconds: float,
) -> tuple[IntervalPeakReport, ...]:
    tolerance_us = round(tolerance_seconds * MICROSECONDS_PER_SECOND)
    reports = []
    for index, interval in enumerate(intervals):
        exact = (timestamps >= interval.start_us) & (timestamps <= interval.end_us)
        tolerant = (timestamps >= max(0, interval.start_us - tolerance_us)) & (
            timestamps <= min(duration_us, interval.end_us + tolerance_us)
        )
        reports.append(
            IntervalPeakReport(
                interval_index=index,
                start=interval.start,
                end=interval.end,
                category=interval.category,
                severity=interval.severity,
                notes=interval.notes,
                exact=_interval_snapshot(
                    exact,
                    timestamps,
                    nsfw,
                    nsfl,
                    prompt_scores,
                    strategy_scores,
                ),
                tolerant_5s=_interval_snapshot(
                    tolerant,
                    timestamps,
                    nsfw,
                    nsfl,
                    prompt_scores,
                    strategy_scores,
                ),
            )
        )
    return tuple(reports)


def _interval_snapshot(
    mask: np.ndarray,
    timestamps: np.ndarray,
    nsfw: np.ndarray,
    nsfl: np.ndarray,
    prompt_scores: dict[str, np.ndarray],
    strategy_scores: dict[str, dict[str, np.ndarray]],
) -> IntervalScoreSnapshot:
    return IntervalScoreSnapshot(
        maximum_nsfw=_peak(nsfw, timestamps, mask),
        maximum_nsfl=_peak(nsfl, timestamps, mask),
        prompt_peaks=tuple(
            (concept_id, _peak(values, timestamps, mask))
            for concept_id, values in prompt_scores.items()
        ),
        aggregation_peaks=tuple(
            StrategyIntervalPeaks(
                strategy=strategy,
                weapons=_peak(values["weapons"], timestamps, mask),
                drugs=_peak(values["drugs"], timestamps, mask),
                controls=_peak(values["controls"], timestamps, mask),
            )
            for strategy, values in strategy_scores.items()
        ),
    )


def _peak(values: np.ndarray, timestamps: np.ndarray, mask: np.ndarray) -> ScorePeak:
    indices = np.flatnonzero(mask)
    if indices.size == 0:
        return ScorePeak()
    relative_index = int(np.argmax(values[indices]))
    index = int(indices[relative_index])
    return ScorePeak(value=float(values[index]), timestamp_us=int(timestamps[index]))


def _observed_threshold_grid(values: np.ndarray, count: int) -> tuple[float, ...]:
    if values.size == 0:
        raise Stage1UnionEvaluationError(
            "Cannot create a threshold grid with no scores."
        )
    indices = np.rint(np.linspace(0, values.size - 1, count)).astype(np.int64)
    ordered = np.sort(values)
    return tuple(float(value) for value in np.unique(ordered[indices]))


def _candidate_metrics(
    candidate_mask: np.ndarray,
    *,
    timestamps: np.ndarray,
    intervals: Sequence[GroundTruthInterval],
    duration_us: int,
    tolerance_seconds: float,
    temporal_grid: Sequence[tuple[float, float]],
    frames_per_region: int,
) -> CandidateMetrics:
    tolerance_us = round(tolerance_seconds * MICROSECONDS_PER_SECOND)
    exact_detections: list[bool] = []
    tolerant_detections: list[bool] = []
    missed: list[MissedInterval] = []
    inside_gt = np.zeros(timestamps.shape, dtype=bool)
    for index, interval in enumerate(intervals):
        exact_mask = (timestamps >= interval.start_us) & (timestamps <= interval.end_us)
        tolerant_mask = (timestamps >= max(0, interval.start_us - tolerance_us)) & (
            timestamps <= min(duration_us, interval.end_us + tolerance_us)
        )
        exact_detected = bool(np.any(candidate_mask & exact_mask))
        tolerant_detected = bool(np.any(candidate_mask & tolerant_mask))
        exact_detections.append(exact_detected)
        tolerant_detections.append(tolerant_detected)
        inside_gt |= exact_mask
        if not exact_detected:
            nearest_timestamp, nearest_distance = _nearest_timestamp(
                timestamps,
                interval.start_us,
                interval.end_us,
            )
            missed.append(
                MissedInterval(
                    interval_index=index,
                    start=interval.start,
                    end=interval.end,
                    category=interval.category,
                    severity=interval.severity,
                    notes=interval.notes,
                    tolerant_detected=tolerant_detected,
                    nearest_representative_timestamp_us=nearest_timestamp,
                    nearest_representative_distance_us=nearest_distance,
                )
            )
    candidate_count = int(candidate_mask.sum())
    detected = sum(exact_detections)
    tolerant_detected = sum(tolerant_detections)
    total = len(intervals)
    inside_candidates = int(np.sum(candidate_mask & inside_gt))
    candidate_timestamps = timestamps[candidate_mask]
    return CandidateMetrics(
        total_intervals=total,
        detected_intervals=detected,
        missed_intervals=total - detected,
        interval_recall=detected / total if total else None,
        tolerant_detected_intervals=tolerant_detected,
        tolerant_missed_intervals=total - tolerant_detected,
        tolerant_interval_recall_5s=(tolerant_detected / total if total else None),
        candidate_samples=candidate_count,
        total_representative_samples=len(timestamps),
        candidate_sample_rate=(
            candidate_count / len(timestamps) if len(timestamps) else None
        ),
        candidate_samples_inside_gt=(inside_candidates if total else None),
        candidate_samples_outside_gt=(
            candidate_count - inside_candidates if total else None
        ),
        frame_candidate_precision=(
            inside_candidates / candidate_count if candidate_count else None
        ),
        category_recall=_recall_breakdown(
            intervals, exact_detections, tolerant_detections, "category"
        ),
        severity_recall=_recall_breakdown(
            intervals, exact_detections, tolerant_detections, "severity"
        ),
        semantic_target_category_recall=_target_recall(
            intervals,
            exact_detections,
            tolerant_detections,
        ),
        missed_interval_details=tuple(missed),
        temporal_workloads=tuple(
            _temporal_workload(
                candidate_timestamps,
                duration_us=duration_us,
                context_seconds=context,
                merge_gap_seconds=merge_gap,
                frames_per_region=frames_per_region,
            )
            for context, merge_gap in temporal_grid
        ),
    )


def _recall_breakdown(
    intervals: Sequence[GroundTruthInterval],
    exact: Sequence[bool],
    tolerant: Sequence[bool],
    attribute: Literal["category", "severity"],
) -> tuple[RecallBreakdown, ...]:
    grouped: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for interval, exact_detected, tolerant_detected in zip(
        intervals,
        exact,
        tolerant,
        strict=True,
    ):
        value = getattr(interval, attribute)
        if value is not None:
            grouped[value].append((exact_detected, tolerant_detected))
    return tuple(
        _recall_value(value, values) for value, values in sorted(grouped.items())
    )


def _target_recall(
    intervals: Sequence[GroundTruthInterval],
    exact: Sequence[bool],
    tolerant: Sequence[bool],
) -> tuple[RecallBreakdown, ...]:
    grouped: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for interval, exact_detected, tolerant_detected in zip(
        intervals,
        exact,
        tolerant,
        strict=True,
    ):
        category = _category_key(interval.category)
        if category in {"weapons", "drugs"}:
            grouped[category].append((exact_detected, tolerant_detected))
    return tuple(
        _recall_value(value, values) for value, values in sorted(grouped.items())
    )


def _recall_value(value: str, values: Sequence[tuple[bool, bool]]) -> RecallBreakdown:
    exact_count = sum(item[0] for item in values)
    tolerant_count = sum(item[1] for item in values)
    return RecallBreakdown(
        value=value,
        total_intervals=len(values),
        detected_intervals=exact_count,
        missed_intervals=len(values) - exact_count,
        interval_recall=exact_count / len(values),
        tolerant_detected_intervals=tolerant_count,
        tolerant_missed_intervals=len(values) - tolerant_count,
        tolerant_interval_recall=tolerant_count / len(values),
    )


def _temporal_workload(
    candidate_timestamps: np.ndarray,
    *,
    duration_us: int,
    context_seconds: float,
    merge_gap_seconds: float,
    frames_per_region: int,
) -> TemporalWorkload:
    if candidate_timestamps.size == 0:
        return TemporalWorkload(
            context_seconds=context_seconds,
            merge_gap_seconds=merge_gap_seconds,
            raw_candidate_samples=0,
            merged_candidate_regions=0,
            total_region_seconds=0.0,
            median_region_seconds=0.0,
            average_region_seconds=0.0,
            maximum_region_seconds=0.0,
            movie_fraction=0.0,
            frames_per_region=frames_per_region,
            estimated_vlm_images=0,
        )
    context_us = round(context_seconds * MICROSECONDS_PER_SECOND)
    merge_gap_us = round(merge_gap_seconds * MICROSECONDS_PER_SECOND)
    starts = np.maximum(0, candidate_timestamps - context_us)
    ends = np.minimum(duration_us, candidate_timestamps + context_us)
    new_region = np.empty(candidate_timestamps.size, dtype=bool)
    new_region[0] = True
    new_region[1:] = starts[1:] > ends[:-1] + merge_gap_us
    indices = np.flatnonzero(new_region)
    region_starts = starts[indices]
    region_ends = np.maximum.reduceat(ends, indices)
    durations = region_ends - region_starts
    total_us = int(durations.sum())
    regions = int(durations.size)
    return TemporalWorkload(
        context_seconds=context_seconds,
        merge_gap_seconds=merge_gap_seconds,
        raw_candidate_samples=int(candidate_timestamps.size),
        merged_candidate_regions=regions,
        total_region_seconds=total_us / MICROSECONDS_PER_SECOND,
        median_region_seconds=float(np.median(durations) / MICROSECONDS_PER_SECOND),
        average_region_seconds=total_us / regions / MICROSECONDS_PER_SECOND,
        maximum_region_seconds=float(durations.max() / MICROSECONDS_PER_SECOND),
        movie_fraction=total_us / duration_us,
        frames_per_region=frames_per_region,
        estimated_vlm_images=regions * frames_per_region,
    )


def _onnx_baselines() -> tuple[ONNXBaselinePolicy, ...]:
    return (
        ONNXBaselinePolicy(name="A", nsfw_threshold=0.10, nsfl_threshold=0.10),
        ONNXBaselinePolicy(name="B", nsfw_threshold=0.15, nsfl_threshold=0.10),
        ONNXBaselinePolicy(name="C", nsfw_threshold=0.20, nsfl_threshold=0.40),
        ONNXBaselinePolicy(name="D", nsfw_threshold=0.30, nsfl_threshold=0.30),
    )


def _pareto_summaries(
    results: Iterable[UnionPolicyEvaluation],
    *,
    recall_field: Literal["interval_recall", "tolerant_interval_recall_5s"],
    required_recall: float,
) -> tuple[ParetoPolicySummary, ...]:
    eligible = [
        result
        for result in results
        if getattr(result.metrics, recall_field) is not None
        and math.isclose(float(getattr(result.metrics, recall_field)), required_recall)
    ]
    eligible.sort(
        key=lambda result: (
            result.metrics.candidate_sample_rate
            if result.metrics.candidate_sample_rate is not None
            else math.inf,
            _best_workload(result.metrics.temporal_workloads).estimated_vlm_images,
            _best_workload(result.metrics.temporal_workloads).movie_fraction,
            result.onnx_policy.name,
            result.semantic_policy.strategy,
            result.semantic_policy.weapons_threshold,
            result.semantic_policy.drugs_threshold,
        )
    )
    return tuple(_pareto_summary(result) for result in eligible)


def _best_workload(workloads: Sequence[TemporalWorkload]) -> TemporalWorkload:
    return min(
        workloads,
        key=lambda workload: (
            workload.estimated_vlm_images,
            workload.movie_fraction,
            workload.context_seconds,
            workload.merge_gap_seconds,
        ),
    )


def _pareto_summary(result: UnionPolicyEvaluation) -> ParetoPolicySummary:
    workload = _best_workload(result.metrics.temporal_workloads)
    return ParetoPolicySummary(
        onnx_baseline=result.onnx_policy.name,
        semantic_strategy=result.semantic_policy.strategy,
        weapons_threshold=result.semantic_policy.weapons_threshold,
        drugs_threshold=result.semantic_policy.drugs_threshold,
        interval_recall=float(result.metrics.interval_recall or 0.0),
        tolerant_interval_recall=float(
            result.metrics.tolerant_interval_recall_5s or 0.0
        ),
        candidate_sample_rate=result.metrics.candidate_sample_rate,
        workload_context_seconds=workload.context_seconds,
        workload_merge_gap_seconds=workload.merge_gap_seconds,
        estimated_vlm_images=workload.estimated_vlm_images,
        merged_region_movie_fraction=workload.movie_fraction,
    )


def _highest_exact_recall(results: Sequence[UnionPolicyEvaluation]) -> float | None:
    values = [result.metrics.interval_recall for result in results]
    numeric = [value for value in values if value is not None]
    return max(numeric) if numeric else None


def _nearest_timestamp(
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
    index = int(np.argmin(distances))
    return int(timestamps[index]), int(distances[index])


def _category_key(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def _interval_sort_key(interval: GroundTruthInterval) -> tuple[int, int, str, str]:
    return (
        interval.start_us,
        interval.end_us,
        interval.category or "",
        interval.severity or "",
    )


def _metric_definitions() -> dict[str, str]:
    return {
        "semantic_scores": "TinyCLIP cosine similarities and scaled logits are raw semantic measurements, not probabilities.",
        "semantic_policy": "A semantic candidate is weapons_score >= weapons_threshold OR drugs_score >= drugs_threshold for one explicit aggregation strategy.",
        "union_policy": "A union candidate is an ONNX baseline candidate OR a TinyCLIP semantic candidate.",
        "interval_recall": "An interval is detected when at least one representative candidate is inside its inclusive bounds.",
        "tolerant_interval_recall_5s": "Interval recall after expanding annotations by the configured five-second tolerance and clamping to movie bounds.",
        "frame_candidate_precision": "Candidate representatives inside the exact union of annotations divided by candidates; this is a frame-level precision proxy only.",
        "temporal_workload": "Candidate timestamps are padded and merged only for an evaluation workload proxy; estimated VLM images equal merged regions times frames_per_region.",
        "pareto_sort": "Exact/tolerant qualifying policies are sorted by candidate rate, then the smallest image workload and movie fraction across the evaluated temporal grid. This is not a production recommendation.",
    }
