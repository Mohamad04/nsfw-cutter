"""Experimental SmolVLM2-2.2B capability comparison on cached event frames."""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    ExperimentalCandidateEventsArtifact,
)
from services.analysis.qwen3vl_binary_capability import (
    EXPECTED_KNOWN_SILVER_EVENTS,
    EXPECTED_KNOWN_SILVER_IMAGES,
    EXPECTED_SILVER_INTERVALS,
    SMOKE_IMAGE_COUNTS,
    LatencySummary,
    cache_validation_summary,
    validate_known_silver_inputs,
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
    SmolVLMArtifactResolver,
    SmolVLMCudaOutOfMemoryError,
    SmolVLMModelContractError,
    SmolVLMModelLoadError,
    SmolVLMModelSpec,
    SmolVLMVerifier,
)
from services.analysis.smolvlm_visual_capability import (
    CATEGORY_IDS,
    BinaryAnswer,
    BinaryCapabilitySummary,
    OutputTokenBudgetInspection,
    build_binary_conversation,
    inspect_output_token_budget,
    parse_binary_answer,
    summarize_binary_capability,
)
from services.analysis.stage1_evaluation import GroundTruthArtifact

MODEL_REPOSITORY_ID = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
MODEL_REVISION = "482adb537c021c86670beed01cd58990d01e72e4"
MODEL_SHARD_1 = "model-00001-of-00002.safetensors"
MODEL_SHARD_2 = "model-00002-of-00002.safetensors"
MODEL_INDEX = "model.safetensors.index.json"
EXPECTED_PARAMETER_COUNT = 2_246_784_880
EXPECTED_MODEL_CLASS = "SmolVLMForConditionalGeneration"
EXPECTED_PROCESSOR_CLASS = "SmolVLMProcessor"
EXPECTED_CONTEXT_LENGTH = 8192
EXPECTED_DTYPE = "bfloat16"
EXPECTED_ATTENTION = "sdpa"

MODEL_FILE_MANIFEST: dict[str, tuple[int, str]] = {
    MODEL_SHARD_1: (
        4_959_390_584,
        "7c88a90e78f567460b2369a0369cc4dafbfda5607c9cb090b30fa4437b0282f2",
    ),
    MODEL_SHARD_2: (
        4_027_833_472,
        "cf3d0958a8240f71054a6812038f2a6bfbe2e5124573a3b363f6b120c9a52657",
    ),
    MODEL_INDEX: (
        63_881,
        "d7c4b7a36f51bc15755cb11938c76f66be56e7c0d2bf3606335a8f77f90a551d",
    ),
    "config.json": (
        3_642,
        "ec1f7e45deeafba7601f8dd0b6ca9ba75985dffc2f053e82341d12d06e2d9d46",
    ),
    "preprocessor_config.json": (
        599,
        "70d935393e28a5b77b8f46cbd3e3cb74a336e4814bd43983858215bd0be388e7",
    ),
    "processor_config.json": (
        67,
        "55fb18f99dcce2694a011d46addf50a8114e6458d1847f6da9a0af22c6695a95",
    ),
    "chat_template.json": (
        430,
        "b585e3598909a5687f9f9d738d35223724dedef256b9b274e1cbfb32b13c74bf",
    ),
    "generation_config.json": (
        136,
        "34835060c9f0f74d1acb456cc72ca32746d3843d9eb5f578f9cbffac1d2eb840",
    ),
    "tokenizer.json": (
        3_548_256,
        "5ece781dc8d2b2f3e2f289ca0ae50b17cfc27dd27bfe7971bb8241e0b964331a",
    ),
    "tokenizer_config.json": (
        28_627,
        "30d7854334f3f96e9dc8e5210777ba030d55257de0d9c9b5ce65387f2ab73773",
    ),
    "special_tokens_map.json": (
        868,
        "2dfea2a426162316ff1567c82bc6d36d9690cd9f90455f075c77daca78b45c60",
    ),
    "added_tokens.json": (
        4_739,
        "74135b8664b56088c0006f1c8e848d79a8eba003411f72ebf1dc2ee96227be3a",
    ),
    "merges.txt": (
        466_391,
        "0b54e8aa4e53d5383e2e4bc635a56b43f9647f7b13832d5d9ecd8f82dac4f510",
    ),
    "vocab.json": (
        800_662,
        "82b84012e3add4d01d12ba14442026e49b8cbbaead1f79ecf3d919784f82dc79",
    ),
}

