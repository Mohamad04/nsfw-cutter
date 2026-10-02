"""Experimental InternVL3.5-4B runtime-4bit binary capability benchmark.

This module is isolated from the live pipeline. It reads only the immutable
candidate-event/frame-cache artifacts and deliberately reuses the established
six questions and strict YES/NO parser.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.paths import get_model_cache_dir
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
    build_qwen_binary_conversation,
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
from services.analysis.smolvlm_verifier import VLMVerificationRequest
from services.analysis.smolvlm_visual_capability import (
    CATEGORY_IDS,
    BinaryAnswer,
    BinaryCapabilitySummary,
    OutputTokenBudgetInspection,
    inspect_output_token_budget,
    parse_binary_answer,
    summarize_binary_capability,
)
from services.analysis.stage1_evaluation import GroundTruthArtifact

MODEL_REPOSITORY_ID = "OpenGVLab/InternVL3_5-4B-HF"
MODEL_REVISION = "6bd4487402110ef9889ba50eb7aefeb302526fed"
MODEL_SHARD_1 = "model-00001-of-00002.safetensors"
MODEL_SHARD_2 = "model-00002-of-00002.safetensors"
MODEL_INDEX = "model.safetensors.index.json"
EXPECTED_MODEL_CLASS = "InternVLForConditionalGeneration"
EXPECTED_PROCESSOR_CLASS = "InternVLProcessor"
EXPECTED_PARAMETER_COUNT = 4_732_489_216
EXPECTED_ATTENTION = "sdpa"
EXPECTED_TILE_SIZE = 448
EXPECTED_IMAGE_SEQUENCE_LENGTH = 256

MODEL_FILE_MANIFEST: dict[str, tuple[int, str]] = {
    MODEL_SHARD_1: (
        4_954_007_064,
        "337d6d5bea97956480a1560c3a88e4e6c4455c3954b94ed468c367cf4b500f20",
    ),
    MODEL_SHARD_2: (
        4_511_078_400,
        "343234927f41c7d3a4aa8a2280864f477b1f77795463feb6b26910fa2e4921d3",
    ),
    MODEL_INDEX: (
        79_936,
        "4f5f24a16dc7fcba6edeb8df8482f633b369c284685f92c6e3d6069ee3b323e1",
    ),
    "config.json": (
        2_997,
        "d127456863b66b0cf656a36f4419db0607651af381aeaf6b88af729d2399708d",
    ),
    "generation_config.json": (
        121,
        "b17e2c6813e1f5e4de267a4c7697b46f69ba7ba95643c8253ad671fab7d7271c",
    ),
    "preprocessor_config.json": (
        666,
        "af09ffbe57900d5ae07f93f4c20693559a272e32fa6c5f816132cb71985aac98",
    ),
    "processor_config.json": (
        72,
        "3511f4ae65c2fa5c1ab6a0fb2bb2fe767d6f0ee53ba412953b33acc892327c2a",
    ),
    "chat_template.jinja": (
        481,
        "b3e3fa7cdeceec1d3dfe0d17b77724baf3857714e688f3a700261567e96140eb",
    ),
    "tokenizer_config.json": (
        7_614,
        "5d109a013cdc2b9b5914dbd9564e8e1ef591b91c4d5d5584a00b1f01f28c0749",
    ),
    "tokenizer.json": (
        11_424_484,
        "7b9d18660f656ae5a87df2d5d6ed990e80f292d3473c1a35cae8259a5d28cd67",
    ),
    "vocab.json": (
        2_776_833,
        "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    ),
    "merges.txt": (
        1_671_853,
        "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
    ),
    "added_tokens.json": (
        913,
        "21d196327bf587cb24ec39db1dbe52cd68d243fdde8bc60dff2c867261b703fe",
    ),
    "special_tokens_map.json": (
        877,
        "e847a86633f2470a0d9fed41b5a36ff1f4435050929aa80b28c41d28420501b2",
    ),
    "video_preprocessor_config.json": (
        1_345,
        "b7f9c784a27f30ddb3fc78fca353ab6ce982c2a263b702e2547302e8c1e0087a",
    ),
}


class InternVL35Error(RuntimeError):
    """Base error for the isolated InternVL experiment."""


class InternVL35ArtifactError(InternVL35Error):
    """Pinned snapshot resolution or integrity failed."""


class InternVL35ContractError(InternVL35Error):
    """Loaded runtime contradicted the verified contract."""


class InternVL35LoadError(InternVL35Error):
    """The exact native 4-bit CUDA runtime could not load."""


class InternVL35CudaOutOfMemoryError(InternVL35Error):
    """The fixed 4-bit experiment exceeded CUDA memory."""


class InternVL35BenchmarkError(InternVL35Error):
    """Input artifacts or benchmark gates are invalid."""


@dataclass(frozen=True)
class ResolvedInternVLArtifact:
    snapshot_dir: Path
    resolved_files: tuple[Path, ...]
    shard_sha256: dict[str, str]


class InternVL35ArtifactResolver:
    """Resolve one exact snapshot and verify every allowlisted file."""

    def __init__(
        self,
        *,
        model_cache_dir: str | Path | None = None,
        hub_download: Callable[..., str] | None = None,
    ) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir) if model_cache_dir else get_model_cache_dir()
        )
        self._hub_download = hub_download

    def resolve(self, *, local_files_only: bool = False) -> ResolvedInternVLArtifact:
        download = self._hub_download
        if download is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise InternVL35ArtifactError(
                    "huggingface_hub is unavailable; install requirements-ai.txt."
                ) from exc
            download = hf_hub_download
        paths: list[Path] = []
        for filename in MODEL_FILE_MANIFEST:
            try:
                path = Path(
                    download(
                        repo_id=MODEL_REPOSITORY_ID,
                        filename=filename,
                        revision=MODEL_REVISION,
                        cache_dir=self.model_cache_dir,
                        local_files_only=local_files_only,
                    )
                )
            except Exception as exc:
                raise InternVL35ArtifactError(
                    f"Unable to resolve pinned InternVL file {filename!r} "
                    f"({type(exc).__name__})."
                ) from exc
            paths.append(path)
        parents = {path.parent.resolve() for path in paths}
        if len(parents) != 1:
            raise InternVL35ArtifactError(
                "Pinned InternVL files resolved to mixed snapshot directories."
            )
        verify_file_manifest(dict(zip(MODEL_FILE_MANIFEST, paths, strict=True)))
        return ResolvedInternVLArtifact(
            snapshot_dir=next(iter(parents)),
            resolved_files=tuple(paths),
            shard_sha256={
                MODEL_SHARD_1: MODEL_FILE_MANIFEST[MODEL_SHARD_1][1],
                MODEL_SHARD_2: MODEL_FILE_MANIFEST[MODEL_SHARD_2][1],
            },
        )


class ImageDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class InternVLImageMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: ImageDimensions
    patch_count: int = Field(gt=0)
    visual_tokens: int = Field(gt=0)


class InternVLProcessorMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_image_count: int = Field(gt=0)
    images: tuple[InternVLImageMetrics, ...]
    pixel_values_shape: tuple[int, ...]
    patch_count: int = Field(gt=0)
    total_visual_tokens: int = Field(gt=0)
    input_ids_shape: tuple[int, ...]
    input_sequence_length: int = Field(gt=0)
    image_token_count: int = Field(gt=0)


class QuantizationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bitsandbytes_version: str
    load_in_4bit: Literal[True] = True
    quantization_type: str
    compute_dtype: str
    use_double_quant: bool
    quant_storage: str
    quantized_linear_modules: int = Field(gt=0)
    non_quantized_linear_modules: int = Field(ge=0)
    representative_quantized_modules: dict[str, dict[str, str]]
    representative_unquantized_modules: dict[str, dict[str, str]]


class InternVLRuntimeProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    repository_id: str
    revision: str
    shard_sha256: dict[str, str]
    model_class: str
    processor_class: str
    declared_parameter_count: int
    runtime_parameter_elements: int
    model_dtype: str
    device: Literal["cuda"]
    transformers_version: str
    torch_version: str
    attention_implementation: str
    gpu_name: str
    gpu_total_memory_bytes: int = Field(gt=0)
    gpu_compute_capability: tuple[int, int]
    cuda_bf16_supported: Literal[True] = True
    steady_model_cuda_allocated_bytes: int = Field(ge=0)
    steady_model_cuda_reserved_bytes: int = Field(ge=0)
    host_rss_bytes: int | None = Field(default=None, ge=0)
    quantization: QuantizationProvenance
    experimental_label: Literal[
        "InternVL3.5-4B — runtime 4-bit experimental baseline"
    ] = "InternVL3.5-4B — runtime 4-bit experimental baseline"


class InternVLGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    raw_generated_text: str
    error: str | None
    truncated: bool
    generated_token_count: int = Field(ge=0)
    chat_template_seconds: float = Field(ge=0.0)
    processor_seconds: float = Field(ge=0.0)
    generation_seconds: float = Field(ge=0.0)
    decode_seconds: float = Field(ge=0.0)
    total_seconds: float = Field(ge=0.0)
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)
    host_rss_bytes: int | None = Field(default=None, ge=0)
    processor_metrics: InternVLProcessorMetrics | None


class InternVLAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: str
    answer: BinaryAnswer
    validation_error: str | None
    generation: InternVLGeneration


class InternVLEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    selected_frame_paths: tuple[str, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    answers: tuple[InternVLAttempt, ...]

    def answer_for(self, category: str) -> BinaryAnswer:
        for attempt in self.answers:
            if attempt.category == category:
                return attempt.answer
        raise InternVL35BenchmarkError(
            f"Binary result for {self.event_id} lacks category {category!r}."
        )


class SmokeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    image_count: int
    category: str
    raw_answer_text: str
    parsed_answer: BinaryAnswer
    succeeded: bool
    generation: InternVLGeneration


class InternVLSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    artifact_resolution_seconds: float = Field(ge=0.0)
    model_load_seconds: float = Field(ge=0.0)
    provenance: InternVLRuntimeProvenance
    file_manifest: dict[str, tuple[int, str]]
    token_budget: OutputTokenBudgetInspection
    cache_validation: dict[str, Any]
    cases: tuple[SmokeCase, ...]
    six_image_gate_passed: bool


class InternVLPerformance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    latency: LatencySummary
    latency_by_image_count: dict[int, LatencySummary]
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)


class FourModelComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    baseline_artifact_paths: dict[str, str]
    metrics: dict[str, dict[str, Any]]


class InternVLCapabilityReport(BaseModel):
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
    provenance: InternVLRuntimeProvenance
    token_budget: OutputTokenBudgetInspection
    generation_settings: dict[str, Any]
    events: tuple[InternVLEventResult, ...]
    summary: BinaryCapabilitySummary
    performance: InternVLPerformance
    comparison: FourModelComparison
    metric_notes: tuple[str, ...]


@dataclass
class PreparedRequest:
    model_inputs: dict[str, Any]
    prompt_input_length: int
    chat_template_seconds: float
    processor_seconds: float
    metrics: InternVLProcessorMetrics


@dataclass
class InternVLRuntime:
    torch: Any
    processor: Any
    model: Any
    provenance: InternVLRuntimeProvenance

    def inspect_output_budget(self) -> OutputTokenBudgetInspection:
        inspected = inspect_output_token_budget(
            self.processor.tokenizer, output_kind="binary"
        )
        return inspected.model_copy(
            update={"configured_max_new_tokens": inspected.required_max_new_tokens}
        )

    def prepare(self, request: VLMVerificationRequest, category: str) -> PreparedRequest:
        conversation = build_qwen_binary_conversation(request, category)
        started = time.perf_counter()
        try:
            prompt = self.processor.apply_chat_template(
                conversation, tokenize=False, add_generation_prompt=True
            )
        except Exception as exc:
            raise InternVL35ContractError(
                f"InternVL chat template failed ({type(exc).__name__})."
            ) from exc
        chat_seconds = time.perf_counter() - started
        started = time.perf_counter()
        try:
            encoded = self.processor(
                text=[prompt], images=list(request.images), return_tensors="pt"
            )
        except Exception as exc:
            raise InternVL35ContractError(
                f"InternVL multi-image processor failed ({type(exc).__name__})."
            ) from exc
        processor_seconds = time.perf_counter() - started
        metrics = extract_processor_metrics(encoded, request, self.processor)
        return PreparedRequest(
            model_inputs=move_inputs(encoded, self.torch),
            prompt_input_length=metrics.input_sequence_length,
            chat_template_seconds=chat_seconds,
            processor_seconds=processor_seconds,
            metrics=metrics,
        )

    def generate_binary(
        self,
        request: VLMVerificationRequest,
        category: str,
        *,
        max_new_tokens: int,
    ) -> InternVLGeneration:
        started = time.perf_counter()
        self.torch.cuda.reset_peak_memory_stats()
        try:
            prepared = self.prepare(request, category)
            self.torch.cuda.synchronize()
            generation_started = time.perf_counter()
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **prepared.model_inputs,
                    do_sample=False,
                    num_beams=1,
                    max_new_tokens=max_new_tokens,
                )
            self.torch.cuda.synchronize()
        except self.torch.OutOfMemoryError as exc:
            self.torch.cuda.empty_cache()
            raise InternVL35CudaOutOfMemoryError(
                f"InternVL CUDA OOM for {len(request.images)} cached images."
            ) from exc
        except InternVL35Error:
            raise
        except Exception as exc:  # noqa: BLE001 - backend failure boundary
            return InternVLGeneration(
                event_id=request.metadata.event_id,
                raw_generated_text="",
                error=f"model generation failed ({type(exc).__name__}): {exc}",
                truncated=False,
                generated_token_count=0,
                chat_template_seconds=0.0,
                processor_seconds=0.0,
                generation_seconds=0.0,
                decode_seconds=0.0,
                total_seconds=time.perf_counter() - started,
                peak_cuda_allocated_bytes=int(self.torch.cuda.max_memory_allocated()),
                peak_cuda_reserved_bytes=int(self.torch.cuda.max_memory_reserved()),
                host_rss_bytes=host_rss_bytes(),
                processor_metrics=None,
            )
        generation_seconds = time.perf_counter() - generation_started
        decode_started = time.perf_counter()
        sequences = getattr(generated, "sequences", generated)
        if getattr(sequences, "ndim", None) != 2 or int(sequences.shape[0]) != 1:
            raise InternVL35ContractError(
                "InternVL generation did not return one token sequence."
            )
        new_tokens = sequences[:, prepared.prompt_input_length :]
        count = int(new_tokens.shape[1])
        raw_text = self.processor.batch_decode(
            new_tokens,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        eos_ids = generation_eos_ids(self.model, self.processor.tokenizer)
        last_id = int(new_tokens[0, -1].item()) if count else None
        truncated = count >= max_new_tokens and last_id not in eos_ids
        decode_seconds = time.perf_counter() - decode_started
        return InternVLGeneration(
            event_id=request.metadata.event_id,
            raw_generated_text=raw_text,
            error=("generation reached max_new_tokens without EOS" if truncated else None),
            truncated=truncated,
            generated_token_count=count,
            chat_template_seconds=prepared.chat_template_seconds,
            processor_seconds=prepared.processor_seconds,
            generation_seconds=generation_seconds,
            decode_seconds=decode_seconds,
            total_seconds=time.perf_counter() - started,
            peak_cuda_allocated_bytes=int(self.torch.cuda.max_memory_allocated()),
            peak_cuda_reserved_bytes=int(self.torch.cuda.max_memory_reserved()),
            host_rss_bytes=host_rss_bytes(),
            processor_metrics=prepared.metrics,
        )


class InternVLRuntimeFactory:
    def create(self, artifact: ResolvedInternVLArtifact) -> InternVLRuntime:
        try:
            import bitsandbytes
            import torch
            import transformers
            from transformers import (
                AutoModelForImageTextToText,
                AutoProcessor,
                BitsAndBytesConfig,
                InternVLForConditionalGeneration,
                InternVLProcessor,
            )
        except ImportError as exc:
            raise InternVL35LoadError(
                "Native InternVL/BitsAndBytes dependencies are unavailable."
            ) from exc
        validate_cuda(torch)
        quantization = BitsAndBytesConfig(load_in_4bit=True)
        validate_quantization_config(quantization)
        try:
            processor = AutoProcessor.from_pretrained(
                str(artifact.snapshot_dir),
                trust_remote_code=False,
                local_files_only=True,
            )
            model = AutoModelForImageTextToText.from_pretrained(
                str(artifact.snapshot_dir),
                trust_remote_code=False,
                local_files_only=True,
                use_safetensors=True,
                dtype=torch.bfloat16,
                attn_implementation=EXPECTED_ATTENTION,
                quantization_config=quantization,
                device_map={"": "cuda:0"},
            )
            model.eval()
            torch.cuda.synchronize()
        except torch.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise InternVL35CudaOutOfMemoryError(
                "InternVL model loading exceeded CUDA memory."
            ) from exc
        except Exception as exc:
            raise InternVL35LoadError(
                "Pinned InternVL snapshot failed native runtime 4-bit CUDA load; "
                f"no fallback was attempted ({type(exc).__name__}): {exc}"
            ) from exc
        validate_runtime_classes(
            processor,
            model,
            expected_processor=InternVLProcessor,
            expected_model=InternVLForConditionalGeneration,
        )
        provenance = inspect_runtime(
            torch,
            bitsandbytes,
            transformers,
            processor,
            model,
            quantization,
            artifact,
        )
        return InternVLRuntime(torch, processor, model, provenance)


class InternVLProvider:
    """Lazy provider: construction performs no network or model work."""

    def __init__(
        self,
        *,
        resolver: InternVL35ArtifactResolver | None = None,
        factory: InternVLRuntimeFactory | None = None,
        local_files_only: bool = False,
    ) -> None:
        self.resolver = resolver or InternVL35ArtifactResolver()
        self.factory = factory or InternVLRuntimeFactory()
        self.local_files_only = local_files_only
        self.artifact_resolution_seconds = 0.0
        self.model_load_seconds = 0.0
        self._runtime: InternVLRuntime | None = None

    def runtime(self) -> InternVLRuntime:
        if self._runtime is None:
            started = time.perf_counter()
            artifact = self.resolver.resolve(local_files_only=self.local_files_only)
            self.artifact_resolution_seconds = time.perf_counter() - started
            started = time.perf_counter()
            self._runtime = self.factory.create(artifact)
            self.model_load_seconds = time.perf_counter() - started
        return self._runtime


def extract_processor_metrics(
    encoded: Any,
    request: VLMVerificationRequest,
    processor: Any,
) -> InternVLProcessorMetrics:
    try:
        pixel_values = encoded["pixel_values"]
        input_ids = encoded["input_ids"]
        image_token_id = int(processor.image_token_id)
        image_sequence_length = int(processor.image_seq_length)
        image_processor = processor.image_processor
        patch_counts = tuple(
            int(
                image_processor.get_number_of_image_patches(
                    image.height,
                    image.width,
                    images_kwargs={"crop_to_patches": True},
                )
            )
            for image in request.images
        )
    except Exception as exc:
        raise InternVL35ContractError(
            f"InternVL processor outputs are not inspectable ({type(exc).__name__})."
        ) from exc
    if getattr(input_ids, "ndim", None) != 2 or int(input_ids.shape[0]) != 1:
        raise InternVL35ContractError("InternVL input_ids must be [1, sequence].")
    actual_patches = int(pixel_values.shape[0])
    expected_patches = sum(patch_counts)
    image_tokens = int((input_ids == image_token_id).sum().item())
    expected_tokens = expected_patches * image_sequence_length
    if actual_patches != expected_patches or image_tokens != expected_tokens:
        raise InternVL35ContractError(
            "InternVL processor patch/token expansion contradicts its runtime contract: "
            f"patches {actual_patches}/{expected_patches}, "
            f"tokens {image_tokens}/{expected_tokens}."
        )
    return InternVLProcessorMetrics(
        input_image_count=len(request.images),
        images=tuple(
            InternVLImageMetrics(
                source=ImageDimensions(width=image.width, height=image.height),
                patch_count=patches,
                visual_tokens=patches * image_sequence_length,
            )
            for image, patches in zip(request.images, patch_counts, strict=True)
        ),
        pixel_values_shape=tuple(int(value) for value in pixel_values.shape),
        patch_count=actual_patches,
        total_visual_tokens=expected_tokens,
        input_ids_shape=tuple(int(value) for value in input_ids.shape),
        input_sequence_length=int(input_ids.shape[1]),
        image_token_count=image_tokens,
    )


def run_smoke_benchmark(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    frame_cache_root: str | Path,
    provider: InternVLProvider,
) -> InternVLSmokeReport:
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = provider.runtime()
    budget = runtime.inspect_output_budget()
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    cases: list[SmokeCase] = []
    for count in SMOKE_IMAGE_COUNTS:
        event = next(
            (item for item in known_events if len(item.selected_frames) == count), None
        )
        if event is None:
            raise InternVL35BenchmarkError(f"No {count}-image silver event for smoke.")
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        try:
            generation = runtime.generate_binary(
                request, "weapons", max_new_tokens=budget.configured_max_new_tokens
            )
        finally:
            for image in images:
                image.close()
        answer = parsed_generation(generation)
        succeeded = (
            generation.error is None
            and generation.processor_metrics is not None
            and answer != BinaryAnswer.UNVERIFIED
        )
        cases.append(
            SmokeCase(
                event_id=event.event_id,
                image_count=count,
                category="weapons",
                raw_answer_text=generation.raw_generated_text,
                parsed_answer=answer,
                succeeded=succeeded,
                generation=generation,
            )
        )
        if not succeeded:
            break
    gate = len(cases) == 3 and all(case.succeeded for case in cases)
    return InternVLSmokeReport(
        artifact_resolution_seconds=provider.artifact_resolution_seconds,
        model_load_seconds=provider.model_load_seconds,
        provenance=runtime.provenance,
        file_manifest=MODEL_FILE_MANIFEST,
        token_budget=budget,
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
    provider: InternVLProvider,
    smoke: InternVLSmokeReport,
    baseline_paths: dict[str, str | Path],
    progress_callback: Callable[[int, int], None] | None = None,
) -> InternVLCapabilityReport:
    if not smoke.six_image_gate_passed:
        raise InternVL35BenchmarkError(
            "Six-image smoke gate failed; capability evaluation is forbidden."
        )
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = provider.runtime()
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    records: list[InternVLEventResult] = []
    completed = 0
    total = len(known_events) * len(CATEGORY_IDS)
    for event in known_events:
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        attempts: list[InternVLAttempt] = []
        try:
            for category in CATEGORY_IDS:
                generation = runtime.generate_binary(
                    request,
                    category,
                    max_new_tokens=smoke.token_budget.configured_max_new_tokens,
                )
                answer = parsed_generation(generation)
                attempts.append(
                    InternVLAttempt(
                        category=category,
                        answer=answer,
                        validation_error=validation_error(generation, answer),
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
            InternVLEventResult(
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
    comparison = compare_four_models(records, summary, performance, baseline_paths)
    return InternVLCapabilityReport(
        video_filename=events_artifact.video_filename,
        video_duration_us=events_artifact.video_duration_us,
        event_artifact_path=str(Path(event_artifact_path).resolve()),
        ground_truth_path=str(Path(ground_truth_path).resolve()),
        frame_cache_manifest_path=str(
            Path(frame_cache_root).resolve() / "manifest.json"
        ),
        artifact_resolution_seconds=provider.artifact_resolution_seconds,
        model_load_seconds=provider.model_load_seconds,
        provenance=runtime.provenance,
        token_budget=smoke.token_budget,
        generation_settings={
            "device": "cuda",
            "dtype": "bfloat16_unquantized_modules",
            "attention": "sdpa",
            "quantization": "BitsAndBytesConfig(load_in_4bit=True)",
            "quantization_type": runtime.provenance.quantization.quantization_type,
            "double_quantization": runtime.provenance.quantization.use_double_quant,
            "processor_defaults_unchanged": True,
            "do_sample": False,
            "num_beams": 1,
            "temperature": None,
            "max_new_tokens": smoke.token_budget.configured_max_new_tokens,
        },
        events=tuple(records),
        summary=summary,
        performance=performance,
        comparison=comparison,
        metric_notes=(
            "Exact cached frames, questions, parser, and silver metrics are reused.",
            "Unexpected YES answers are not false positives; silver labels are incomplete.",
            "No movie, preprocessing, Stage-1, clustering, or frame selection ran.",
            "Capability is for the runtime FP4 4-bit experimental baseline, not BF16.",
        ),
    )


def summarize_performance(records: Sequence[InternVLEventResult]) -> InternVLPerformance:
    attempts = [attempt for record in records for attempt in record.answers]
    by_count: dict[int, list[InternVLGeneration]] = {}
    for record in records:
        by_count.setdefault(len(record.selected_frame_timestamps_us), []).extend(
            attempt.generation for attempt in record.answers
        )
    return InternVLPerformance(
        latency=summarize_latency(attempt.generation for attempt in attempts),
        latency_by_image_count={
            count: summarize_latency(values) for count, values in sorted(by_count.items())
        },
        peak_cuda_allocated_bytes=max(
            attempt.generation.peak_cuda_allocated_bytes for attempt in attempts
        ),
        peak_cuda_reserved_bytes=max(
            attempt.generation.peak_cuda_reserved_bytes for attempt in attempts
        ),
    )


def summarize_latency(generations: Iterable[InternVLGeneration]) -> LatencySummary:
    values = tuple(generations)
    totals = tuple(item.total_seconds for item in values)
    return LatencySummary(
        request_count=len(values),
        total_processor_seconds=sum(item.processor_seconds for item in values),
        total_generation_seconds=sum(item.generation_seconds for item in values),
        total_request_seconds=sum(totals),
        mean_request_seconds=statistics.fmean(totals) if totals else None,
        p50_request_seconds=percentile(totals, 0.50) if totals else None,
        p90_request_seconds=percentile(totals, 0.90) if totals else None,
        p95_request_seconds=percentile(totals, 0.95) if totals else None,
        maximum_request_seconds=max(totals) if totals else None,
        total_generated_tokens=sum(item.generated_token_count for item in values),
    )


def compare_four_models(
    records: Sequence[InternVLEventResult],
    summary: BinaryCapabilitySummary,
    performance: InternVLPerformance,
    baseline_paths: dict[str, str | Path],
) -> FourModelComparison:
    required = ("smolvlm2_500m", "qwen3vl_2b", "smolvlm2_2_2b")
    if tuple(baseline_paths) != required:
        raise InternVL35BenchmarkError(
            f"Baseline keys must be exactly {required}, got {tuple(baseline_paths)}."
        )
    payloads: dict[str, dict[str, Any]] = {}
    resolved: dict[str, str] = {}
    for name, raw_path in baseline_paths.items():
        path = Path(raw_path).resolve()
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InternVL35BenchmarkError(
                f"Invalid {name} baseline artifact ({type(exc).__name__})."
            ) from exc
        resolved[name] = str(path)
    current_categories = {item.category: item for item in summary.category_metrics}
    columns = (*required, "internvl35_4b_4bit")

    def baseline_value(name: str, *keys: str) -> Any:
        value: Any = payloads[name]
        for key in keys:
            value = value[key]
        return value

    metrics: dict[str, dict[str, Any]] = {}
    direct = {
        "binary_validity": ("summary", "valid_yes_no_rate"),
        "any_category_recall": ("summary", "known_unsafe_recall"),
        "category_aware_recall": ("summary", "category_aware_recall"),
    }
    current = {
        "binary_validity": summary.valid_yes_no_rate,
        "any_category_recall": summary.known_unsafe_recall,
        "category_aware_recall": summary.category_aware_recall,
    }
    for metric, keys in direct.items():
        metrics[metric] = {
            **{name: baseline_value(name, *keys) for name in required},
            columns[-1]: current[metric],
        }
    for metric, attr in (
        ("aggregate_request_seconds", "total_request_seconds"),
        ("generation_seconds", "total_generation_seconds"),
        ("mean_request_seconds", "mean_request_seconds"),
    ):
        metrics[metric] = {
            name: baseline_latency(payloads[name], attr) for name in required
        }
        metrics[metric][columns[-1]] = getattr(performance.latency, attr)
    metrics["peak_cuda_allocated_bytes"] = {
        name: baseline_peak(payloads[name]) for name in required
    }
    metrics["peak_cuda_allocated_bytes"][columns[-1]] = (
        performance.peak_cuda_allocated_bytes
    )
    metrics["marijuana_drugs_answer"] = {
        name: target_answer(payloads[name]["events"], "silver:000", "drugs")
        for name in required
    }
    metrics["marijuana_drugs_answer"][columns[-1]] = target_answer(
        records, "silver:000", "drugs"
    )
    metrics["weapons_answer"] = {
        name: target_answer(payloads[name]["events"], "silver:009", "weapons")
        for name in required
    }
    metrics["weapons_answer"][columns[-1]] = target_answer(
        records, "silver:009", "weapons"
    )
    for category in CATEGORY_IDS:
        row: dict[str, Any] = {}
        for name in required:
            category_rows = baseline_value(name, "summary", "category_metrics")
            row[name] = next(
                item["recall"] for item in category_rows if item["category"] == category
            )
        row[columns[-1]] = current_categories[category].recall
        metrics[f"{category}_recall"] = row
    return FourModelComparison(baseline_artifact_paths=resolved, metrics=metrics)


def validate_quantization_config(config: Any) -> None:
    values = config.to_dict()
    expected = {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "fp4",
        "bnb_4bit_use_double_quant": False,
        "bnb_4bit_compute_dtype": "float32",
    }
    mismatches = {
        key: (values.get(key), value)
        for key, value in expected.items()
        if values.get(key) != value
    }
    if mismatches:
        raise InternVL35ContractError(
            f"BitsAndBytes default 4-bit contract changed: {mismatches}."
        )


def validate_cuda(torch_module: Any) -> None:
    if not bool(torch_module.cuda.is_available()):
        raise InternVL35LoadError("CUDA is required for the InternVL experiment.")
    if not bool(torch_module.cuda.is_bf16_supported()):
        raise InternVL35LoadError("CUDA BF16 support is required for this experiment.")
    if "RTX 3070" not in str(torch_module.cuda.get_device_name(0)):
        raise InternVL35LoadError("The required RTX 3070 benchmark device is unavailable.")


def validate_runtime_classes(
    processor: Any,
    model: Any,
    *,
    expected_processor: type[Any],
    expected_model: type[Any],
) -> None:
    if not isinstance(processor, expected_processor) or (
        type(processor).__name__ != EXPECTED_PROCESSOR_CLASS
    ):
        raise InternVL35ContractError("Loaded processor is not native InternVLProcessor.")
    if not isinstance(model, expected_model) or (
        type(model).__name__ != EXPECTED_MODEL_CLASS
    ):
        raise InternVL35ContractError(
            "Loaded model is not native InternVLForConditionalGeneration."
        )
    if not bool(getattr(model, "is_loaded_in_4bit", False)):
        raise InternVL35ContractError("Loaded InternVL model is not marked 4-bit.")


def inspect_runtime(
    torch_module: Any,
    bitsandbytes: Any,
    transformers: Any,
    processor: Any,
    model: Any,
    quantization_config: Any,
    artifact: ResolvedInternVLArtifact,
) -> InternVLRuntimeProvenance:
    linear4bit = bitsandbytes.nn.Linear4bit
    quantized = [
        (name, module)
        for name, module in model.named_modules()
        if isinstance(module, linear4bit)
    ]
    non_quantized = [
        (name, module)
        for name, module in model.named_modules()
        if type(module) is torch_module.nn.Linear
    ]
    if not quantized:
        raise InternVL35ContractError("InternVL runtime contains no Linear4bit modules.")
    config = quantization_config.to_dict()
    attention = str(model.config._attn_implementation)
    if attention != EXPECTED_ATTENTION:
        raise InternVL35ContractError(
            f"InternVL attention is {attention!r}, expected SDPA."
        )
    if int(processor.image_seq_length) != EXPECTED_IMAGE_SEQUENCE_LENGTH:
        raise InternVL35ContractError("InternVL image sequence length changed.")
    size = processor.image_processor.size
    if int(size["height"]) != EXPECTED_TILE_SIZE or int(size["width"]) != EXPECTED_TILE_SIZE:
        raise InternVL35ContractError("InternVL processor tile size changed.")
    properties = torch_module.cuda.get_device_properties(0)

    def module_info(values: list[tuple[str, Any]]) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for name, module in values[:5]:
            weight = getattr(module, "weight", None)
            result[name] = {
                "class": type(module).__name__,
                "weight_dtype": str(getattr(weight, "dtype", "unavailable")),
                "weight_device": str(getattr(weight, "device", "unavailable")),
            }
        return result

    return InternVLRuntimeProvenance(
        repository_id=MODEL_REPOSITORY_ID,
        revision=MODEL_REVISION,
        shard_sha256=artifact.shard_sha256,
        model_class=type(model).__name__,
        processor_class=type(processor).__name__,
        declared_parameter_count=EXPECTED_PARAMETER_COUNT,
        runtime_parameter_elements=sum(int(item.numel()) for item in model.parameters()),
        model_dtype=str(model.dtype).removeprefix("torch."),
        device="cuda",
        transformers_version=str(transformers.__version__),
        torch_version=str(torch_module.__version__),
        attention_implementation=attention,
        gpu_name=str(torch_module.cuda.get_device_name(0)),
        gpu_total_memory_bytes=int(properties.total_memory),
        gpu_compute_capability=tuple(
            int(value) for value in torch_module.cuda.get_device_capability(0)
        ),
        cuda_bf16_supported=True,
        steady_model_cuda_allocated_bytes=int(torch_module.cuda.memory_allocated()),
        steady_model_cuda_reserved_bytes=int(torch_module.cuda.memory_reserved()),
        host_rss_bytes=host_rss_bytes(),
        quantization=QuantizationProvenance(
            bitsandbytes_version=str(bitsandbytes.__version__),
            load_in_4bit=True,
            quantization_type=str(config["bnb_4bit_quant_type"]),
            compute_dtype=str(config["bnb_4bit_compute_dtype"]),
            use_double_quant=bool(config["bnb_4bit_use_double_quant"]),
            quant_storage=str(config["bnb_4bit_quant_storage"]),
            quantized_linear_modules=len(quantized),
            non_quantized_linear_modules=len(non_quantized),
            representative_quantized_modules=module_info(quantized),
            representative_unquantized_modules=module_info(non_quantized),
        ),
    )


def move_inputs(batch: Any, torch_module: Any) -> dict[str, Any]:
    moved: dict[str, Any] = {}
    for key, value in dict(batch).items():
        if not hasattr(value, "to"):
            moved[key] = value
        elif bool(value.is_floating_point()):
            moved[key] = value.to(device="cuda", dtype=torch_module.bfloat16)
        else:
            moved[key] = value.to(device="cuda")
    return moved


def generation_eos_ids(model: Any, tokenizer: Any) -> set[int]:
    raw = getattr(getattr(model, "generation_config", None), "eos_token_id", None)
    if raw is None:
        raw = getattr(tokenizer, "eos_token_id", None)
    values = raw if isinstance(raw, (tuple, list)) else (raw,)
    if not values or any(value is None or int(value) < 0 for value in values):
        raise InternVL35ContractError("InternVL EOS token contract is invalid.")
    return {int(value) for value in values}


def parsed_generation(generation: InternVLGeneration) -> BinaryAnswer:
    if generation.error is not None or generation.truncated:
        return BinaryAnswer.UNVERIFIED
    return parse_binary_answer(generation.raw_generated_text)


def validation_error(
    generation: InternVLGeneration, answer: BinaryAnswer
) -> str | None:
    if generation.error:
        return generation.error
    if generation.truncated:
        return "generation was truncated"
    if answer == BinaryAnswer.UNVERIFIED:
        return "generated text is not strict YES or NO"
    return None


def entries_for_event(
    event: CandidateEvent,
    entries: dict[str, CachedSelectedFrame],
) -> tuple[CachedSelectedFrame, ...]:
    try:
        return tuple(entries[item.sample.sample_id] for item in event.selected_frames)
    except KeyError as exc:
        raise InternVL35BenchmarkError(
            f"Cached selected frame missing for {event.event_id}: {exc.args[0]}"
        ) from exc


def verify_file_manifest(paths: dict[str, Path]) -> None:
    for filename, (expected_size, expected_sha) in MODEL_FILE_MANIFEST.items():
        path = paths.get(filename)
        if path is None or not path.is_file():
            raise InternVL35ArtifactError(f"Pinned InternVL artifact missing: {filename}.")
        size = path.stat().st_size
        if size != expected_size:
            raise InternVL35ArtifactError(
                f"InternVL size mismatch for {filename}: {size} != {expected_size}."
            )
        digest = sha256_file(path)
        if digest != expected_sha:
            raise InternVL35ArtifactError(
                f"InternVL SHA-256 mismatch for {filename}: {digest} != {expected_sha}."
            )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def host_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def baseline_latency(payload: dict[str, Any], key: str) -> Any:
    if "performance" in payload:
        return payload["performance"]["latency"][key]
    return payload["summary"]["latency"][key]


def baseline_peak(payload: dict[str, Any]) -> int | None:
    if "performance" in payload:
        return payload["performance"].get("peak_cuda_allocated_bytes")
    summary = payload.get("summary", {})
    if summary.get("peak_cuda_allocated_bytes") is not None:
        return summary["peak_cuda_allocated_bytes"]
    values = [
        attempt.get("peak_cuda_allocated_bytes")
        or attempt.get("generation", {}).get("peak_cuda_allocated_bytes")
        for event in payload.get("events", [])
        for attempt in event.get("answers", [])
    ]
    numeric = [int(value) for value in values if value is not None]
    return max(numeric) if numeric else None


def target_answer(records: Sequence[Any], interval_id: str, category: str) -> str:
    answers: list[str] = []
    for record in records:
        overlaps = record.silver_overlaps if hasattr(record, "silver_overlaps") else record["silver_overlaps"]
        if not any(
            (item.interval_id if hasattr(item, "interval_id") else item["interval_id"])
            == interval_id
            and (item.exact_overlap if hasattr(item, "exact_overlap") else item["exact_overlap"])
            for item in overlaps
        ):
            continue
        attempts = record.answers if hasattr(record, "answers") else record["answers"]
        for attempt in attempts:
            attempt_category = attempt.category if hasattr(attempt, "category") else attempt["category"]
            if attempt_category == category:
                value = attempt.answer if hasattr(attempt, "answer") else attempt["answer"]
                answers.append(value.value if hasattr(value, "value") else str(value))
    if "yes" in answers:
        return "yes"
    if "unverified" in answers:
        return "unverified"
    if answers and all(answer == "no" for answer in answers):
        return "no"
    return "unavailable"


__all__ = [
    "EXPECTED_KNOWN_SILVER_EVENTS",
    "EXPECTED_KNOWN_SILVER_IMAGES",
    "EXPECTED_SILVER_INTERVALS",
    "MODEL_FILE_MANIFEST",
    "MODEL_REPOSITORY_ID",
    "MODEL_REVISION",
    "InternVL35ArtifactResolver",
    "InternVL35BenchmarkError",
    "InternVL35ContractError",
    "InternVL35CudaOutOfMemoryError",
    "InternVL35Error",
    "InternVL35LoadError",
    "InternVLProvider",
    "compare_four_models",
    "evaluate_binary_capability",
    "extract_processor_metrics",
    "run_smoke_benchmark",
    "validate_quantization_config",
    "validate_runtime_classes",
    "verify_file_manifest",
]
