"""Experimental cached-frame SmolVLM visual-capability ablation."""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    ExperimentalCandidateEventsArtifact,
)
from services.analysis.smolvlm_quality_evaluation import (
    CachedSelectedFrame,
    SelectedFrameCacheManifest,
    SilverIntervalReference,
    build_verification_request,
    match_event_to_ground_truth,
)
from services.analysis.smolvlm_verifier import (
    RawSmolVLMGeneration,
    SmolVLMVerifier,
    VLMVerificationRequestMetadata,
)
from services.analysis.stage1_evaluation import GroundTruthArtifact, GroundTruthInterval

BINARY_MAX_NEW_TOKENS = 4
BITMASK_MAX_NEW_TOKENS_CEILING = 8
CATEGORY_IDS = (
    "nudity",
    "sexual_content",
    "violence",
    "graphic_violence",
    "weapons",
    "drugs",
)
CATEGORY_QUESTIONS = {
    "nudity": "Is explicit visible nudity present in any supplied frame?",
    "sexual_content": (
        "Is visible sexual activity or strongly sexual physical behavior present "
        "in any supplied frame?"
    ),
    "violence": (
        "Is a visible physical attack, fight, assault, or violent action present "
        "in any supplied frame?"
    ),
    "graphic_violence": (
        "Is visible blood, gore, severe injury, or graphic violent harm present "
        "in any supplied frame?"
    ),
    "weapons": (
        "Is a firearm, gun, weapon, weapon cache, or weapon being aimed or used "
        "visibly present in any supplied frame?"
    ),
    "drugs": (
        "Is illegal drug use, marijuana use, illegal drug material, or drug "
        "paraphernalia visibly present in any supplied frame?"
    ),
}


class SmolVLMVisualCapabilityError(RuntimeError):
    """Cached inputs or binary capability contracts are invalid."""


class BinaryAnswer(StrEnum):
    YES = "yes"
    NO = "no"
    UNVERIFIED = "unverified"


class OutputTokenBudgetInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output_kind: Literal["binary", "bitmask"]
    candidate_count: int = Field(gt=0)
    minimum_candidate_token_count: int = Field(gt=0)
    maximum_candidate_token_count: int = Field(gt=0)
    eos_token_id: int | tuple[int, ...]
    eos_tokens_reserved: Literal[1] = 1
    required_max_new_tokens: int = Field(gt=0)
    configured_max_new_tokens: int = Field(gt=0)


class BinaryAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    answer: BinaryAnswer
    validation_error: str | None
    generation: RawSmolVLMGeneration


class BinaryEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    selected_frame_paths: tuple[str, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    answers: tuple[BinaryAttempt, ...]

    def answer_for(self, category: str) -> BinaryAnswer:
        for attempt in self.answers:
            if attempt.category == category:
                return attempt.answer
        raise SmolVLMVisualCapabilityError(
            f"Binary result for {self.event_id} lacks category '{category}'."
        )


class CategoryBinaryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    silver_intervals: int = Field(ge=0)
    detected_intervals: int = Field(ge=0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    yes_responses: int = Field(ge=0)
    no_responses: int = Field(ge=0)
    unverified_responses: int = Field(ge=0)
    total_generation_seconds: float = Field(ge=0.0)
    total_generated_tokens: int = Field(ge=0)


class RequestLatencyMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_count: int = Field(ge=0)
    total_generation_seconds: float = Field(ge=0.0)
    total_request_seconds: float = Field(ge=0.0)
    mean_request_seconds: float | None = Field(default=None, ge=0.0)
    p50_request_seconds: float | None = Field(default=None, ge=0.0)
    p90_request_seconds: float | None = Field(default=None, ge=0.0)
    total_generated_tokens: int = Field(ge=0)


class BinaryCapabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_count: int = Field(ge=1)
    request_count: int = Field(ge=1)
    valid_yes_no_count: int = Field(ge=0)
    valid_yes_no_rate: float = Field(ge=0.0, le=1.0)
    unverified_count: int = Field(ge=0)
    unverified_rate: float = Field(ge=0.0, le=1.0)
    output_distribution: dict[str, int]
    detected_intervals: int = Field(ge=0)
    total_intervals: int = Field(ge=1)
    known_unsafe_recall: float = Field(ge=0.0, le=1.0)
    category_detected_intervals: int = Field(ge=0)
    category_aware_recall: float = Field(ge=0.0, le=1.0)
    category_metrics: tuple[CategoryBinaryMetrics, ...]
    missed_interval_ids: tuple[str, ...]
    latency: RequestLatencyMetrics


class PhaseBGate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    should_run: bool
    measured_category_detected_intervals: int = Field(ge=0)
    rule: str
    reason: str


class SmolVLMVisualCapabilityBinaryReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    model_provenance: dict[str, Any]
    fixed_runtime_contract: dict[str, Any]
    event_artifact_path: str
    ground_truth_path: str
    frame_cache_manifest_path: str
    token_budget: OutputTokenBudgetInspection
    parser_contract: str
    events: tuple[BinaryEventResult, ...]
    summary: BinaryCapabilitySummary
    phase_b_gate: PhaseBGate
    metric_notes: tuple[str, ...]


class BitmaskAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    bits: tuple[bool, ...] | None
    validation_error: str | None
    generation: RawSmolVLMGeneration

    @property
    def valid(self) -> bool:
        return self.bits is not None

    def detected_categories(self) -> tuple[str, ...]:
        if self.bits is None:
            return ()
        return tuple(
            category for category, detected in zip(CATEGORY_IDS, self.bits, strict=True)
            if detected
        )


class BitmaskEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    attempt: BitmaskAttempt


class BitmaskCapabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_count: int = Field(ge=1)
    valid_count: int = Field(ge=0)
    valid_rate: float = Field(ge=0.0, le=1.0)
    unverified_count: int = Field(ge=0)
    detected_intervals: int = Field(ge=0)
    total_intervals: int = Field(ge=1)
    known_unsafe_recall: float = Field(ge=0.0, le=1.0)
    category_detected_intervals: int = Field(ge=0)
    category_aware_recall: float = Field(ge=0.0, le=1.0)
    category_recall: dict[str, float | None]
    phase_a_comparable_answers: int = Field(ge=0)
    phase_a_disagreements: int = Field(ge=0)
    latency: RequestLatencyMetrics


class FullBitmaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_count: int = Field(ge=1)
    valid_count: int = Field(ge=0)
    valid_rate: float = Field(ge=0.0, le=1.0)
    events_with_categories: int = Field(ge=0)
    events_without_categories: int = Field(ge=0)
    unverified_events: int = Field(ge=0)
    category_frequency: dict[str, int]
    latency: RequestLatencyMetrics


class SmolVLMVisualCapabilityBitmaskReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    model_provenance: dict[str, Any]
    fixed_runtime_contract: dict[str, Any]
    token_budget: OutputTokenBudgetInspection
    parser_contract: str
    known_silver_events: tuple[BitmaskEventResult, ...]
    known_silver_summary: BitmaskCapabilitySummary
    full_run_gate: PhaseBGate
    full_events: tuple[BitmaskEventResult, ...] | None
    full_summary: FullBitmaskSummary | None
    unlabeled_output_note: str


def parse_binary_answer(raw_text: str) -> BinaryAnswer:
    normalized = raw_text.strip().casefold()
    if normalized.endswith(".") and not normalized.endswith(".."):
        normalized = normalized[:-1]
    if normalized == "yes":
        return BinaryAnswer.YES
    if normalized == "no":
        return BinaryAnswer.NO
    return BinaryAnswer.UNVERIFIED


def parse_six_bit_output(raw_text: str) -> tuple[bool, ...] | None:
    if len(raw_text) != len(CATEGORY_IDS) or any(bit not in "01" for bit in raw_text):
        return None
    return tuple(bit == "1" for bit in raw_text)


def build_binary_conversation(
    metadata: VLMVerificationRequestMetadata,
    category: str,
) -> list[dict[str, Any]]:
    try:
        question = CATEGORY_QUESTIONS[category]
    except KeyError as exc:
        raise SmolVLMVisualCapabilityError(
            f"Unknown visual capability category '{category}'."
        ) from exc
    content: list[dict[str, str]] = [
        {
            "type": "text",
            "text": (
                "Inspect every supplied frame. The images are one time-ordered event. "
                "Report only visible evidence and do not infer unseen events from "
                "dialogue or context.\n"
            ),
        }
    ]
    for frame in metadata.frames:
        content.extend(
            (
                {"type": "text", "text": f"Frame {frame.frame_index}:\n"},
                {"type": "image"},
            )
        )
    content.append(
        {"type": "text", "text": f"Question: {question}\nAnswer only YES or NO."}
    )
    return [{"role": "user", "content": content}]


def build_bitmask_conversation(
    metadata: VLMVerificationRequestMetadata,
) -> list[dict[str, Any]]:
    content: list[dict[str, str]] = [
        {
            "type": "text",
            "text": (
                "Inspect every supplied frame in this one time-ordered event. Report "
                "only visible evidence; do not infer unseen events from dialogue or "
                "context.\n"
            ),
        }
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
                "Return exactly six digits. Use 1 if the category is visibly present "
                "in any supplied frame, otherwise 0. Order: nudity, sexual content, "
                "violence, graphic violence, weapons, drugs. Return only the six "
                "digits."
            ),
        }
    )
    return [{"role": "user", "content": content}]