SMOLVLM22_MODEL_SPEC = SmolVLMModelSpec(
    repository_id=MODEL_REPOSITORY_ID,
    revision=MODEL_REVISION,
    file_manifest=MODEL_FILE_MANIFEST,
    primary_artifact_filename=MODEL_SHARD_1,
    primary_artifact_sha256=MODEL_FILE_MANIFEST[MODEL_SHARD_1][1],
    expected_model_class=EXPECTED_MODEL_CLASS,
    expected_processor_class=EXPECTED_PROCESSOR_CLASS,
    expected_parameter_count=EXPECTED_PARAMETER_COUNT,
    expected_context_length=EXPECTED_CONTEXT_LENGTH,
)


class SmolVLM22BenchmarkError(RuntimeError):
    """The 2.2B benchmark input, gate, or baseline contract is invalid."""


class SmolVLM22Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    answer: BinaryAnswer
    validation_error: str | None
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)
    generation: RawSmolVLMGeneration


class SmolVLM22EventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    selected_frame_paths: tuple[str, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    answers: tuple[SmolVLM22Attempt, ...]

    def answer_for(self, category: str) -> BinaryAnswer:
        for attempt in self.answers:
            if attempt.category == category:
                return attempt.answer
        raise SmolVLM22BenchmarkError(
            f"Binary result for {self.event_id} lacks category '{category}'."
        )


class SmolVLM22RuntimeProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    revision: str
    shard_sha256: dict[str, str]
    model_class: str
    processor_class: str
    parameter_count: int
    model_dtype: str
    device: str
    transformers_version: str
    torch_version: str
    attention_implementation: str
    gpu_name: str
    gpu_total_memory_bytes: int = Field(gt=0)
    gpu_compute_capability: tuple[int, int]
    cuda_bf16_supported: Literal[True] = True
    steady_model_cuda_allocated_bytes: int = Field(ge=0)
    steady_model_cuda_reserved_bytes: int = Field(ge=0)


class SmolVLM22SmokeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    image_count: int
    category: str
    raw_answer_text: str
    parsed_answer: BinaryAnswer
    succeeded: bool
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)
    generation: RawSmolVLMGeneration


class SmolVLM22SmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    artifact_resolution_seconds: float = Field(ge=0.0)
    model_load_seconds: float = Field(ge=0.0)
    provenance: SmolVLM22RuntimeProvenance
    file_manifest: dict[str, tuple[int, str]]
    token_budget: OutputTokenBudgetInspection
    cache_validation: dict[str, Any]
    cases: tuple[SmolVLM22SmokeCase, ...]
    six_image_gate_passed: bool


class SmolVLM22PerformanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    latency: LatencySummary
    latency_by_image_count: dict[int, LatencySummary]
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)


class ThreeModelComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    smolvlm500m_artifact_path: str
    qwen3vl2b_artifact_path: str
    metrics: dict[str, dict[str, Any]]


class SmolVLM22CapabilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    video_filename: str
    video_duration_us: int = Field(gt=0)
    event_artifact_path: str
    ground_truth_path: str
    frame_cache_manifest_path: str
    artifact_resolution_seconds: float = Field(ge=0.0)
    model_load_seconds: float = Field(ge=0.0)
    provenance: SmolVLM22RuntimeProvenance
    token_budget: OutputTokenBudgetInspection
    generation_settings: dict[str, Any]
    events: tuple[SmolVLM22EventResult, ...]
    summary: BinaryCapabilitySummary
    performance: SmolVLM22PerformanceSummary
    comparison: ThreeModelComparison
    metric_notes: tuple[str, ...]


def create_smolvlm22_verifier(*, local_files_only: bool) -> SmolVLMVerifier:
    return SmolVLMVerifier(
        resolver=SmolVLMArtifactResolver(model_spec=SMOLVLM22_MODEL_SPEC),
        local_files_only=local_files_only,
        device="cuda",
        dtype="bfloat16",
        attention_implementation="sdpa",
    )


