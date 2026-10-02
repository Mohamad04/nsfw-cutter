"""Experimental cached-frame SmolVLM evidence-map prompt ablation."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    ExperimentalCandidateEventsArtifact,
)
from services.analysis.smolvlm_quality_evaluation import (
    SelectedFrameCacheManifest,
    SilverIntervalReference,
    build_verification_request,
    match_event_to_ground_truth,
)
from services.analysis.smolvlm_verifier import (
    RawSmolVLMGeneration,
    SmolVLMVerifier,
    VLMVerificationRequest,
    VLMVerificationRequestMetadata,
)
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
)

PRIMARY_MAX_NEW_TOKENS = 64
RETRY_MAX_NEW_TOKENS = 96
COLLAPSE_DIAGNOSTIC_FRACTION = 0.80
CATEGORY_IDS = (
    "nudity",
    "sexual_content",
    "violence",
    "graphic_violence",
    "weapons",
    "drugs",
)
CATEGORY_DEFINITIONS = {
    "nudity": "visible exposed intimate body parts or explicit nudity",
    "sexual_content": "visible sexual activity or strongly sexual physical behavior",
    "violence": "visible physical attack, fighting, assault, or violent action",
    "graphic_violence": "visible blood, gore, severe injury, or graphic violent harm",
    "weapons": "visible firearm, gun, weapon, weapon cache, or weapon being aimed or used",
    "drugs": "visible illegal drug use, marijuana use, drug substances, or drug paraphernalia",
}


class SmolVLMPromptAblationError(RuntimeError):
    """Cached inputs or evidence-map experiment contracts are invalid."""


class PromptVariantId(StrEnum):
    MINIMAL = "minimal_evidence_map"
    DEFINED = "defined_evidence_map"
    HIGH_RECALL = "high_recall_defined_evidence_map"
    QUESTION_FIRST = "question_first_evidence_map"


class PromptVariantDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_id: PromptVariantId
    description: str
    includes_definitions: bool
    high_recall_instruction: bool
    question_first: bool
    output_contract_text: str


PROMPT_VARIANTS = (
    PromptVariantDefinition(
        variant_id=PromptVariantId.MINIMAL,
        description="Minimal category names and evidence-map output contract.",
        includes_definitions=False,
        high_recall_instruction=False,
        question_first=False,
        output_contract_text="category names only; no examples",
    ),
    PromptVariantDefinition(
        variant_id=PromptVariantId.DEFINED,
        description="Evidence map with concise visual category definitions.",
        includes_definitions=True,
        high_recall_instruction=False,
        question_first=False,
        output_contract_text="concise definitions; no examples",
    ),
    PromptVariantDefinition(
        variant_id=PromptVariantId.HIGH_RECALL,
        description="Defined evidence map plus an experimental high-recall instruction.",
        includes_definitions=True,
        high_recall_instruction=True,
        question_first=False,
        output_contract_text="concise definitions and high-recall instruction; no examples",
    ),
    PromptVariantDefinition(
        variant_id=PromptVariantId.QUESTION_FIRST,
        description="Question-first defined evidence map.",
        includes_definitions=True,
        high_recall_instruction=False,
        question_first=True,
        output_contract_text="question-first concise definitions; no examples",
    ),
)


class CategoryEvidenceMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nudity: tuple[StrictInt, ...] = Field(max_length=6)
    sexual_content: tuple[StrictInt, ...] = Field(max_length=6)
    violence: tuple[StrictInt, ...] = Field(max_length=6)
    graphic_violence: tuple[StrictInt, ...] = Field(max_length=6)
    weapons: tuple[StrictInt, ...] = Field(max_length=6)
    drugs: tuple[StrictInt, ...] = Field(max_length=6)

    @field_validator("*", mode="after")
    @classmethod
    def unique_positive_indices(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) != len(set(values)):
            raise ValueError("category evidence indices must be unique")
        if any(index < 1 for index in values):
            raise ValueError("category evidence indices must be positive")
        return values

    def categories(self) -> tuple[str, ...]:
        return tuple(
            category for category in CATEGORY_IDS if getattr(self, category)
        )

    def all_indices(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    index
                    for category in CATEGORY_IDS
                    for index in getattr(self, category)
                }
            )
        )


class EvidenceMapPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category_evidence: CategoryEvidenceMap

    @property
    def derived_categories(self) -> tuple[str, ...]:
        return self.category_evidence.categories()

    @property
    def derived_unsafe(self) -> bool:
        return bool(self.derived_categories)


class EvidenceMapAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_new_tokens: int = Field(gt=0)
    strict_json_valid: bool
    pydantic_valid: bool
    status: Literal["detected", "no_evidence", "unverified"]
    payload: EvidenceMapPayload | None
    derived_categories: tuple[str, ...]
    derived_unsafe: bool
    evidence_timestamps_us: dict[str, tuple[int, ...]]
    validation_error: str | None
    generation: RawSmolVLMGeneration


class EvidenceMapEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    variant_id: PromptVariantId
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    primary_attempt: EvidenceMapAttempt
    truncation_retry_96: EvidenceMapAttempt | None

    @property
    def effective_attempt(self) -> EvidenceMapAttempt:
        if self.primary_attempt.generation.truncated and self.truncation_retry_96:
            return self.truncation_retry_96
        return self.primary_attempt


class EvidenceCategoryRecall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    total_intervals: int = Field(ge=1)
    unsafe_detected: int = Field(ge=0)
    unsafe_recall: float = Field(ge=0.0, le=1.0)
    category_detected: int = Field(ge=0)
    category_aware_recall: float = Field(ge=0.0, le=1.0)


class OutputCollapseDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_count: int = Field(ge=1)
    unique_raw_outputs: int = Field(ge=1)
    most_common_exact_output: str
    most_common_exact_frequency: int = Field(ge=1)
    unique_normalized_outputs: int = Field(ge=1)
    most_common_normalized_output: str
    most_common_normalized_frequency: int = Field(ge=1)
    most_common_normalized_fraction: float = Field(ge=0.0, le=1.0)
    diagnostic_collapse_flag: bool
    diagnostic_flag_fraction: float = COLLAPSE_DIAGNOSTIC_FRACTION


class PromptVariantMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    variant_id: PromptVariantId
    event_count: int = Field(ge=1)
    primary_strict_json_rate: float = Field(ge=0.0, le=1.0)
    primary_pydantic_valid_rate: float = Field(ge=0.0, le=1.0)
    effective_strict_json_rate: float = Field(ge=0.0, le=1.0)
    effective_pydantic_valid_rate: float = Field(ge=0.0, le=1.0)
    detected_intervals: int = Field(ge=0)
    total_intervals: int = Field(ge=1)
    known_unsafe_recall: float = Field(ge=0.0, le=1.0)
    category_detected_intervals: int = Field(ge=0)
    category_aware_recall: float = Field(ge=0.0, le=1.0)
    category_recall: tuple[EvidenceCategoryRecall, ...]
    unverified_events: int = Field(ge=0)
    primary_generated_tokens: int = Field(ge=0)
    retry_generated_tokens: int = Field(ge=0)
    total_cuda_seconds: float = Field(ge=0.0)
    collapse: OutputCollapseDiagnostics


class PromptVariantEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    definition: PromptVariantDefinition
    metrics: PromptVariantMetrics
    events: tuple[EvidenceMapEventResult, ...]


class SmolVLMPromptAblationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    event_artifact_path: str
    ground_truth_path: str
    frame_cache_manifest_path: str
    model_provenance: dict[str, Any]
    fixed_runtime_contract: dict[str, Any]
    known_silver_event_count: int = Field(ge=1)
    variants: tuple[PromptVariantEvaluation, ...]
    sorted_variant_ids: tuple[PromptVariantId, ...]
    best_measured_prompt_variant: PromptVariantId
    metric_notes: tuple[str, ...]


class FullRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_events: int = Field(ge=1)
    total_images: int = Field(ge=1)
    events_with_categories: int = Field(ge=0)
    events_without_categories: int = Field(ge=0)
    unverified_events: int = Field(ge=0)
    category_frequency: dict[str, int]
    effective_strict_json_rate: float = Field(ge=0.0, le=1.0)
    effective_pydantic_valid_rate: float = Field(ge=0.0, le=1.0)
    total_cuda_seconds: float = Field(ge=0.0)
    collapse: OutputCollapseDiagnostics
    known_silver_metrics: PromptVariantMetrics


class SmolVLMEvidenceMapFullReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    variant: PromptVariantDefinition
    video_filename: str
    video_duration_us: int = Field(gt=0)
    model_provenance: dict[str, Any]
    frame_cache_manifest_path: str
    events: tuple[EvidenceMapEventResult, ...]
    summary: FullRunSummary
    unlabeled_output_note: str


def parse_evidence_map_json(
    raw_text: str,
    *,
    frame_count: int,
) -> EvidenceMapPayload:
    decoded = json.loads(raw_text.strip())
    if not isinstance(decoded, dict):
        raise TypeError("generated evidence map must be exactly one JSON object")
    payload = EvidenceMapPayload.model_validate_json(raw_text.strip(), strict=True)
    if any(index > frame_count for index in payload.category_evidence.all_indices()):
        raise ValueError("generated evidence references an unavailable frame")
    return payload


def build_evidence_map_conversation(
    metadata: VLMVerificationRequestMetadata,
    definition: PromptVariantDefinition,
) -> list[dict[str, Any]]:
    if definition.question_first:
        task = (
            "For each allowed category, determine which supplied frames contain "
            "visible evidence."
        )
    else:
        task = "Inspect every supplied frame for visible evidence in the allowed categories."
    instructions = [
        task,
        "The images are one time-ordered event and are labeled Frame 1 through Frame N.",
        "A category may appear in multiple frames and multiple categories may be present.",
        "Report only visible evidence; do not infer unseen events from dialogue or context.",
    ]
    if definition.includes_definitions:
        instructions.append(
            "Visual definitions: "
            + "; ".join(
                f"{category.upper()}: {CATEGORY_DEFINITIONS[category]}"
                for category in CATEGORY_IDS
            )
            + "."
        )
    else:
        instructions.append("Allowed category names: " + ", ".join(CATEGORY_IDS) + ".")
    if definition.high_recall_instruction:
        instructions.append(
            "If a supplied frame contains plausible visible evidence of an allowed "
            "unsafe category, include that category rather than omitting it merely "
            "because the image is ambiguous."
        )
    content: list[dict[str, str]] = [
        {"type": "text", "text": " ".join(instructions) + "\n"}
    ]
    for frame in metadata.frames:
        content.extend(
            (
                {"type": "text", "text": f"Frame {frame.frame_index}:\n"},
                {"type": "image"},
            )
        )
    content.append(
        {
            "type": "text",
            "text": (
                "Return only one JSON object containing exactly one field named "
                "category_evidence. Its value must be an object containing exactly "
                "these six fields: nudity, sexual_content, violence, "
                "graphic_violence, weapons, drugs. Every field value must be a JSON "
                "array of unique 1-based supplied Frame integers. Use an empty JSON "
                "array when a category has no visible evidence. Do not include any "
                "other field, prose, markdown, or timestamp."
            ),
        }
    )
    return [{"role": "user", "content": content}]


def run_evidence_map_attempt(
    runtime: Any,
    request: VLMVerificationRequest,
    definition: PromptVariantDefinition,
    *,
    max_new_tokens: int,
) -> EvidenceMapAttempt:
    conversation = build_evidence_map_conversation(request.metadata, definition)
    generation = runtime.generate_raw(
        request,
        conversation,
        max_new_tokens=max_new_tokens,
        image_splitting=False,
    )
    if generation.error is not None or generation.truncated:
        return _unverified_attempt(
            generation,
            max_new_tokens=max_new_tokens,
            error=generation.error or "generation was truncated",
        )
    strict_json = False
    try:
        strict_json = isinstance(json.loads(generation.raw_generated_text.strip()), dict)
        payload = parse_evidence_map_json(
            generation.raw_generated_text,
            frame_count=len(request.metadata.frames),
        )
    except Exception as exc:  # noqa: BLE001 - generated-output trust boundary
        return _unverified_attempt(
            generation,
            max_new_tokens=max_new_tokens,
            error=f"{type(exc).__name__}: {exc}",
            strict_json_valid=strict_json,
        )
    evidence_timestamps = {
        category: tuple(
            request.metadata.frames[index - 1].timestamp_us
            for index in getattr(payload.category_evidence, category)
        )
        for category in payload.derived_categories
    }
    return EvidenceMapAttempt(
        max_new_tokens=max_new_tokens,
        strict_json_valid=True,
        pydantic_valid=True,
        status="detected" if payload.derived_unsafe else "no_evidence",
        payload=payload,
        derived_categories=payload.derived_categories,
        derived_unsafe=payload.derived_unsafe,
        evidence_timestamps_us=evidence_timestamps,
        validation_error=None,
        generation=generation,
    )


def evaluate_prompt_ablation(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    event_artifact_path: str | Path,
    ground_truth_path: str | Path,
    frame_cache_root: str | Path,
    verifier: SmolVLMVerifier,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[SmolVLMPromptAblationReport, SmolVLMEvidenceMapFullReport]:
    runtime = verifier.runtime()
    if (
        runtime.provenance.device != "cuda"
        or runtime.provenance.model_dtype != "float32"
        or runtime.provenance.attention_implementation != "sdpa"
    ):
        raise SmolVLMPromptAblationError(
            "Prompt ablation requires the fixed CUDA/FP32/SDPA runtime contract."
        )
    exact_events = tuple(
        event
        for event in events_artifact.events
        if any(
            overlap.exact_overlap
            for overlap in match_event_to_ground_truth(
                event,
                ground_truth.intervals,
                movie_duration_us=events_artifact.video_duration_us,
            )
        )
    )
    evaluations = tuple(
        _evaluate_variant(
            definition,
            exact_events,
            events_artifact,
            ground_truth,
            frame_manifest,
            frame_cache_root=Path(frame_cache_root).resolve(),
            runtime=runtime,
            progress_callback=progress_callback,
        )
        for definition in PROMPT_VARIANTS
    )
    ordered = tuple(
        sorted(
            evaluations,
            key=lambda item: (
                -item.metrics.category_aware_recall,
                -item.metrics.known_unsafe_recall,
                -item.metrics.effective_pydantic_valid_rate,
                -item.metrics.effective_strict_json_rate,
                item.metrics.unverified_events,
                item.metrics.total_cuda_seconds,
                item.definition.variant_id.value,
            ),
        )
    )
    best = ordered[0].definition
    full_evaluation = _evaluate_variant(
        best,
        events_artifact.events,
        events_artifact,
        ground_truth,
        frame_manifest,
        frame_cache_root=Path(frame_cache_root).resolve(),
        runtime=runtime,
        progress_callback=progress_callback,
    )
    full_report = _build_full_report(
        full_evaluation,
        events_artifact,
        ground_truth,
        frame_cache_root=frame_cache_root,
    )
    report = SmolVLMPromptAblationReport(
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        event_artifact_path=str(Path(event_artifact_path).resolve()),
        ground_truth_path=str(Path(ground_truth_path).resolve()),
        frame_cache_manifest_path=str(
            Path(frame_cache_root).resolve() / "manifest.json"
        ),
        model_provenance=runtime.provenance.model_dump(mode="json"),
        fixed_runtime_contract={
            "device": "cuda",
            "dtype": "float32",
            "attention": "sdpa",
            "image_splitting": False,
            "do_sample": False,
            "num_beams": 1,
            "primary_max_new_tokens": PRIMARY_MAX_NEW_TOKENS,
            "truncation_retry_max_new_tokens": RETRY_MAX_NEW_TOKENS,
        },
        known_silver_event_count=len(exact_events),
        variants=evaluations,
        sorted_variant_ids=tuple(item.definition.variant_id for item in ordered),
        best_measured_prompt_variant=best.variant_id,
        metric_notes=(
            "Only exact silver-overlap events are used to rank prompt variants.",
            "An interval is detected when an overlapping event has any validated non-empty category evidence.",
            "Events outside silver intervals remain unlabeled in the full run.",
            "The collapse flag is diagnostic only and uses an explicitly reported 80% dominant-output fraction.",
        ),
    )
    return report, full_report


def write_prompt_ablation_csv(
    report: SmolVLMPromptAblationReport,
    path: str | Path,
) -> Path:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "variant_id",
            "known_silver_events",
            "known_unsafe_recall",
            "category_aware_recall",
            "effective_json_rate",
            "effective_pydantic_rate",
            "unverified_events",
            "generated_tokens",
            "total_cuda_seconds",
            "unique_raw_outputs",
            "dominant_normalized_fraction",
            "collapse_flag",
        )
    )
    for evaluation in report.variants:
        metrics = evaluation.metrics
        writer.writerow(
            (
                evaluation.definition.variant_id.value,
                metrics.event_count,
                metrics.known_unsafe_recall,
                metrics.category_aware_recall,
                metrics.effective_strict_json_rate,
                metrics.effective_pydantic_valid_rate,
                metrics.unverified_events,
                metrics.primary_generated_tokens + metrics.retry_generated_tokens,
                metrics.total_cuda_seconds,
                metrics.collapse.unique_raw_outputs,
                metrics.collapse.most_common_normalized_fraction,
                metrics.collapse.diagnostic_collapse_flag,
            )
        )
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    temporary.write_text(output.getvalue(), encoding="utf-8")
    temporary.replace(resolved)
    return resolved


def write_missed_ablation_review_index(
    full_report: SmolVLMEvidenceMapFullReport,
    ground_truth: GroundTruthArtifact,
    path: str | Path,
    *,
    existing_review_root: str | Path,
) -> Path | None:
    event_by_id = {event.event_id: event for event in full_report.events}
    missed: list[dict[str, Any]] = []
    for index, interval in enumerate(ground_truth.intervals):
        interval_id = f"silver:{index:03d}"
        records = [
            event
            for event in full_report.events
            if any(
                overlap.interval_id == interval_id and overlap.exact_overlap
                for overlap in event.silver_overlaps
            )
        ]
        if any(record.effective_attempt.derived_unsafe for record in records):
            continue
        missed.append(
            {
                "interval_id": interval_id,
                "start": interval.start,
                "end": interval.end,
                "category": interval.category,
                "existing_review_directory": str(
                    Path(existing_review_root).resolve()
                    / interval_id.replace(":", "_")
                ),
                "events": [
                    {
                        "event_id": record.event_id,
                        "selected_frame_timestamps_us": record.selected_frame_timestamps_us,
                        "effective_attempt": record.effective_attempt.model_dump(mode="json"),
                    }
                    for record in records
                    if record.event_id in event_by_id
                ],
            }
        )
    if not missed:
        return None
    resolved = Path(path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(
            {
                "experimental": True,
                "variant": full_report.variant.variant_id.value,
                "missed_silver_intervals": missed,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return resolved


def _evaluate_variant(
    definition: PromptVariantDefinition,
    events: Sequence[CandidateEvent],
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    manifest: SelectedFrameCacheManifest,
    *,
    frame_cache_root: Path,
    runtime: Any,
    progress_callback: Callable[[str, int, int], None] | None,
) -> PromptVariantEvaluation:
    entry_by_id = {entry.sample_id: entry for entry in manifest.entries}
    records: list[EvidenceMapEventResult] = []
    for ordinal, event in enumerate(events, start=1):
        entries = tuple(
            entry_by_id[selected.sample.sample_id] for selected in event.selected_frames
        )
        request, images = build_verification_request(event, entries, frame_cache_root)
        primary = run_evidence_map_attempt(
            runtime,
            request,
            definition,
            max_new_tokens=PRIMARY_MAX_NEW_TOKENS,
        )
        retry = None
        if primary.generation.truncated:
            retry = run_evidence_map_attempt(
                runtime,
                request,
                definition,
                max_new_tokens=RETRY_MAX_NEW_TOKENS,
            )
        for image in images:
            image.close()
        records.append(
            EvidenceMapEventResult(
                event_id=event.event_id,
                variant_id=definition.variant_id,
                start_timestamp_us=event.start_timestamp_us,
                end_timestamp_us=event.end_timestamp_us,
                selected_frame_timestamps_us=tuple(
                    entry.timestamp_us for entry in entries
                ),
                silver_overlaps=match_event_to_ground_truth(
                    event,
                    ground_truth.intervals,
                    movie_duration_us=events_artifact.video_duration_us,
                ),
                primary_attempt=primary,
                truncation_retry_96=retry,
            )
        )
        if progress_callback:
            progress_callback(definition.variant_id.value, ordinal, len(events))
    return PromptVariantEvaluation(
        definition=definition,
        metrics=summarize_variant(records, ground_truth.intervals),
        events=tuple(records),
    )


def summarize_variant(
    records: Sequence[EvidenceMapEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> PromptVariantMetrics:
    effective = [record.effective_attempt for record in records]
    interval_outcomes = []
    grouped: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for index, interval in enumerate(intervals):
        interval_id = f"silver:{index:03d}"
        matching = [
            record
            for record in records
            if any(
                overlap.interval_id == interval_id and overlap.exact_overlap
                for overlap in record.silver_overlaps
            )
        ]
        detected = any(record.effective_attempt.derived_unsafe for record in matching)
        category_detected = bool(interval.category) and any(
            interval.category in record.effective_attempt.derived_categories
            for record in matching
        )
        interval_outcomes.append((detected, category_detected))
        if interval.category:
            grouped[interval.category].append((detected, category_detected))
    category_metrics = tuple(
        EvidenceCategoryRecall(
            category=category,
            total_intervals=len(values),
            unsafe_detected=sum(value[0] for value in values),
            unsafe_recall=sum(value[0] for value in values) / len(values),
            category_detected=sum(value[1] for value in values),
            category_aware_recall=sum(value[1] for value in values) / len(values),
        )
        for category, values in sorted(grouped.items())
    )
    total = len(interval_outcomes)
    return PromptVariantMetrics(
        variant_id=records[0].variant_id,
        event_count=len(records),
        primary_strict_json_rate=sum(
            record.primary_attempt.strict_json_valid for record in records
        )
        / len(records),
        primary_pydantic_valid_rate=sum(
            record.primary_attempt.pydantic_valid for record in records
        )
        / len(records),
        effective_strict_json_rate=sum(item.strict_json_valid for item in effective)
        / len(effective),
        effective_pydantic_valid_rate=sum(item.pydantic_valid for item in effective)
        / len(effective),
        detected_intervals=sum(value[0] for value in interval_outcomes),
        total_intervals=total,
        known_unsafe_recall=sum(value[0] for value in interval_outcomes) / total,
        category_detected_intervals=sum(value[1] for value in interval_outcomes),
        category_aware_recall=sum(value[1] for value in interval_outcomes) / total,
        category_recall=category_metrics,
        unverified_events=sum(item.status == "unverified" for item in effective),
        primary_generated_tokens=sum(
            record.primary_attempt.generation.generated_token_count for record in records
        ),
        retry_generated_tokens=sum(
            record.truncation_retry_96.generation.generated_token_count
            for record in records
            if record.truncation_retry_96
        ),
        total_cuda_seconds=sum(
            record.primary_attempt.generation.total_seconds
            + (
                record.truncation_retry_96.generation.total_seconds
                if record.truncation_retry_96
                else 0.0
            )
            for record in records
        ),
        collapse=output_collapse_diagnostics(
            [record.primary_attempt.generation.raw_generated_text for record in records]
        ),
    )


def output_collapse_diagnostics(raw_outputs: Sequence[str]) -> OutputCollapseDiagnostics:
    if not raw_outputs:
        raise ValueError("collapse diagnostics require outputs")
    exact = Counter(raw_outputs)
    normalized = Counter(_normalize_generated_output(value) for value in raw_outputs)
    common_exact, exact_frequency = exact.most_common(1)[0]
    common_normalized, normalized_frequency = normalized.most_common(1)[0]
    fraction = normalized_frequency / len(raw_outputs)
    return OutputCollapseDiagnostics(
        event_count=len(raw_outputs),
        unique_raw_outputs=len(exact),
        most_common_exact_output=common_exact,
        most_common_exact_frequency=exact_frequency,
        unique_normalized_outputs=len(normalized),
        most_common_normalized_output=common_normalized,
        most_common_normalized_frequency=normalized_frequency,
        most_common_normalized_fraction=fraction,
        diagnostic_collapse_flag=fraction >= COLLAPSE_DIAGNOSTIC_FRACTION,
    )


def _build_full_report(
    evaluation: PromptVariantEvaluation,
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    *,
    frame_cache_root: str | Path,
) -> SmolVLMEvidenceMapFullReport:
    effective = [record.effective_attempt for record in evaluation.events]
    categories = Counter(
        category for attempt in effective for category in attempt.derived_categories
    )
    known_records = tuple(
        record
        for record in evaluation.events
        if any(overlap.exact_overlap for overlap in record.silver_overlaps)
    )
    return SmolVLMEvidenceMapFullReport(
        variant=evaluation.definition,
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        model_provenance=evaluation.events[0].primary_attempt.generation.provenance.model_dump(
            mode="json"
        ),
        frame_cache_manifest_path=str(
            Path(frame_cache_root).resolve() / "manifest.json"
        ),
        events=evaluation.events,
        summary=FullRunSummary(
            total_events=len(evaluation.events),
            total_images=sum(
                len(record.selected_frame_timestamps_us) for record in evaluation.events
            ),
            events_with_categories=sum(item.derived_unsafe for item in effective),
            events_without_categories=sum(
                item.status == "no_evidence" for item in effective
            ),
            unverified_events=sum(item.status == "unverified" for item in effective),
            category_frequency=dict(sorted(categories.items())),
            effective_strict_json_rate=sum(item.strict_json_valid for item in effective)
            / len(effective),
            effective_pydantic_valid_rate=sum(item.pydantic_valid for item in effective)
            / len(effective),
            total_cuda_seconds=evaluation.metrics.total_cuda_seconds,
            collapse=evaluation.metrics.collapse,
            known_silver_metrics=summarize_variant(
                known_records,
                ground_truth.intervals,
            ),
        ),
        unlabeled_output_note=(
            "Events without exact silver overlap are unlabeled outputs, not false "
            "positives or true negatives."
        ),
    )


def _normalize_generated_output(raw_text: str) -> str:
    try:
        decoded = json.loads(raw_text.strip())
    except (json.JSONDecodeError, TypeError):
        return " ".join(raw_text.split())
    return json.dumps(decoded, sort_keys=True, separators=(",", ":"))


def _unverified_attempt(
    generation: RawSmolVLMGeneration,
    *,
    max_new_tokens: int,
    error: str,
    strict_json_valid: bool = False,
) -> EvidenceMapAttempt:
    return EvidenceMapAttempt(
        max_new_tokens=max_new_tokens,
        strict_json_valid=strict_json_valid,
        pydantic_valid=False,
        status="unverified",
        payload=None,
        derived_categories=(),
        derived_unsafe=False,
        evidence_timestamps_us={},
        validation_error=error,
        generation=generation,
    )