def inspect_output_token_budget(
    tokenizer: Any,
    *,
    output_kind: Literal["binary", "bitmask"],
) -> OutputTokenBudgetInspection:
    candidates = (
        tuple(
            prefix + value + suffix
            for prefix in ("", " ")
            for value in ("YES", "NO", "Yes", "No", "yes", "no")
            for suffix in ("", ".")
        )
        if output_kind == "binary"
        else tuple(f"{value:06b}" for value in range(64))
    )
    counts = tuple(_token_count(tokenizer, candidate) for candidate in candidates)
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if eos_token_id is None:
        raise SmolVLMVisualCapabilityError(
            "Pinned tokenizer does not expose an EOS token for short-output validation."
        )
    normalized_eos = (
        tuple(int(value) for value in eos_token_id)
        if isinstance(eos_token_id, (list, tuple))
        else int(eos_token_id)
    )
    required = max(counts) + 1
    configured = (
        BINARY_MAX_NEW_TOKENS
        if output_kind == "binary"
        else required
    )
    ceiling = (
        BINARY_MAX_NEW_TOKENS
        if output_kind == "binary"
        else BITMASK_MAX_NEW_TOKENS_CEILING
    )
    if required > ceiling:
        raise SmolVLMVisualCapabilityError(
            f"Runtime tokenization needs {required} new tokens for {output_kind}; "
            f"the experimental ceiling is {ceiling}."
        )
    return OutputTokenBudgetInspection(
        output_kind=output_kind,
        candidate_count=len(candidates),
        minimum_candidate_token_count=min(counts),
        maximum_candidate_token_count=max(counts),
        eos_token_id=normalized_eos,
        required_max_new_tokens=required,
        configured_max_new_tokens=configured,
    )