def run_smoke_benchmark(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    frame_cache_root: str | Path,
    verifier: SmolVLMVerifier,
) -> SmolVLM22SmokeReport:
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = verifier.runtime()
    provenance = inspect_runtime(runtime)
    token_budget = minimum_binary_token_budget(runtime.processor.tokenizer)
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    cases: list[SmolVLM22SmokeCase] = []
    for count in SMOKE_IMAGE_COUNTS:
        event = next(
            (event for event in known_events if len(event.selected_frames) == count),
            None,
        )
        if event is None:
            raise SmolVLM22BenchmarkError(
                f"Known-silver cache has no unchanged {count}-image event for smoke."
            )
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        try:
            runtime.torch.cuda.reset_peak_memory_stats()
            generation = runtime.generate_raw(
                request,
                build_binary_conversation(request.metadata, "weapons"),
                max_new_tokens=token_budget.configured_max_new_tokens,
                image_splitting=False,
            )
            peak_allocated = int(runtime.torch.cuda.max_memory_allocated())
            peak_reserved = int(runtime.torch.cuda.max_memory_reserved())
        finally:
            for image in images:
                image.close()
        answer = (
            BinaryAnswer.UNVERIFIED
            if generation.error is not None or generation.truncated
            else parse_binary_answer(generation.raw_generated_text)
        )
        succeeded = (
            generation.error is None
            and generation.expansion is not None
            and answer != BinaryAnswer.UNVERIFIED
        )
        cases.append(
            SmolVLM22SmokeCase(
                event_id=event.event_id,
                image_count=count,
                category="weapons",
                raw_answer_text=generation.raw_generated_text,
                parsed_answer=answer,
                succeeded=succeeded,
                peak_cuda_allocated_bytes=peak_allocated,
                peak_cuda_reserved_bytes=peak_reserved,
                generation=generation,
            )
        )
        if not succeeded:
            break
    gate = len(cases) == len(SMOKE_IMAGE_COUNTS) and all(
        case.succeeded for case in cases
    )
    return SmolVLM22SmokeReport(
        artifact_resolution_seconds=verifier.artifact_resolution_seconds,
        model_load_seconds=verifier.model_load_seconds,
        provenance=provenance,
        file_manifest=MODEL_FILE_MANIFEST,
        token_budget=token_budget,
        cache_validation=cache_validation_summary(
            events_artifact, ground_truth, frame_manifest, known_events
        ),
        cases=tuple(cases),
        six_image_gate_passed=gate,
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
    smoke: SmolVLM22SmokeReport,
    smol500_path: str | Path,
    qwen_path: str | Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> SmolVLM22CapabilityReport:
    if not smoke.six_image_gate_passed:
        raise SmolVLM22BenchmarkError(
            "Six-image smoke gate failed; the 144-request quality run is forbidden."
        )
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = verifier.runtime()
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    records: list[SmolVLM22EventResult] = []
    total = len(known_events) * len(CATEGORY_IDS)
    completed = 0
    for event in known_events:
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        attempts: list[SmolVLM22Attempt] = []
        try:
            for category in CATEGORY_IDS:
                runtime.torch.cuda.reset_peak_memory_stats()
                generation = runtime.generate_raw(
                    request,
                    build_binary_conversation(request.metadata, category),
                    max_new_tokens=smoke.token_budget.configured_max_new_tokens,
                    image_splitting=False,
                )
                answer = (
                    BinaryAnswer.UNVERIFIED
                    if generation.error is not None or generation.truncated
                    else parse_binary_answer(generation.raw_generated_text)
                )
                attempts.append(
                    SmolVLM22Attempt(
                        category=category,
                        answer=answer,
                        validation_error=validation_error(generation, answer),
                        peak_cuda_allocated_bytes=int(
                            runtime.torch.cuda.max_memory_allocated()
                        ),
                        peak_cuda_reserved_bytes=int(
                            runtime.torch.cuda.max_memory_reserved()
                        ),
                        generation=generation,
                    )
                )
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
        finally:
            for image in images:
                image.close()
        records.append(
            SmolVLM22EventResult(
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
    summary = summarize_binary_capability(records, ground_truth.intervals)  # type: ignore[arg-type]
    performance = summarize_performance(records)
    comparison = compare_three_models(
        records,
        summary,
        performance,
        smol500_path=smol500_path,
        qwen_path=qwen_path,
    )
    return SmolVLM22CapabilityReport(
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        event_artifact_path=str(Path(event_artifact_path).resolve()),
        ground_truth_path=str(Path(ground_truth_path).resolve()),
        frame_cache_manifest_path=str(
            Path(frame_cache_root).resolve() / "manifest.json"
        ),
        artifact_resolution_seconds=verifier.artifact_resolution_seconds,
        model_load_seconds=verifier.model_load_seconds,
        provenance=smoke.provenance,
        token_budget=smoke.token_budget,
        generation_settings={
            "device": "cuda",
            "dtype": "bfloat16",
            "attention": "sdpa",
            "image_splitting": False,
            "do_sample": False,
            "num_beams": 1,
            "temperature": None,
            "max_new_tokens": smoke.token_budget.configured_max_new_tokens,
            "quantization": None,
        },
        events=tuple(records),
        summary=summary,
        performance=performance,
        comparison=comparison,
        metric_notes=(
            "The exact cached images, six binary questions, parser, and silver metrics are reused.",
            "Unexpected YES responses are not false positives because silver annotations are not exhaustive.",
            "No movie, preprocessing, Stage-1, clustering, or frame selection was rerun.",
        ),
    )


def minimum_binary_token_budget(tokenizer: Any) -> OutputTokenBudgetInspection:
    inspected = inspect_output_token_budget(tokenizer, output_kind="binary")
    return inspected.model_copy(
        update={"configured_max_new_tokens": inspected.required_max_new_tokens}
    )


def inspect_runtime(runtime: Any) -> SmolVLM22RuntimeProvenance:
    provenance = runtime.provenance
    if (
        provenance.repository_id != MODEL_REPOSITORY_ID
        or provenance.revision != MODEL_REVISION
        or provenance.model_class != EXPECTED_MODEL_CLASS
        or provenance.processor_class != EXPECTED_PROCESSOR_CLASS
        or provenance.parameter_count != EXPECTED_PARAMETER_COUNT
        or provenance.model_dtype != EXPECTED_DTYPE
        or provenance.device != "cuda"
        or provenance.attention_implementation != EXPECTED_ATTENTION
    ):
        raise SmolVLMModelContractError(
            "Loaded SmolVLM2-2.2B runtime contradicts the pinned CUDA/BF16/SDPA contract."
        )
    torch_module = runtime.torch
    if not bool(torch_module.cuda.is_available()) or not bool(
        torch_module.cuda.is_bf16_supported()
    ):
        raise SmolVLMModelLoadError("CUDA BF16 runtime validation failed after loading.")
    properties = torch_module.cuda.get_device_properties(0)
    return SmolVLM22RuntimeProvenance(
        repository_id=provenance.repository_id,
        revision=provenance.revision,
        shard_sha256={
            MODEL_SHARD_1: MODEL_FILE_MANIFEST[MODEL_SHARD_1][1],
            MODEL_SHARD_2: MODEL_FILE_MANIFEST[MODEL_SHARD_2][1],
        },
        model_class=provenance.model_class,
        processor_class=provenance.processor_class,
        parameter_count=provenance.parameter_count,
        model_dtype=provenance.model_dtype,
        device=provenance.device,
        transformers_version=provenance.transformers_version,
        torch_version=provenance.torch_version,
        attention_implementation=provenance.attention_implementation or "",
        gpu_name=str(torch_module.cuda.get_device_name(0)),
        gpu_total_memory_bytes=int(properties.total_memory),
        gpu_compute_capability=tuple(
            int(value) for value in torch_module.cuda.get_device_capability(0)
        ),
        cuda_bf16_supported=True,
        steady_model_cuda_allocated_bytes=int(torch_module.cuda.memory_allocated()),
        steady_model_cuda_reserved_bytes=int(torch_module.cuda.memory_reserved()),
    )


def summarize_performance(
    records: Sequence[SmolVLM22EventResult],
) -> SmolVLM22PerformanceSummary:
    attempts = [attempt for record in records for attempt in record.answers]
    by_count: dict[int, list[RawSmolVLMGeneration]] = {}
    for record in records:
        count = len(record.selected_frame_timestamps_us)
        by_count.setdefault(count, []).extend(
            attempt.generation for attempt in record.answers
        )
    return SmolVLM22PerformanceSummary(
        latency=summarize_latency(attempt.generation for attempt in attempts),
        latency_by_image_count={
            count: summarize_latency(values) for count, values in sorted(by_count.items())
        },
        peak_cuda_allocated_bytes=max(
            attempt.peak_cuda_allocated_bytes for attempt in attempts
        ),
        peak_cuda_reserved_bytes=max(
            attempt.peak_cuda_reserved_bytes for attempt in attempts
        ),
    )


def summarize_latency(generations: Iterable[RawSmolVLMGeneration]) -> LatencySummary:
    values = tuple(generations)
    totals = tuple(value.total_seconds for value in values)
    return LatencySummary(
        request_count=len(values),
        total_processor_seconds=sum(value.processor_seconds for value in values),
        total_generation_seconds=sum(value.generation_seconds for value in values),
        total_request_seconds=sum(totals),
        mean_request_seconds=statistics.fmean(totals) if totals else None,
        p50_request_seconds=_percentile(totals, 0.50) if totals else None,
        p90_request_seconds=_percentile(totals, 0.90) if totals else None,
        p95_request_seconds=_percentile(totals, 0.95) if totals else None,
        maximum_request_seconds=max(totals) if totals else None,
        total_generated_tokens=sum(value.generated_token_count for value in values),
    )


def compare_three_models(
    records: Sequence[SmolVLM22EventResult],
    summary: BinaryCapabilitySummary,
    performance: SmolVLM22PerformanceSummary,
    *,
    smol500_path: str | Path,
    qwen_path: str | Path,
) -> ThreeModelComparison:
    smol_path = Path(smol500_path).resolve()
    resolved_qwen_path = Path(qwen_path).resolve()
    try:
        smol = json.loads(smol_path.read_text(encoding="utf-8"))
        qwen = json.loads(resolved_qwen_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SmolVLM22BenchmarkError(
            f"Existing baseline artifact is invalid ({type(exc).__name__})."
        ) from exc
    smol_summary = smol["summary"]
    qwen_summary = qwen["summary"]
    current_categories = {item.category: item for item in summary.category_metrics}
    smol_categories = {
        item["category"]: item for item in smol_summary["category_metrics"]
    }
    qwen_categories = {
        item["category"]: item for item in qwen_summary["category_metrics"]
    }
    metrics: dict[str, dict[str, Any]] = {
        "binary_validity": {
            "smolvlm2_500m": smol_summary["valid_yes_no_rate"],
            "qwen3vl_2b": qwen_summary["valid_yes_no_rate"],
            "smolvlm2_2_2b": summary.valid_yes_no_rate,
        },
        "any_category_recall": {
            "smolvlm2_500m": smol_summary["known_unsafe_recall"],
            "qwen3vl_2b": qwen_summary["known_unsafe_recall"],
            "smolvlm2_2_2b": summary.known_unsafe_recall,
        },
        "category_aware_recall": {
            "smolvlm2_500m": smol_summary["category_aware_recall"],
            "qwen3vl_2b": qwen_summary["category_aware_recall"],
            "smolvlm2_2_2b": summary.category_aware_recall,
        },
        "aggregate_request_seconds": {
            "smolvlm2_500m": smol_summary["latency"]["total_request_seconds"],
            "qwen3vl_2b": qwen_summary["latency"]["total_request_seconds"],
            "smolvlm2_2_2b": performance.latency.total_request_seconds,
        },
        "generation_seconds": {
            "smolvlm2_500m": smol_summary["latency"]["total_generation_seconds"],
            "qwen3vl_2b": qwen_summary["latency"]["total_generation_seconds"],
            "smolvlm2_2_2b": performance.latency.total_generation_seconds,
        },
        "mean_request_seconds": {
            "smolvlm2_500m": smol_summary["latency"]["mean_request_seconds"],
            "qwen3vl_2b": qwen_summary["latency"]["mean_request_seconds"],
            "smolvlm2_2_2b": performance.latency.mean_request_seconds,
        },
        "peak_cuda_allocated_bytes": {
            "smolvlm2_500m": _baseline_peak(smol),
            "qwen3vl_2b": qwen_summary.get("peak_cuda_allocated_bytes"),
            "smolvlm2_2_2b": performance.peak_cuda_allocated_bytes,
        },
        "marijuana_drugs_answer": {
            "smolvlm2_500m": target_answer(smol["events"], "silver:000", "drugs"),
            "qwen3vl_2b": target_answer(qwen["events"], "silver:000", "drugs"),
            "smolvlm2_2_2b": target_answer(records, "silver:000", "drugs"),
        },
        "weapons_answer": {
            "smolvlm2_500m": target_answer(smol["events"], "silver:009", "weapons"),
            "qwen3vl_2b": target_answer(qwen["events"], "silver:009", "weapons"),
            "smolvlm2_2_2b": target_answer(records, "silver:009", "weapons"),
        },
    }
    for category in CATEGORY_IDS:
        metrics[f"{category}_recall"] = {
            "smolvlm2_500m": smol_categories[category]["recall"],
            "qwen3vl_2b": qwen_categories[category]["recall"],
            "smolvlm2_2_2b": current_categories[category].recall,
        }
    return ThreeModelComparison(
        smolvlm500m_artifact_path=str(smol_path),
        qwen3vl2b_artifact_path=str(resolved_qwen_path),
        metrics=metrics,
    )


def target_answer(
    records: Sequence[Any], interval_id: str, category: str
) -> str:
    answers: list[str] = []
    for record in records:
        overlaps = (
            record.silver_overlaps
            if hasattr(record, "silver_overlaps")
            else record["silver_overlaps"]
        )
        if not any(
            (item.interval_id if hasattr(item, "interval_id") else item["interval_id"])
            == interval_id
            and (
                item.exact_overlap
                if hasattr(item, "exact_overlap")
                else item["exact_overlap"]
            )
            for item in overlaps
        ):
            continue
        attempts = record.answers if hasattr(record, "answers") else record["answers"]
        for attempt in attempts:
            attempt_category = (
                attempt.category if hasattr(attempt, "category") else attempt["category"]
            )
            if attempt_category == category:
                value = attempt.answer if hasattr(attempt, "answer") else attempt["answer"]
                answers.append(value.value if hasattr(value, "value") else str(value))
    if "yes" in answers:
        return "yes"
    if "unverified" in answers:
        return "unverified"
    if answers and all(value == "no" for value in answers):
        return "no"
    return "unavailable"


def entries_for_event(
    event: CandidateEvent,
    entries: dict[str, CachedSelectedFrame],
) -> tuple[CachedSelectedFrame, ...]:
    try:
        return tuple(entries[item.sample.sample_id] for item in event.selected_frames)
    except KeyError as exc:
        raise SmolVLM22BenchmarkError(
            f"Cached selected frame is missing for {event.event_id}: {exc.args[0]}"
        ) from exc


def validation_error(
    generation: RawSmolVLMGeneration,
    answer: BinaryAnswer,
) -> str | None:
    if generation.error is not None:
        return generation.error
    if generation.truncated:
        return "generation was truncated"
    if answer == BinaryAnswer.UNVERIFIED:
        return "generated text is not strict YES or NO"
    return None


def _baseline_peak(payload: dict[str, Any]) -> int | None:
    values = [
        attempt.get("peak_cuda_allocated_bytes")
        for event in payload.get("events", [])
        for attempt in event.get("answers", [])
    ]
    numeric = [int(value) for value in values if value is not None]
    return max(numeric) if numeric else None


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile for an empty sequence.")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


__all__ = [
    "EXPECTED_KNOWN_SILVER_EVENTS",
    "EXPECTED_KNOWN_SILVER_IMAGES",
    "EXPECTED_SILVER_INTERVALS",
    "MODEL_FILE_MANIFEST",
    "MODEL_REPOSITORY_ID",
    "MODEL_REVISION",
    "SMOLVLM22_MODEL_SPEC",
    "SmolVLM22BenchmarkError",
    "SmolVLM22CapabilityReport",
    "SmolVLM22SmokeReport",
    "SmolVLMCudaOutOfMemoryError",
    "compare_three_models",
    "create_smolvlm22_verifier",
    "evaluate_binary_capability",
    "run_smoke_benchmark",
]
