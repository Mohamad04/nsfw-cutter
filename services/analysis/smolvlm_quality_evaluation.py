"""Experimental real-frame SmolVLM candidate-event quality evaluation.

Frame reconstruction deliberately reuses the production-independent preprocessing
pipeline once. The resulting lossless low-resolution crops live only in an ignored
evaluation cache; no live analysis or persistent application contract depends on it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import shutil
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.analysis.cancellation import CancellationToken
from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    ExperimentalCandidateEventsArtifact,
)
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preflight import FileFingerprintService
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import FrameSample, PreprocessingConfig
from services.analysis.smolvlm_verifier import (
    EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    SmolVLMVerifier,
    VerificationStatus,
    VLMFrameDescriptor,
    VLMVerificationRequest,
    VLMVerificationRequestMetadata,
    VLMVerificationResult,
)
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    Stage1ScoreArtifact,
    write_json_artifact,
)

FRAME_CACHE_SCHEMA_VERSION = 1
QUALITY_REPORT_SCHEMA_VERSION = 1
PRIMARY_MAX_NEW_TOKENS = 64
RETRY_MAX_NEW_TOKENS = 96
TOLERANCE_US = 5_000_000


class SmolVLMQualityEvaluationError(RuntimeError):
    """Evaluation artifact, reconstruction, or metric contract is invalid."""


class FrameTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    frame_index: int = Field(ge=1, le=6)
    sample_id: str
    timestamp_us: int = Field(ge=0)
    expected_sample_reasons: tuple[str, ...]
    selection_reasons: tuple[str, ...]


class CachedSelectedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    frame_index: int = Field(ge=1, le=6)
    sample_id: str
    timestamp_us: int = Field(ge=0)
    source_pts: int | None
    owning_chunk_index: int = Field(ge=0)
    sample_reasons: tuple[str, ...]
    selection_reasons: tuple[str, ...]
    canvas_width: int = Field(gt=0)
    canvas_height: int = Field(gt=0)
    content_rect: tuple[int, int, int, int]
    cropped_width: int = Field(gt=0)
    cropped_height: int = Field(gt=0)
    relative_png_path: str
    png_sha256: str = Field(min_length=64, max_length=64)


class UnresolvedSelectedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: FrameTarget
    reason: str
    observed_sample_id_at_timestamp: str | None = None


class SelectedFrameCacheManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = FRAME_CACHE_SCHEMA_VERSION
    experimental: Literal[True] = True
    video_path: str
    video_filename: str
    video_duration_us: int = Field(gt=0)
    video_fingerprint: str
    event_artifact_sha256: str
    preprocessing_score_artifact_sha256: str
    preprocessing: PreprocessingConfig
    expected_event_count: int = Field(gt=0)
    expected_frame_reference_count: int = Field(gt=0)
    representatives_observed: int = Field(ge=0)
    entries: tuple[CachedSelectedFrame, ...]
    unresolved: tuple[UnresolvedSelectedFrame, ...]

    @property
    def all_references_resolved(self) -> bool:
        return len(self.entries) == self.expected_frame_reference_count and not self.unresolved


class SilverIntervalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interval_id: str
    start: str
    end: str
    start_us: int = Field(ge=0)
    end_us: int = Field(gt=0)
    category: str | None
    severity: str | None
    exact_overlap: bool
    tolerant_overlap_5s: bool


class VerificationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_splitting: bool
    max_new_tokens: int = Field(gt=0)
    syntactic_json_valid: bool
    pydantic_valid: bool
    failure_reason: str | None
    peak_cuda_allocated_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_reserved_bytes: int | None = Field(default=None, ge=0)
    result: VLMVerificationResult


class EventQualityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_count: int = Field(ge=1, le=6)
    selected_frame_timestamps_us: tuple[int, ...]
    selected_frame_paths: tuple[str, ...]
    selected_frame_selection_reasons: tuple[tuple[str, ...], ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    resolution_status: Literal["resolved", "unresolved"]
    resolution_error: str | None
    primary_attempt: VerificationAttempt | None
    truncation_retry_96: VerificationAttempt | None


class CategoryRecallMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    total_intervals: int = Field(ge=1)
    exact_unsafe_detected: int = Field(ge=0)
    exact_unsafe_recall: float = Field(ge=0.0, le=1.0)
    exact_category_detected: int = Field(ge=0)
    exact_category_aware_recall: float = Field(ge=0.0, le=1.0)
    tolerant_unsafe_detected: int = Field(ge=0)
    tolerant_unsafe_recall: float = Field(ge=0.0, le=1.0)
    tolerant_category_detected: int = Field(ge=0)
    tolerant_category_aware_recall: float = Field(ge=0.0, le=1.0)


class SilverIntervalEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    interval: SilverIntervalReference
    exact_overlapping_event_ids: tuple[str, ...]
    tolerant_overlapping_event_ids: tuple[str, ...]
    unsafe_detected_exact: bool
    category_detected_exact: bool
    unsafe_detected_tolerant: bool
    category_detected_tolerant: bool
    verified_unsafe_event_ids: tuple[str, ...]
    category_matching_event_ids: tuple[str, ...]


class LatencyByImageCount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_count: int = Field(ge=1, le=6)
    event_count: int = Field(ge=1)
    p50_total_seconds: float = Field(ge=0.0)
    mean_total_seconds: float = Field(ge=0.0)
    p90_total_seconds: float = Field(ge=0.0)
    p95_total_seconds: float = Field(ge=0.0)
    maximum_total_seconds: float = Field(ge=0.0)
    mean_generated_tokens: float = Field(ge=0.0)
    syntactic_json_rate: float = Field(ge=0.0, le=1.0)
    pydantic_valid_rate: float = Field(ge=0.0, le=1.0)


class QualitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_events: int = Field(ge=0)
    total_selected_images: int = Field(ge=0)
    resolved_events: int = Field(ge=0)
    unresolved_events: int = Field(ge=0)
    verified_unsafe: int = Field(ge=0)
    verified_safe: int = Field(ge=0)
    unverified: int = Field(ge=0)
    unverified_reasons: dict[str, int]
    syntactic_json_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    pydantic_valid_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_completion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    exact_unsafe_detected_intervals: int = Field(ge=0)
    exact_unsafe_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    exact_category_detected_intervals: int = Field(ge=0)
    exact_category_aware_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    tolerant_unsafe_detected_intervals: int = Field(ge=0)
    tolerant_unsafe_recall_5s: float | None = Field(default=None, ge=0.0, le=1.0)
    tolerant_category_detected_intervals: int = Field(ge=0)
    tolerant_category_aware_recall_5s: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    category_recall: tuple[CategoryRecallMetrics, ...]
    unlabeled_verified_unsafe: int = Field(ge=0)
    unlabeled_verified_safe: int = Field(ge=0)
    unlabeled_unverified: int = Field(ge=0)
    latency_by_image_count: tuple[LatencyByImageCount, ...]
    model_load_seconds: float = Field(ge=0.0)
    artifact_resolution_seconds: float = Field(ge=0.0)
    total_processor_seconds: float = Field(ge=0.0)
    total_generation_seconds: float = Field(ge=0.0)
    sequential_verifier_wall_seconds: float = Field(ge=0.0)
    mean_event_latency_seconds: float | None = Field(default=None, ge=0.0)
    peak_cuda_allocated_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_reserved_bytes: int | None = Field(default=None, ge=0)
    truncation_retries: int = Field(ge=0)
    successful_truncation_retries: int = Field(ge=0)


class DefaultSplittingComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    expected_categories: tuple[str, ...]
    original_image_count: int = Field(ge=1, le=6)
    compared_image_indices: tuple[int, ...] = Field(min_length=1, max_length=3)
    reduced_evidence_subset: bool
    split_disabled: VerificationAttempt
    default_splitting: VerificationAttempt


class SmolVLMRealQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = QUALITY_REPORT_SCHEMA_VERSION
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    video_fingerprint: str
    event_artifact_path: str
    event_artifact_sha256: str
    ground_truth_path: str
    ground_truth_sha256: str
    frame_cache_manifest_path: str
    model_provenance: dict[str, Any]
    verification_policy: dict[str, Any]
    generation_settings: dict[str, Any]
    events: tuple[EventQualityRecord, ...]
    silver_intervals: tuple[SilverIntervalEvaluation, ...]
    summary: QualitySummary
    default_splitting_comparison: tuple[DefaultSplittingComparison, ...]
    metric_notes: tuple[str, ...]


class SelectedFrameCacheConsumer:
    """Save only exact selected representatives; all other RGB is released immediately."""

    def __init__(self, targets: Sequence[FrameTarget], cache_root: Path) -> None:
        self.targets = {target.sample_id: target for target in targets}
        if len(self.targets) != len(targets):
            raise SmolVLMQualityEvaluationError(
                "Candidate-event artifact contains duplicate selected sample IDs."
            )
        self.target_timestamps = {target.timestamp_us for target in targets}
        self.cache_root = cache_root
        self.entries: dict[str, CachedSelectedFrame] = {}
        self.observed_at_target_timestamp: dict[int, str] = {}
        self.representatives_observed = 0

    def __call__(
        self,
        frame: ExtractedFrame,
        sample: FrameSample,
        cancellation: CancellationToken,
    ) -> None:
        cancellation.raise_if_cancelled()
        self.representatives_observed += 1
        sample_id = representative_sample_id(sample)
        if sample.timestamp_us in self.target_timestamps:
            self.observed_at_target_timestamp[sample.timestamp_us] = sample_id
        target = self.targets.get(sample_id)
        if target is None:
            return
        if sample_id in self.entries:
            raise SmolVLMQualityEvaluationError(
                f"Selected representative was emitted twice: {sample_id}"
            )
        if sample.timestamp_us != target.timestamp_us:
            raise SmolVLMQualityEvaluationError(
                f"Selected representative timestamp mismatch for {sample_id}."
            )
        actual_reasons = tuple(sorted(reason.value for reason in sample.sample_reasons))
        if actual_reasons != tuple(sorted(target.expected_sample_reasons)):
            raise SmolVLMQualityEvaluationError(
                f"Selected representative reasons changed for {sample_id}."
            )
        image = crop_representative_content(frame)
        event_dir = self.cache_root / "frames" / target.event_id.replace(":", "_")
        relative = Path("frames") / event_dir.name / (
            f"frame_{target.frame_index:02d}_{target.timestamp_us}.png"
        )
        output = self.cache_root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        _atomic_save_png(image, output)
        digest = sha256_file(output)
        self.entries[sample_id] = CachedSelectedFrame(
            event_id=target.event_id,
            frame_index=target.frame_index,
            sample_id=sample_id,
            timestamp_us=sample.timestamp_us,
            source_pts=sample.source_pts,
            owning_chunk_index=sample.owning_chunk_index,
            sample_reasons=actual_reasons,
            selection_reasons=target.selection_reasons,
            canvas_width=frame.width,
            canvas_height=frame.height,
            content_rect=frame.content_rect,
            cropped_width=image.width,
            cropped_height=image.height,
            relative_png_path=relative.as_posix(),
            png_sha256=digest,
        )
        image.close()


def load_quality_inputs(
    event_artifact_path: str | Path,
    ground_truth_path: str | Path,
    preprocessing_score_path: str | Path,
) -> tuple[ExperimentalCandidateEventsArtifact, GroundTruthArtifact, Stage1ScoreArtifact]:
    try:
        events_payload = json.loads(Path(event_artifact_path).read_text(encoding="utf-8"))
        ground_truth_payload = json.loads(
            Path(ground_truth_path).read_text(encoding="utf-8")
        )
        scores_payload = json.loads(
            Path(preprocessing_score_path).read_text(encoding="utf-8")
        )
        events = ExperimentalCandidateEventsArtifact.model_validate(events_payload)
        ground_truth = GroundTruthArtifact.model_validate(ground_truth_payload)
        scores = Stage1ScoreArtifact.model_validate(scores_payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise SmolVLMQualityEvaluationError(
            f"Unable to load quality-evaluation inputs ({type(exc).__name__}): {exc}"
        ) from exc
    if events.video_filename.casefold() != ground_truth.video.filename.casefold():
        raise SmolVLMQualityEvaluationError(
            "Candidate-event and ground-truth video filenames differ."
        )
    if events.video_filename.casefold() != scores.video.filename.casefold():
        raise SmolVLMQualityEvaluationError(
            "Candidate-event and preprocessing-score video filenames differ."
        )
    if events.video_duration_us != scores.video.duration_us:
        raise SmolVLMQualityEvaluationError(
            "Candidate-event and preprocessing-score durations differ."
        )
    return events, ground_truth, scores


def build_frame_targets(
    artifact: ExperimentalCandidateEventsArtifact,
) -> tuple[FrameTarget, ...]:
    targets: list[FrameTarget] = []
    for event in artifact.events:
        timestamps = [frame.sample.timestamp_us for frame in event.selected_frames]
        if timestamps != sorted(timestamps):
            raise SmolVLMQualityEvaluationError(
                f"Selected frames are not timestamp ordered for {event.event_id}."
            )
        for index, selected in enumerate(event.selected_frames, start=1):
            targets.append(
                FrameTarget(
                    event_id=event.event_id,
                    frame_index=index,
                    sample_id=selected.sample.sample_id,
                    timestamp_us=selected.sample.timestamp_us,
                    expected_sample_reasons=selected.sample.sample_reasons,
                    selection_reasons=selected.selection_reasons,
                )
            )
    if len({target.sample_id for target in targets}) != len(targets):
        raise SmolVLMQualityEvaluationError(
            "Selected sample identities must be unique for this evaluation cache."
        )
    return tuple(targets)


def reconstruct_selected_frames(
    video_path: str | Path,
    event_artifact: ExperimentalCandidateEventsArtifact,
    score_artifact: Stage1ScoreArtifact,
    *,
    event_artifact_path: str | Path,
    preprocessing_score_path: str | Path,
    cache_root: str | Path,
    preprocessing_service: MoviePreprocessingService | None = None,
    fingerprint_service: FileFingerprintService | None = None,
    cancellation: CancellationToken | None = None,
) -> SelectedFrameCacheManifest:
    resolved_video = Path(video_path).expanduser().resolve()
    resolved_cache = Path(cache_root).expanduser().resolve()
    if not resolved_video.is_file():
        raise FileNotFoundError(f"Movie does not exist: {resolved_video}")
    if resolved_video.name.casefold() != event_artifact.video_filename.casefold():
        raise SmolVLMQualityEvaluationError(
            "Movie filename differs from the candidate-event artifact."
        )
    if resolved_cache.exists() and any(resolved_cache.iterdir()):
        raise SmolVLMQualityEvaluationError(
            "Evaluation frame cache already exists and is non-empty; use cache reuse "
            "or choose another directory."
        )
    resolved_cache.mkdir(parents=True, exist_ok=True)
    token = cancellation or CancellationToken()
    fingerprint = (fingerprint_service or FileFingerprintService()).fingerprint(
        resolved_video, token
    )
    if score_artifact.video.fingerprint is not None and (
        fingerprint != score_artifact.video.fingerprint
    ):
        raise SmolVLMQualityEvaluationError(
            "Movie fingerprint differs from the exported Stage-1 score artifact."
        )
    targets = build_frame_targets(event_artifact)
    consumer = SelectedFrameCacheConsumer(targets, resolved_cache)
    result = (preprocessing_service or MoviePreprocessingService()).preprocess(
        resolved_video,
        config=score_artifact.preprocessing,
        cancellation=token,
        representative_callback=consumer,
    )
    if result.statistics.movie_duration_us != event_artifact.video_duration_us:
        raise SmolVLMQualityEvaluationError(
            "Reconstructed preprocessing duration differs from the event artifact."
        )
    unresolved = tuple(
        UnresolvedSelectedFrame(
            target=target,
            reason="exact selected sample identity was not reproduced",
            observed_sample_id_at_timestamp=consumer.observed_at_target_timestamp.get(
                target.timestamp_us
            ),
        )
        for target in targets
        if target.sample_id not in consumer.entries
    )
    ordered_entries = tuple(
        consumer.entries[target.sample_id]
        for target in targets
        if target.sample_id in consumer.entries
    )
    manifest = SelectedFrameCacheManifest(
        video_path=str(resolved_video),
        video_filename=resolved_video.name,
        video_duration_us=result.statistics.movie_duration_us,
        video_fingerprint=fingerprint,
        event_artifact_sha256=sha256_file(Path(event_artifact_path)),
        preprocessing_score_artifact_sha256=sha256_file(
            Path(preprocessing_score_path)
        ),
        preprocessing=score_artifact.preprocessing,
        expected_event_count=len(event_artifact.events),
        expected_frame_reference_count=len(targets),
        representatives_observed=consumer.representatives_observed,
        entries=ordered_entries,
        unresolved=unresolved,
    )
    write_json_artifact(manifest, resolved_cache / "manifest.json")
    return manifest


def load_and_validate_frame_cache(
    cache_root: str | Path,
    event_artifact: ExperimentalCandidateEventsArtifact,
    *,
    event_artifact_path: str | Path,
    preprocessing_score_path: str | Path,
) -> SelectedFrameCacheManifest:
    root = Path(cache_root).expanduser().resolve()
    try:
        manifest = SelectedFrameCacheManifest.model_validate_json(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise SmolVLMQualityEvaluationError(
            f"Evaluation frame-cache manifest is invalid ({type(exc).__name__})."
        ) from exc
    if manifest.event_artifact_sha256 != sha256_file(Path(event_artifact_path)):
        raise SmolVLMQualityEvaluationError(
            "Frame cache was produced from a different candidate-event artifact."
        )
    if manifest.preprocessing_score_artifact_sha256 != sha256_file(
        Path(preprocessing_score_path)
    ):
        raise SmolVLMQualityEvaluationError(
            "Frame cache was produced from a different preprocessing-score artifact."
        )
    if manifest.expected_event_count != len(event_artifact.events):
        raise SmolVLMQualityEvaluationError("Frame-cache event count changed.")
    expected_targets = build_frame_targets(event_artifact)
    if manifest.expected_frame_reference_count != len(expected_targets):
        raise SmolVLMQualityEvaluationError("Frame-cache reference count changed.")
    entry_by_id = {entry.sample_id: entry for entry in manifest.entries}
    for target in expected_targets:
        entry = entry_by_id.get(target.sample_id)
        if entry is None:
            continue
        if (
            entry.event_id != target.event_id
            or entry.frame_index != target.frame_index
            or entry.timestamp_us != target.timestamp_us
            or entry.selection_reasons != target.selection_reasons
        ):
            raise SmolVLMQualityEvaluationError(
                f"Cached selected-frame metadata changed: {target.sample_id}"
            )
        path = root / entry.relative_png_path
        if not path.is_file() or sha256_file(path) != entry.png_sha256:
            raise SmolVLMQualityEvaluationError(
                f"Cached selected image failed integrity validation: {target.sample_id}"
            )
        with Image.open(path) as image:
            image.load()
            if image.mode != "RGB" or image.size != (
                entry.cropped_width,
                entry.cropped_height,
            ):
                raise SmolVLMQualityEvaluationError(
                    f"Cached selected image contract changed: {target.sample_id}"
                )
            _, _, content_width, content_height = entry.content_rect
            if image.size != (content_width, content_height):
                raise SmolVLMQualityEvaluationError(
                    f"Cached image still contains padding: {target.sample_id}"
                )
    return manifest


def representative_sample_id(sample: FrameSample) -> str:
    source_pts = "none" if sample.source_pts is None else str(sample.source_pts)
    return (
        f"representative:{sample.owning_chunk_index}:"
        f"{sample.timestamp_us}:{source_pts}"
    )


def crop_representative_content(frame: ExtractedFrame) -> Image.Image:
    expected = frame.width * frame.height * 3
    if len(frame.rgb_bytes) != expected:
        raise SmolVLMQualityEvaluationError(
            "Representative RGB byte count does not match its dimensions."
        )
    left, top, width, height = frame.content_rect
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise SmolVLMQualityEvaluationError("Representative content rectangle is invalid.")
    if left + width > frame.width or top + height > frame.height:
        raise SmolVLMQualityEvaluationError(
            "Representative content rectangle exceeds the canvas."
        )
    canvas = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb_bytes)
    cropped = canvas.crop((left, top, left + width, top + height))
    canvas.close()
    return cropped


def evaluate_real_candidate_quality(
    event_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    event_artifact_path: str | Path,
    ground_truth_path: str | Path,
    frame_cache_root: str | Path,
    verifier: SmolVLMVerifier,
    image_splitting: bool = False,
    max_new_tokens: int = PRIMARY_MAX_NEW_TOKENS,
    retry_truncation: bool = True,
    run_default_comparison: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SmolVLMRealQualityReport:
    if event_artifact.video_filename.casefold() != ground_truth.video.filename.casefold():
        raise SmolVLMQualityEvaluationError(
            "Candidate events and ground truth refer to different videos."
        )
    cache_root = Path(frame_cache_root).expanduser().resolve()
    entry_by_sample_id = {entry.sample_id: entry for entry in frame_manifest.entries}
    runtime = verifier.runtime()
    records: list[EventQualityRecord] = []
    evaluation_started = time.perf_counter()
    for ordinal, event in enumerate(event_artifact.events, start=1):
        overlaps = match_event_to_ground_truth(
            event,
            ground_truth.intervals,
            movie_duration_us=event_artifact.video_duration_us,
        )
        entries = [
            entry_by_sample_id.get(selected.sample.sample_id)
            for selected in event.selected_frames
        ]
        missing = [
            selected.sample.sample_id
            for selected, entry in zip(event.selected_frames, entries, strict=True)
            if entry is None
        ]
        if missing:
            records.append(
                _unresolved_event_record(
                    event,
                    overlaps,
                    f"selected frame cache is missing: {', '.join(missing)}",
                )
            )
        else:
            resolved_entries = tuple(entry for entry in entries if entry is not None)
            request, images = build_verification_request(
                event,
                resolved_entries,
                cache_root,
            )
            primary = run_verification_attempt(
                runtime,
                request,
                max_new_tokens=max_new_tokens,
                image_splitting=image_splitting,
            )
            retry = None
            if retry_truncation and primary.result.truncated:
                retry = run_verification_attempt(
                    runtime,
                    request,
                    max_new_tokens=RETRY_MAX_NEW_TOKENS,
                    image_splitting=image_splitting,
                )
            for image in images:
                image.close()
            records.append(
                EventQualityRecord(
                    event_id=event.event_id,
                    start_timestamp_us=event.start_timestamp_us,
                    end_timestamp_us=event.end_timestamp_us,
                    selected_frame_count=len(resolved_entries),
                    selected_frame_timestamps_us=tuple(
                        entry.timestamp_us for entry in resolved_entries
                    ),
                    selected_frame_paths=tuple(
                        entry.relative_png_path for entry in resolved_entries
                    ),
                    selected_frame_selection_reasons=tuple(
                        entry.selection_reasons for entry in resolved_entries
                    ),
                    silver_overlaps=overlaps,
                    resolution_status="resolved",
                    resolution_error=None,
                    primary_attempt=primary,
                    truncation_retry_96=retry,
                )
            )
        if progress_callback is not None:
            progress_callback(ordinal, len(event_artifact.events))
    sequential_wall = time.perf_counter() - evaluation_started
    interval_results = evaluate_silver_intervals(
        ground_truth.intervals,
        records,
    )
    summary = summarize_quality(
        records,
        interval_results,
        model_load_seconds=verifier.model_load_seconds,
        artifact_resolution_seconds=verifier.artifact_resolution_seconds,
        sequential_verifier_wall_seconds=sequential_wall,
    )
    comparisons = (
        run_default_splitting_comparison(
            event_artifact.events,
            records,
            frame_manifest,
            cache_root=cache_root,
            runtime=runtime,
            max_new_tokens=max_new_tokens,
        )
        if run_default_comparison
        else ()
    )
    return SmolVLMRealQualityReport(
        video_filename=event_artifact.video_filename,
        video_duration_us=event_artifact.video_duration_us,
        video_fingerprint=frame_manifest.video_fingerprint,
        event_artifact_path=str(Path(event_artifact_path).resolve()),
        event_artifact_sha256=sha256_file(Path(event_artifact_path)),
        ground_truth_path=str(Path(ground_truth_path).resolve()),
        ground_truth_sha256=sha256_file(Path(ground_truth_path)),
        frame_cache_manifest_path=str((cache_root / "manifest.json").resolve()),
        model_provenance=runtime.provenance.model_dump(mode="json"),
        verification_policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY.model_dump(mode="json"),
        generation_settings={
            "device": runtime.provenance.device,
            "image_splitting": image_splitting,
            "max_new_tokens": max_new_tokens,
            "do_sample": False,
            "num_beams": 1,
            "temperature": None,
            "truncation_retry_max_new_tokens": (
                RETRY_MAX_NEW_TOKENS if retry_truncation else None
            ),
        },
        events=tuple(records),
        silver_intervals=interval_results,
        summary=summary,
        default_splitting_comparison=comparisons,
        metric_notes=(
            "Recall is measured only against manually supplied silver unsafe intervals.",
            "Events outside silver intervals are unlabeled outputs, not false positives or true negatives.",
            "Primary status/recall always uses the original 64-token attempt; 96-token truncation retries are retained separately.",
            "Default-splitting comparisons use at most three images; larger events are explicitly reduced for this diagnostic only.",
        ),
    )


def build_verification_request(
    event: CandidateEvent,
    entries: Sequence[CachedSelectedFrame],
    cache_root: Path,
    *,
    selected_indices: Sequence[int] | None = None,
) -> tuple[VLMVerificationRequest, tuple[Image.Image, ...]]:
    indices = tuple(selected_indices or range(1, len(entries) + 1))
    selected_entries = tuple(entries[index - 1] for index in indices)
    images: list[Image.Image] = []
    descriptors: list[VLMFrameDescriptor] = []
    for request_index, entry in enumerate(selected_entries, start=1):
        path = cache_root / entry.relative_png_path
        with Image.open(path) as source:
            source.load()
            image = source.copy()
        if image.mode != "RGB":
            image.close()
            raise SmolVLMQualityEvaluationError(
                f"Cached frame is not RGB: {entry.sample_id}"
            )
        images.append(image)
        descriptors.append(
            VLMFrameDescriptor(
                frame_index=request_index,
                timestamp_us=entry.timestamp_us,
                selection_reasons=entry.selection_reasons,
            )
        )
    return (
        VLMVerificationRequest(
            metadata=VLMVerificationRequestMetadata(
                event_id=event.event_id,
                frames=tuple(descriptors),
                policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
            ),
            images=tuple(images),
        ),
        tuple(images),
    )


def run_verification_attempt(
    runtime: Any,
    request: VLMVerificationRequest,
    *,
    max_new_tokens: int,
    image_splitting: bool,
) -> VerificationAttempt:
    peak_allocated = None
    peak_reserved = None
    torch_module = getattr(runtime, "torch", None)
    device = runtime.provenance.device
    if device == "cuda":
        torch_module.cuda.reset_peak_memory_stats()
    result = runtime.verify(
        request,
        max_new_tokens=max_new_tokens,
        image_splitting=image_splitting,
    )
    if device == "cuda":
        peak_allocated = int(torch_module.cuda.max_memory_allocated())
        peak_reserved = int(torch_module.cuda.max_memory_reserved())
    return VerificationAttempt(
        image_splitting=image_splitting,
        max_new_tokens=max_new_tokens,
        syntactic_json_valid=is_single_json_object(result.raw_generated_text),
        pydantic_valid=result.payload is not None,
        failure_reason=classify_unverified_reason(result),
        peak_cuda_allocated_bytes=peak_allocated,
        peak_cuda_reserved_bytes=peak_reserved,
        result=result,
    )


def match_event_to_ground_truth(
    event: CandidateEvent,
    intervals: Sequence[GroundTruthInterval],
    *,
    movie_duration_us: int,
) -> tuple[SilverIntervalReference, ...]:
    matches: list[SilverIntervalReference] = []
    for index, interval in enumerate(intervals):
        exact = ranges_overlap(
            event.start_timestamp_us,
            event.end_timestamp_us,
            interval.start_us,
            interval.end_us,
        )
        tolerant_start = max(0, interval.start_us - TOLERANCE_US)
        tolerant_end = min(movie_duration_us, interval.end_us + TOLERANCE_US)
        tolerant = ranges_overlap(
            event.start_timestamp_us,
            event.end_timestamp_us,
            tolerant_start,
            tolerant_end,
        )
        if exact or tolerant:
            matches.append(
                SilverIntervalReference(
                    interval_id=f"silver:{index:03d}",
                    start=interval.start,
                    end=interval.end,
                    start_us=interval.start_us,
                    end_us=interval.end_us,
                    category=interval.category,
                    severity=interval.severity,
                    exact_overlap=exact,
                    tolerant_overlap_5s=tolerant,
                )
            )
    return tuple(matches)


def ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a <= end_b and end_a >= start_b


def evaluate_silver_intervals(
    intervals: Sequence[GroundTruthInterval],
    records: Sequence[EventQualityRecord],
) -> tuple[SilverIntervalEvaluation, ...]:
    results: list[SilverIntervalEvaluation] = []
    for index, interval in enumerate(intervals):
        interval_id = f"silver:{index:03d}"
        exact_records = [
            record
            for record in records
            if any(
                overlap.interval_id == interval_id and overlap.exact_overlap
                for overlap in record.silver_overlaps
            )
        ]
        tolerant_records = [
            record
            for record in records
            if any(
                overlap.interval_id == interval_id and overlap.tolerant_overlap_5s
                for overlap in record.silver_overlaps
            )
        ]
        unsafe_exact = [record for record in exact_records if _verified_unsafe(record)]
        unsafe_tolerant = [
            record for record in tolerant_records if _verified_unsafe(record)
        ]
        category_exact = [
            record
            for record in unsafe_exact
            if _record_has_category(record, interval.category)
        ]
        category_tolerant = [
            record
            for record in unsafe_tolerant
            if _record_has_category(record, interval.category)
        ]
        reference = SilverIntervalReference(
            interval_id=interval_id,
            start=interval.start,
            end=interval.end,
            start_us=interval.start_us,
            end_us=interval.end_us,
            category=interval.category,
            severity=interval.severity,
            exact_overlap=True,
            tolerant_overlap_5s=True,
        )
        results.append(
            SilverIntervalEvaluation(
                interval=reference,
                exact_overlapping_event_ids=tuple(
                    record.event_id for record in exact_records
                ),
                tolerant_overlapping_event_ids=tuple(
                    record.event_id for record in tolerant_records
                ),
                unsafe_detected_exact=bool(unsafe_exact),
                category_detected_exact=bool(category_exact),
                unsafe_detected_tolerant=bool(unsafe_tolerant),
                category_detected_tolerant=bool(category_tolerant),
                verified_unsafe_event_ids=tuple(
                    record.event_id for record in unsafe_exact
                ),
                category_matching_event_ids=tuple(
                    record.event_id for record in category_exact
                ),
            )
        )
    return tuple(results)


def summarize_quality(
    records: Sequence[EventQualityRecord],
    interval_results: Sequence[SilverIntervalEvaluation],
    *,
    model_load_seconds: float,
    artifact_resolution_seconds: float,
    sequential_verifier_wall_seconds: float,
) -> QualitySummary:
    attempts = [record.primary_attempt for record in records if record.primary_attempt]
    statuses = Counter(attempt.result.status for attempt in attempts)
    unresolved_events = sum(record.resolution_status == "unresolved" for record in records)
    failure_reasons = Counter(
        attempt.failure_reason
        for attempt in attempts
        if attempt.result.status == VerificationStatus.UNVERIFIED
        and attempt.failure_reason is not None
    )
    if unresolved_events:
        failure_reasons["unresolved_frame_reconstruction"] += unresolved_events
    category_metrics = summarize_category_recall(interval_results)
    unlabeled = [
        record
        for record in records
        if not any(overlap.exact_overlap for overlap in record.silver_overlaps)
    ]
    unlabeled_statuses = Counter(
        record.primary_attempt.result.status
        for record in unlabeled
        if record.primary_attempt is not None
    )
    unlabeled_unresolved = sum(
        record.primary_attempt is None for record in unlabeled
    )
    latencies = summarize_latency_by_image_count(records)
    total = len(interval_results)
    completed = sum(
        attempt.result.status != VerificationStatus.UNVERIFIED for attempt in attempts
    )
    retries = [record.truncation_retry_96 for record in records if record.truncation_retry_96]
    return QualitySummary(
        total_events=len(records),
        total_selected_images=sum(record.selected_frame_count for record in records),
        resolved_events=len(records) - unresolved_events,
        unresolved_events=unresolved_events,
        verified_unsafe=statuses[VerificationStatus.VERIFIED_UNSAFE],
        verified_safe=statuses[VerificationStatus.VERIFIED_SAFE],
        unverified=statuses[VerificationStatus.UNVERIFIED] + unresolved_events,
        unverified_reasons=dict(sorted(failure_reasons.items())),
        syntactic_json_rate=(
            sum(attempt.syntactic_json_valid for attempt in attempts) / len(attempts)
            if attempts
            else None
        ),
        pydantic_valid_rate=(
            sum(attempt.pydantic_valid for attempt in attempts) / len(attempts)
            if attempts
            else None
        ),
        verification_completion_rate=(
            completed / len(records) if records else None
        ),
        exact_unsafe_detected_intervals=sum(
            result.unsafe_detected_exact for result in interval_results
        ),
        exact_unsafe_recall=(
            sum(result.unsafe_detected_exact for result in interval_results) / total
            if total
            else None
        ),
        exact_category_detected_intervals=sum(
            result.category_detected_exact for result in interval_results
        ),
        exact_category_aware_recall=(
            sum(result.category_detected_exact for result in interval_results) / total
            if total
            else None
        ),
        tolerant_unsafe_detected_intervals=sum(
            result.unsafe_detected_tolerant for result in interval_results
        ),
        tolerant_unsafe_recall_5s=(
            sum(result.unsafe_detected_tolerant for result in interval_results) / total
            if total
            else None
        ),
        tolerant_category_detected_intervals=sum(
            result.category_detected_tolerant for result in interval_results
        ),
        tolerant_category_aware_recall_5s=(
            sum(result.category_detected_tolerant for result in interval_results)
            / total
            if total
            else None
        ),
        category_recall=category_metrics,
        unlabeled_verified_unsafe=unlabeled_statuses[
            VerificationStatus.VERIFIED_UNSAFE
        ],
        unlabeled_verified_safe=unlabeled_statuses[VerificationStatus.VERIFIED_SAFE],
        unlabeled_unverified=(
            unlabeled_statuses[VerificationStatus.UNVERIFIED] + unlabeled_unresolved
        ),
        latency_by_image_count=latencies,
        model_load_seconds=model_load_seconds,
        artifact_resolution_seconds=artifact_resolution_seconds,
        total_processor_seconds=sum(
            attempt.result.processor_seconds for attempt in attempts
        ),
        total_generation_seconds=sum(
            attempt.result.generation_seconds for attempt in attempts
        ),
        sequential_verifier_wall_seconds=sequential_verifier_wall_seconds,
        mean_event_latency_seconds=(
            statistics.fmean(attempt.result.total_seconds for attempt in attempts)
            if attempts
            else None
        ),
        peak_cuda_allocated_bytes=_max_optional(
            attempt.peak_cuda_allocated_bytes for attempt in attempts
        ),
        peak_cuda_reserved_bytes=_max_optional(
            attempt.peak_cuda_reserved_bytes for attempt in attempts
        ),
        truncation_retries=len(retries),
        successful_truncation_retries=sum(
            retry.result.status != VerificationStatus.UNVERIFIED for retry in retries
        ),
    )


def summarize_category_recall(
    interval_results: Sequence[SilverIntervalEvaluation],
) -> tuple[CategoryRecallMetrics, ...]:
    grouped: dict[str, list[SilverIntervalEvaluation]] = defaultdict(list)
    for result in interval_results:
        if result.interval.category is not None:
            grouped[result.interval.category].append(result)
    metrics: list[CategoryRecallMetrics] = []
    for category in sorted(grouped):
        values = grouped[category]
        total = len(values)
        exact_unsafe = sum(value.unsafe_detected_exact for value in values)
        exact_category = sum(value.category_detected_exact for value in values)
        tolerant_unsafe = sum(value.unsafe_detected_tolerant for value in values)
        tolerant_category = sum(value.category_detected_tolerant for value in values)
        metrics.append(
            CategoryRecallMetrics(
                category=category,
                total_intervals=total,
                exact_unsafe_detected=exact_unsafe,
                exact_unsafe_recall=exact_unsafe / total,
                exact_category_detected=exact_category,
                exact_category_aware_recall=exact_category / total,
                tolerant_unsafe_detected=tolerant_unsafe,
                tolerant_unsafe_recall=tolerant_unsafe / total,
                tolerant_category_detected=tolerant_category,
                tolerant_category_aware_recall=tolerant_category / total,
            )
        )
    return tuple(metrics)


def summarize_latency_by_image_count(
    records: Sequence[EventQualityRecord],
) -> tuple[LatencyByImageCount, ...]:
    grouped: dict[int, list[VerificationAttempt]] = defaultdict(list)
    for record in records:
        if record.primary_attempt is not None:
            grouped[record.selected_frame_count].append(record.primary_attempt)
    result: list[LatencyByImageCount] = []
    for image_count in sorted(grouped):
        attempts = grouped[image_count]
        latencies = [attempt.result.total_seconds for attempt in attempts]
        result.append(
            LatencyByImageCount(
                image_count=image_count,
                event_count=len(attempts),
                p50_total_seconds=_percentile(latencies, 50),
                mean_total_seconds=statistics.fmean(latencies),
                p90_total_seconds=_percentile(latencies, 90),
                p95_total_seconds=_percentile(latencies, 95),
                maximum_total_seconds=max(latencies),
                mean_generated_tokens=statistics.fmean(
                    attempt.result.generated_token_count for attempt in attempts
                ),
                syntactic_json_rate=sum(
                    attempt.syntactic_json_valid for attempt in attempts
                )
                / len(attempts),
                pydantic_valid_rate=sum(
                    attempt.pydantic_valid for attempt in attempts
                )
                / len(attempts),
            )
        )
    return tuple(result)


def select_default_comparison_events(
    events: Sequence[CandidateEvent],
    records: Sequence[EventQualityRecord],
) -> tuple[str, ...]:
    record_by_id = {record.event_id: record for record in records}
    selected: list[str] = []
    target_categories = ("drugs", "weapons")
    for event in events:
        record = record_by_id[event.event_id]
        categories = {
            overlap.category
            for overlap in record.silver_overlaps
            if overlap.exact_overlap
        }
        if categories.intersection(target_categories):
            selected.append(event.event_id)
    for category in ("nudity", "sexual_content", "violence", "graphic_violence"):
        candidates = [
            event
            for event in events
            if event.event_id not in selected
            and any(
                overlap.exact_overlap and overlap.category == category
                for overlap in record_by_id[event.event_id].silver_overlaps
            )
        ]
        candidates.sort(
            key=lambda event: (
                len(event.selected_frames) not in {1, 3},
                len(event.selected_frames),
                event.event_id,
            )
        )
        selected.extend(event.event_id for event in candidates[:2])
    return tuple(selected)


def run_default_splitting_comparison(
    events: Sequence[CandidateEvent],
    records: Sequence[EventQualityRecord],
    manifest: SelectedFrameCacheManifest,
    *,
    cache_root: Path,
    runtime: Any,
    max_new_tokens: int,
) -> tuple[DefaultSplittingComparison, ...]:
    event_by_id = {event.event_id: event for event in events}
    record_by_id = {record.event_id: record for record in records}
    entry_by_id = {entry.sample_id: entry for entry in manifest.entries}
    comparisons: list[DefaultSplittingComparison] = []
    for event_id in select_default_comparison_events(events, records):
        event = event_by_id[event_id]
        entries = tuple(
            entry_by_id[selected.sample.sample_id] for selected in event.selected_frames
        )
        indices = comparison_frame_indices(len(entries))
        request, images = build_verification_request(
            event,
            entries,
            cache_root,
            selected_indices=indices,
        )
        disabled = run_verification_attempt(
            runtime,
            request,
            max_new_tokens=max_new_tokens,
            image_splitting=False,
        )
        default = run_verification_attempt(
            runtime,
            request,
            max_new_tokens=max_new_tokens,
            image_splitting=True,
        )
        for image in images:
            image.close()
        expected = tuple(
            sorted(
                {
                    overlap.category
                    for overlap in record_by_id[event_id].silver_overlaps
                    if overlap.exact_overlap and overlap.category is not None
                }
            )
        )
        comparisons.append(
            DefaultSplittingComparison(
                event_id=event_id,
                expected_categories=expected,
                original_image_count=len(entries),
                compared_image_indices=indices,
                reduced_evidence_subset=len(entries) > 3,
                split_disabled=disabled,
                default_splitting=default,
            )
        )
    return tuple(comparisons)


def comparison_frame_indices(image_count: int) -> tuple[int, ...]:
    if not 1 <= image_count <= 6:
        raise ValueError("comparison image count must be between 1 and 6")
    if image_count <= 3:
        return tuple(range(1, image_count + 1))
    middle = (image_count + 1) // 2
    return (1, middle, image_count)


def write_quality_csv(report: SmolVLMRealQualityReport, path: str | Path) -> Path:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "event_id",
            "start_timestamp_us",
            "end_timestamp_us",
            "image_count",
            "silver_categories",
            "status",
            "categories",
            "severity",
            "syntactic_json_valid",
            "pydantic_valid",
            "failure_reason",
            "processor_seconds",
            "generation_seconds",
            "total_seconds",
            "generated_tokens",
            "visual_blocks",
            "input_length",
        )
    )
    for record in report.events:
        attempt = record.primary_attempt
        result = attempt.result if attempt is not None else None
        payload = result.payload if result is not None else None
        writer.writerow(
            (
                record.event_id,
                record.start_timestamp_us,
                record.end_timestamp_us,
                record.selected_frame_count,
                "|".join(
                    sorted(
                        {
                            overlap.category
                            for overlap in record.silver_overlaps
                            if overlap.exact_overlap and overlap.category
                        }
                    )
                ),
                result.status if result is not None else "unresolved",
                "|".join(payload.categories) if payload is not None else "",
                payload.severity if payload is not None else "",
                attempt.syntactic_json_valid if attempt is not None else False,
                attempt.pydantic_valid if attempt is not None else False,
                attempt.failure_reason if attempt is not None else record.resolution_error,
                result.processor_seconds if result is not None else "",
                result.generation_seconds if result is not None else "",
                result.total_seconds if result is not None else "",
                result.generated_token_count if result is not None else "",
                (
                    result.expansion.visual_block_count
                    if result is not None and result.expansion is not None
                    else ""
                ),
                (
                    result.expansion.input_sequence_length
                    if result is not None and result.expansion is not None
                    else ""
                ),
            )
        )
    output_path = Path(path).expanduser().resolve()
    _atomic_write_text(output_path, output.getvalue())
    return output_path


def write_missed_interval_review(
    report: SmolVLMRealQualityReport,
    *,
    frame_cache_root: str | Path,
    output_dir: str | Path,
) -> Path | None:
    missed = [
        result for result in report.silver_intervals if not result.unsafe_detected_exact
    ]
    if not missed:
        return None
    cache_root = Path(frame_cache_root).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise SmolVLMQualityEvaluationError(
            "Missed-interval review directory already exists and is non-empty."
        )
    root.mkdir(parents=True, exist_ok=True)
    records = {record.event_id: record for record in report.events}
    index_payload: list[dict[str, Any]] = []
    for missed_interval in missed:
        interval = missed_interval.interval
        interval_dir = root / interval.interval_id.replace(":", "_")
        interval_dir.mkdir(parents=True, exist_ok=True)
        review_events: list[dict[str, Any]] = []
        contact_items: list[tuple[Image.Image, str]] = []
        for event_id in missed_interval.exact_overlapping_event_ids:
            record = records[event_id]
            copied_paths: list[str] = []
            for index, (relative_path, timestamp) in enumerate(
                zip(
                    record.selected_frame_paths,
                    record.selected_frame_timestamps_us,
                    strict=True,
                ),
                start=1,
            ):
                source = cache_root / relative_path
                destination = interval_dir / (
                    f"{event_id.replace(':', '_')}_frame_{index:02d}_{timestamp}.png"
                )
                shutil.copy2(source, destination)
                copied_paths.append(destination.name)
                with Image.open(source) as image:
                    image.load()
                    contact_items.append(
                        (image.copy(), f"{event_id} F{index} {timestamp / 1e6:.3f}s")
                    )
            review_events.append(
                {
                    "event_id": event_id,
                    "event_start_timestamp_us": record.start_timestamp_us,
                    "event_end_timestamp_us": record.end_timestamp_us,
                    "selected_frame_timestamps_us": record.selected_frame_timestamps_us,
                    "selection_reasons": record.selected_frame_selection_reasons,
                    "copied_frame_paths": copied_paths,
                    "primary_attempt": (
                        record.primary_attempt.model_dump(mode="json")
                        if record.primary_attempt is not None
                        else None
                    ),
                }
            )
        contact_sheet = None
        if contact_items:
            contact_sheet = interval_dir / "contact-sheet.png"
            _write_contact_sheet(contact_items, contact_sheet)
            for image, _ in contact_items:
                image.close()
        metadata = {
            "experimental": True,
            "interval": interval.model_dump(mode="json"),
            "events": review_events,
            "manual_review_question": (
                "Do the selected low-resolution images visibly contain the annotated "
                "unsafe evidence? This artifact does not decide whether a miss belongs "
                "to frame selection or the VLM."
            ),
            "contact_sheet": contact_sheet.name if contact_sheet else None,
        }
        _atomic_write_text(
            interval_dir / "metadata.json",
            json.dumps(metadata, indent=2),
        )
        index_payload.append(
            {
                "interval_id": interval.interval_id,
                "category": interval.category,
                "start": interval.start,
                "end": interval.end,
                "directory": interval_dir.name,
            }
        )
    _atomic_write_text(
        root / "index.json",
        json.dumps({"experimental": True, "missed_intervals": index_payload}, indent=2),
    )
    return root


def cleanup_evaluation_frame_cache(cache_root: str | Path) -> None:
    root = Path(cache_root).expanduser().resolve()
    if not root.exists():
        return
    manifest = root / "manifest.json"
    if not manifest.is_file():
        raise SmolVLMQualityEvaluationError(
            "Refusing cleanup: target is not a recognized evaluation frame cache."
        )
    shutil.rmtree(root)


def classify_unverified_reason(result: VLMVerificationResult) -> str | None:
    if result.status != VerificationStatus.UNVERIFIED:
        return None
    error = (result.error or "").casefold()
    if result.truncated or "max_new_tokens" in error:
        return "truncation"
    if "jsondecodeerror" in error or "expecting value" in error:
        return "malformed_json"
    if "outside the policy" in error or "unknown category" in error:
        return "unknown_category"
    if "severity" in error:
        return "invalid_severity"
    if "evidence frame" in error or "evidence_frame" in error:
        return "invalid_evidence_index"
    if "cancel" in error:
        return "cancellation"
    if "model generation failed" in error or "processing failed" in error:
        return "model_runtime_failure"
    return "schema_validation"


def is_single_json_object(raw_text: str) -> bool:
    try:
        decoded = json.loads(raw_text.strip())
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(decoded, dict)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(4 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SmolVLMQualityEvaluationError(
            f"Unable to hash evaluation artifact: {path}"
        ) from exc
    return digest.hexdigest()


def _unresolved_event_record(
    event: CandidateEvent,
    overlaps: tuple[SilverIntervalReference, ...],
    error: str,
) -> EventQualityRecord:
    return EventQualityRecord(
        event_id=event.event_id,
        start_timestamp_us=event.start_timestamp_us,
        end_timestamp_us=event.end_timestamp_us,
        selected_frame_count=len(event.selected_frames),
        selected_frame_timestamps_us=tuple(
            frame.sample.timestamp_us for frame in event.selected_frames
        ),
        selected_frame_paths=(),
        selected_frame_selection_reasons=tuple(
            frame.selection_reasons for frame in event.selected_frames
        ),
        silver_overlaps=overlaps,
        resolution_status="unresolved",
        resolution_error=error,
        primary_attempt=None,
        truncation_retry_96=None,
    )


def _verified_unsafe(record: EventQualityRecord) -> bool:
    return bool(
        record.primary_attempt is not None
        and record.primary_attempt.result.status == VerificationStatus.VERIFIED_UNSAFE
    )


def _record_has_category(record: EventQualityRecord, category: str | None) -> bool:
    if category is None or record.primary_attempt is None:
        return False
    payload = record.primary_attempt.result.payload
    return payload is not None and category in payload.categories


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percentile / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _max_optional(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _atomic_save_png(image: Image.Image, output: Path) -> None:
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        image.save(temporary, format="PNG", compress_level=6)
        os.replace(temporary, output)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _write_contact_sheet(items: Sequence[tuple[Image.Image, str]], output: Path) -> None:
    thumb_width = 240
    label_height = 28
    columns = min(3, len(items))
    rows = math.ceil(len(items) / columns)
    prepared: list[tuple[Image.Image, str]] = []
    max_height = 1
    for image, label in items:
        thumbnail = image.copy()
        thumbnail.thumbnail((thumb_width, 180), Image.Resampling.LANCZOS)
        max_height = max(max_height, thumbnail.height)
        prepared.append((thumbnail, label))
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, rows * (max_height + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, (thumbnail, label) in enumerate(prepared):
        column = index % columns
        row = index // columns
        x = column * thumb_width
        y = row * (max_height + label_height)
        sheet.paste(thumbnail, (x, y))
        draw.text((x + 4, y + max_height + 4), label, fill="black")
        thumbnail.close()
    _atomic_save_png(sheet, output)
    sheet.close()