def evaluate_binary_capability(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    event_artifact_path: str | Path,
    ground_truth_path: str | Path,
    frame_cache_root: str | Path,
    verifier: SmolVLMVerifier,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SmolVLMVisualCapabilityBinaryReport:
    runtime = verifier.runtime()
    _validate_runtime(runtime)
    token_budget = inspect_output_token_budget(
        runtime.processor.tokenizer,
        output_kind="binary",
    )
    exact_events = _known_silver_events(events_artifact, ground_truth)
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    records: list[BinaryEventResult] = []
    total_requests = len(exact_events) * len(CATEGORY_IDS)
    completed = 0
    for event in exact_events:
        event_entries = _entries_for_event(event, entries)
        request, images = build_verification_request(
            event,
            event_entries,
            Path(frame_cache_root).resolve(),
        )
        attempts: list[BinaryAttempt] = []
        try:
            for category in CATEGORY_IDS:
                generation = runtime.generate_raw(
                    request,
                    build_binary_conversation(request.metadata, category),
                    max_new_tokens=token_budget.configured_max_new_tokens,
                    image_splitting=False,
                )
                answer = (
                    BinaryAnswer.UNVERIFIED
                    if generation.error is not None or generation.truncated
                    else parse_binary_answer(generation.raw_generated_text)
                )
                attempts.append(
                    BinaryAttempt(
                        category=category,
                        answer=answer,
                        validation_error=_binary_validation_error(generation, answer),
                        generation=generation,
                    )
                )
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_requests)
        finally:
            for image in images:
                image.close()
        records.append(
            BinaryEventResult(
                event_id=event.event_id,
                start_timestamp_us=event.start_timestamp_us,
                end_timestamp_us=event.end_timestamp_us,
                selected_frame_timestamps_us=tuple(
                    entry.timestamp_us for entry in event_entries
                ),
                selected_frame_paths=tuple(
                    str(Path(frame_cache_root).resolve() / entry.relative_png_path)
                    for entry in event_entries
                ),
                silver_overlaps=match_event_to_ground_truth(
                    event,
                    ground_truth.intervals,
                    movie_duration_us=events_artifact.video_duration_us,
                ),
                answers=tuple(attempts),
            )
        )
    summary = summarize_binary_capability(records, ground_truth.intervals)
    gate = phase_b_gate(summary)
    return SmolVLMVisualCapabilityBinaryReport(
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        model_provenance=runtime.provenance.model_dump(mode="json"),
        fixed_runtime_contract=_fixed_runtime_contract(),
        event_artifact_path=str(Path(event_artifact_path).resolve()),
        ground_truth_path=str(Path(ground_truth_path).resolve()),
        frame_cache_manifest_path=str(
            Path(frame_cache_root).resolve() / "manifest.json"
        ),
        token_budget=token_budget,
        parser_contract=(
            "Trim surrounding whitespace and normalize case; accept only YES or NO, "
            "optionally followed by exactly one period. Other punctuation and prose "
            "are rejected."
        ),
        events=tuple(records),
        summary=summary,
        phase_b_gate=gate,
        metric_notes=(
            "All six category questions are asked independently for every exact silver-overlap event.",
            "Unexpected YES responses are not treated as false positives because silver annotations are not exhaustive.",
            "A model/runtime error, truncated output, or non-binary response remains unverified.",
        ),
    )


def evaluate_bitmask_capability(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    phase_a: SmolVLMVisualCapabilityBinaryReport,
    *,
    frame_cache_root: str | Path,
    verifier: SmolVLMVerifier,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> SmolVLMVisualCapabilityBitmaskReport:
    if not phase_a.phase_b_gate.should_run:
        raise SmolVLMVisualCapabilityError(
            "Phase B is gated off because Phase A detected no expected silver category."
        )
    runtime = verifier.runtime()
    _validate_runtime(runtime)
    token_budget = inspect_output_token_budget(
        runtime.processor.tokenizer,
        output_kind="bitmask",
    )
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    exact_events = _known_silver_events(events_artifact, ground_truth)
    known_records = _run_bitmask_events(
        exact_events,
        events_artifact,
        ground_truth,
        entries,
        frame_cache_root=Path(frame_cache_root).resolve(),
        runtime=runtime,
        max_new_tokens=token_budget.configured_max_new_tokens,
        progress_label="known_silver",
        progress_callback=progress_callback,
    )
    known_summary = summarize_bitmask_capability(
        known_records,
        ground_truth.intervals,
        phase_a.events,
    )
    full_gate = full_bitmask_gate(known_summary, phase_a.summary)
    full_records = None
    full_summary = None
    if full_gate.should_run:
        full_records = _run_bitmask_events(
            events_artifact.events,
            events_artifact,
            ground_truth,
            entries,
            frame_cache_root=Path(frame_cache_root).resolve(),
            runtime=runtime,
            max_new_tokens=token_budget.configured_max_new_tokens,
            progress_label="full",
            progress_callback=progress_callback,
        )
        full_summary = summarize_full_bitmask(full_records)
    return SmolVLMVisualCapabilityBitmaskReport(
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        model_provenance=runtime.provenance.model_dump(mode="json"),
        fixed_runtime_contract=_fixed_runtime_contract(),
        token_budget=token_budget,
        parser_contract=(
            "Accept exactly six characters with no whitespace or punctuation; each "
            "character must be 0 or 1 in the fixed category order."
        ),
        known_silver_events=known_records,
        known_silver_summary=known_summary,
        full_run_gate=full_gate,
        full_events=full_records,
        full_summary=full_summary,
        unlabeled_output_note=(
            "Events outside silver annotations remain unlabeled; category bits are "
            "descriptive outputs, not false-positive or precision measurements."
        ),
    )


def summarize_binary_capability(
    records: Sequence[BinaryEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> BinaryCapabilitySummary:
    attempts = [attempt for record in records for attempt in record.answers]
    valid = [attempt for attempt in attempts if attempt.answer != BinaryAnswer.UNVERIFIED]
    category_metrics = tuple(
        _summarize_binary_category(category, records, intervals)
        for category in CATEGORY_IDS
    )
    detected, category_detected, missed = _interval_detection_from_binary(
        records,
        intervals,
    )
    distribution = Counter(attempt.answer.value for attempt in attempts)
    return BinaryCapabilitySummary(
        event_count=len(records),
        request_count=len(attempts),
        valid_yes_no_count=len(valid),
        valid_yes_no_rate=len(valid) / len(attempts),
        unverified_count=len(attempts) - len(valid),
        unverified_rate=(len(attempts) - len(valid)) / len(attempts),
        output_distribution={
            answer.value: distribution[answer.value] for answer in BinaryAnswer
        },
        detected_intervals=detected,
        total_intervals=len(intervals),
        known_unsafe_recall=detected / len(intervals),
        category_detected_intervals=category_detected,
        category_aware_recall=category_detected / len(intervals),
        category_metrics=category_metrics,
        missed_interval_ids=missed,
        latency=_summarize_latency(attempt.generation for attempt in attempts),
    )


def summarize_bitmask_capability(
    records: Sequence[BitmaskEventResult],
    intervals: Sequence[GroundTruthInterval],
    phase_a_records: Sequence[BinaryEventResult],
) -> BitmaskCapabilitySummary:
    detected, category_detected, category_recall = _interval_detection_from_bitmask(
        records,
        intervals,
    )
    phase_a_by_id = {record.event_id: record for record in phase_a_records}
    comparable = 0
    disagreements = 0
    for record in records:
        if record.attempt.bits is None:
            continue
        binary = phase_a_by_id[record.event_id]
        for index, category in enumerate(CATEGORY_IDS):
            answer = binary.answer_for(category)
            if answer == BinaryAnswer.UNVERIFIED:
                continue
            comparable += 1
            if (answer == BinaryAnswer.YES) != record.attempt.bits[index]:
                disagreements += 1
    valid = sum(record.attempt.valid for record in records)
    return BitmaskCapabilitySummary(
        event_count=len(records),
        valid_count=valid,
        valid_rate=valid / len(records),
        unverified_count=len(records) - valid,
        detected_intervals=detected,
        total_intervals=len(intervals),
        known_unsafe_recall=detected / len(intervals),
        category_detected_intervals=category_detected,
        category_aware_recall=category_detected / len(intervals),
        category_recall=category_recall,
        phase_a_comparable_answers=comparable,
        phase_a_disagreements=disagreements,
        latency=_summarize_latency(record.attempt.generation for record in records),
    )


def summarize_full_bitmask(
    records: Sequence[BitmaskEventResult],
) -> FullBitmaskSummary:
    valid_records = [record for record in records if record.attempt.valid]
    with_categories = [
        record for record in valid_records if record.attempt.detected_categories()
    ]
    frequencies = Counter(
        category
        for record in valid_records
        for category in record.attempt.detected_categories()
    )
    return FullBitmaskSummary(
        event_count=len(records),
        valid_count=len(valid_records),
        valid_rate=len(valid_records) / len(records),
        events_with_categories=len(with_categories),
        events_without_categories=len(valid_records) - len(with_categories),
        unverified_events=len(records) - len(valid_records),
        category_frequency={category: frequencies[category] for category in CATEGORY_IDS},
        latency=_summarize_latency(record.attempt.generation for record in records),
    )


def phase_b_gate(summary: BinaryCapabilitySummary) -> PhaseBGate:
    should_run = summary.category_detected_intervals > 0
    return PhaseBGate(
        should_run=should_run,
        measured_category_detected_intervals=summary.category_detected_intervals,
        rule="Run Phase B only when Phase A detects at least one expected silver category.",
        reason=(
            "Phase A demonstrated non-zero category-aware visual recognition."
            if should_run
            else "Phase A category-aware recall was zero; Phase B was not run."
        ),
    )


def full_bitmask_gate(
    phase_b: BitmaskCapabilitySummary,
    phase_a: BinaryCapabilitySummary,
) -> PhaseBGate:
    should_run = (
        phase_b.valid_rate == 1.0
        and phase_b.category_detected_intervals > 0
        and phase_b.category_detected_intervals >= phase_a.category_detected_intervals
    )
    return PhaseBGate(
        should_run=should_run,
        measured_category_detected_intervals=phase_b.category_detected_intervals,
        rule=(
            "Run the 153-event bitmask pass only when every known-silver bitmask is "
            "valid and Phase B retains all Phase A category detections."
        ),
        reason=(
            "Known-silver bitmasks were fully valid and retained Phase A detections."
            if should_run
            else "Known-silver bitmask validity or category retention was insufficient."
        ),
    )


def _run_bitmask_events(
    events: Sequence[CandidateEvent],
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    entries: dict[str, CachedSelectedFrame],
    *,
    frame_cache_root: Path,
    runtime: Any,
    max_new_tokens: int,
    progress_label: str,
    progress_callback: Callable[[str, int, int], None] | None,
) -> tuple[BitmaskEventResult, ...]:
    results: list[BitmaskEventResult] = []
    for ordinal, event in enumerate(events, start=1):
        event_entries = _entries_for_event(event, entries)
        request, images = build_verification_request(
            event,
            event_entries,
            frame_cache_root,
        )
        try:
            generation = runtime.generate_raw(
                request,
                build_bitmask_conversation(request.metadata),
                max_new_tokens=max_new_tokens,
                image_splitting=False,
            )
        finally:
            for image in images:
                image.close()
        bits = (
            None
            if generation.error is not None or generation.truncated
            else parse_six_bit_output(generation.raw_generated_text)
        )
        results.append(
            BitmaskEventResult(
                event_id=event.event_id,
                start_timestamp_us=event.start_timestamp_us,
                end_timestamp_us=event.end_timestamp_us,
                selected_frame_timestamps_us=tuple(
                    entry.timestamp_us for entry in event_entries
                ),
                silver_overlaps=match_event_to_ground_truth(
                    event,
                    ground_truth.intervals,
                    movie_duration_us=events_artifact.video_duration_us,
                ),
                attempt=BitmaskAttempt(
                    bits=bits,
                    validation_error=_bitmask_validation_error(generation, bits),
                    generation=generation,
                ),
            )
        )
        if progress_callback:
            progress_callback(progress_label, ordinal, len(events))
    return tuple(results)


def _summarize_binary_category(
    category: str,
    records: Sequence[BinaryEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> CategoryBinaryMetrics:
    category_intervals = [
        (index, interval)
        for index, interval in enumerate(intervals)
        if interval.category == category
    ]
    detected = 0
    for index, _interval in category_intervals:
        interval_id = f"silver:{index:03d}"
        matching = _records_for_interval(records, interval_id)
        detected += any(
            record.answer_for(category) == BinaryAnswer.YES for record in matching
        )
    attempts = [
        attempt
        for record in records
        for attempt in record.answers
        if attempt.category == category
    ]
    counts = Counter(attempt.answer for attempt in attempts)
    total_intervals = len(category_intervals)
    return CategoryBinaryMetrics(
        category=category,
        silver_intervals=total_intervals,
        detected_intervals=detected,
        recall=(detected / total_intervals if total_intervals else None),
        yes_responses=counts[BinaryAnswer.YES],
        no_responses=counts[BinaryAnswer.NO],
        unverified_responses=counts[BinaryAnswer.UNVERIFIED],
        total_generation_seconds=sum(
            attempt.generation.generation_seconds for attempt in attempts
        ),
        total_generated_tokens=sum(
            attempt.generation.generated_token_count for attempt in attempts
        ),
    )


def _interval_detection_from_binary(
    records: Sequence[BinaryEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> tuple[int, int, tuple[str, ...]]:
    detected = 0
    category_detected = 0
    missed: list[str] = []
    for index, interval in enumerate(intervals):
        interval_id = f"silver:{index:03d}"
        matching = _records_for_interval(records, interval_id)
        unsafe = any(
            attempt.answer == BinaryAnswer.YES
            for record in matching
            for attempt in record.answers
        )
        expected = bool(interval.category) and any(
            record.answer_for(interval.category) == BinaryAnswer.YES
            for record in matching
        )
        detected += unsafe
        category_detected += expected
        if not expected:
            missed.append(interval_id)
    return detected, category_detected, tuple(missed)


def _interval_detection_from_bitmask(
    records: Sequence[BitmaskEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> tuple[int, int, dict[str, float | None]]:
    detected = 0
    category_detected = 0
    grouped: dict[str, list[bool]] = defaultdict(list)
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
        unsafe = any(record.attempt.detected_categories() for record in matching)
        expected = bool(interval.category) and any(
            interval.category in record.attempt.detected_categories()
            for record in matching
        )
        detected += unsafe
        category_detected += expected
        if interval.category:
            grouped[interval.category].append(expected)
    return (
        detected,
        category_detected,
        {
            category: (
                sum(grouped[category]) / len(grouped[category])
                if grouped[category]
                else None
            )
            for category in CATEGORY_IDS
        },
    )


def _summarize_latency(
    generations: Iterable[RawSmolVLMGeneration],
) -> RequestLatencyMetrics:
    values = tuple(generations)
    totals = tuple(value.total_seconds for value in values)
    return RequestLatencyMetrics(
        request_count=len(values),
        total_generation_seconds=sum(value.generation_seconds for value in values),
        total_request_seconds=sum(totals),
        mean_request_seconds=statistics.fmean(totals) if totals else None,
        p50_request_seconds=_percentile(totals, 0.50) if totals else None,
        p90_request_seconds=_percentile(totals, 0.90) if totals else None,
        total_generated_tokens=sum(value.generated_token_count for value in values),
    )


def _known_silver_events(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
) -> tuple[CandidateEvent, ...]:
    return tuple(
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


def _entries_for_event(
    event: CandidateEvent,
    entries: dict[str, CachedSelectedFrame],
) -> tuple[CachedSelectedFrame, ...]:
    try:
        return tuple(
            entries[selected.sample.sample_id] for selected in event.selected_frames
        )
    except KeyError as exc:
        raise SmolVLMVisualCapabilityError(
            f"Cached selected frame is missing for event {event.event_id}: {exc.args[0]}"
        ) from exc


def _records_for_interval(
    records: Sequence[BinaryEventResult],
    interval_id: str,
) -> tuple[BinaryEventResult, ...]:
    return tuple(
        record
        for record in records
        if any(
            overlap.interval_id == interval_id and overlap.exact_overlap
            for overlap in record.silver_overlaps
        )
    )


def _validate_runtime(runtime: Any) -> None:
    if (
        runtime.provenance.device != "cuda"
        or runtime.provenance.model_dtype != "float32"
        or runtime.provenance.attention_implementation != "sdpa"
    ):
        raise SmolVLMVisualCapabilityError(
            "Visual-capability ablation requires the fixed CUDA/FP32/SDPA runtime."
        )


def _fixed_runtime_contract() -> dict[str, Any]:
    return {
        "device": "cuda",
        "dtype": "float32",
        "attention": "sdpa",
        "image_splitting": False,
        "do_sample": False,
        "num_beams": 1,
    }


def _token_count(tokenizer: Any, value: str) -> int:
    encoded = tokenizer(value, add_special_tokens=False)
    token_ids = encoded["input_ids"]
    if hasattr(token_ids, "tolist"):
        token_ids = token_ids.tolist()
    if token_ids and isinstance(token_ids[0], list):
        if len(token_ids) != 1:
            raise SmolVLMVisualCapabilityError(
                "Tokenizer returned an unexpected batch for one output candidate."
            )
        token_ids = token_ids[0]
    count = len(token_ids)
    if count <= 0:
        raise SmolVLMVisualCapabilityError(
            "Tokenizer returned no tokens for a required output candidate."
        )
    return count


def _binary_validation_error(
    generation: RawSmolVLMGeneration,
    answer: BinaryAnswer,
) -> str | None:
    if generation.error is not None:
        return generation.error
    if generation.truncated:
        return "generation was truncated"
    if answer == BinaryAnswer.UNVERIFIED:
        return "output was not exactly YES or NO after whitespace/case normalization"
    return None


def _bitmask_validation_error(
    generation: RawSmolVLMGeneration,
    bits: tuple[bool, ...] | None,
) -> str | None:
    if generation.error is not None:
        return generation.error
    if generation.truncated:
        return "generation was truncated"
    if bits is None:
        return "output was not exactly six binary digits"
    return None


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
