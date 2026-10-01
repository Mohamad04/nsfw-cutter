"""Experimental Qwen3-VL binary capability benchmark on cached event frames.

This module is deliberately isolated from the live analysis pipeline. It reuses the
existing immutable candidate-event/frame-cache contracts and the exact SmolVLM
binary questions, but owns all Qwen-specific model resolution and processing.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter, defaultdict
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
    CATEGORY_QUESTIONS,
    BinaryAnswer,
    CategoryBinaryMetrics,
    parse_binary_answer,
)
from services.analysis.stage1_evaluation import GroundTruthArtifact, GroundTruthInterval

MODEL_REPOSITORY_ID = "Qwen/Qwen3-VL-2B-Instruct"
MODEL_REVISION = "89644892e4d85e24eaac8bacfd4f463576704203"
MODEL_WEIGHTS_FILENAME = "model.safetensors"
MODEL_WEIGHTS_SIZE = 4_255_140_312
MODEL_WEIGHTS_SHA256 = (
    "7de1838c87a5349b016c26a1c3f7d2bc400a3d485f95ef39a7059ffd734977a0"
)
EXPECTED_MODEL_CLASS = "Qwen3VLForConditionalGeneration"
EXPECTED_PROCESSOR_CLASS = "Qwen3VLProcessor"
EXPECTED_PARAMETER_COUNT = 2_127_532_032
EXPECTED_DTYPE = "bfloat16"
EXPECTED_ATTENTION = "sdpa"
EXPECTED_KNOWN_SILVER_EVENTS = 24
EXPECTED_KNOWN_SILVER_IMAGES = 104
EXPECTED_SILVER_INTERVALS = 16
SMOKE_IMAGE_COUNTS = (1, 3, 6)

# Every required file belongs to one pinned snapshot. Pickle weights are absent.
MODEL_FILE_MANIFEST: dict[str, tuple[int, str]] = {
    MODEL_WEIGHTS_FILENAME: (MODEL_WEIGHTS_SIZE, MODEL_WEIGHTS_SHA256),
    "config.json": (
        1_505,
        "bec4b3d446efa05807365c9e1cec03ac590836879d02f3a6da879971154bdd3b",
    ),
    "generation_config.json": (
        269,
        "1e241830b48b397cb0900101421df5450baddc7adf01e5fc86b5615865f3bae4",
    ),
    "preprocessor_config.json": (
        390,
        "27225450ac9c6529872ee1924fcb0962ff5634834f817040f444118116f4e516",
    ),
    "video_preprocessor_config.json": (
        385,
        "7768af27c1fafa9cc9011c1dc20067e03f8915e03b63504550e11d5066986d13",
    ),
    "tokenizer_config.json": (
        10_868,
        "c2da771801886ad9ae98181793ffd3dfb7f1af30f6f7c6a4e15d7dbba52e2399",
    ),
    "tokenizer.json": (
        7_032_403,
        "a5d85b6dcc535e6b93115a9ef287e6132fdbf30270da6218194ba742261173c7",
    ),
    "vocab.json": (
        2_776_833,
        "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
    ),
    "merges.txt": (
        1_671_839,
        "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3",
    ),
    "chat_template.json": (
        5_502,
        "6f8a6a55027e3da5160105556cda5dd69f6423f1c32645f6730d32de7773d0c4",
    ),
}


class Qwen3VLError(RuntimeError):
    """Base error for the isolated Qwen3-VL experiment."""


class Qwen3VLArtifactUnavailableError(Qwen3VLError):
    """The exact pinned snapshot could not be resolved."""


class Qwen3VLArtifactIntegrityError(Qwen3VLError):
    """A pinned artifact failed its size or SHA-256 contract."""


class Qwen3VLModelLoadError(Qwen3VLError):
    """The native pinned Qwen model could not be loaded as requested."""


class Qwen3VLModelContractError(Qwen3VLError):
    """Runtime inspection contradicted the verified Qwen contract."""


class Qwen3VLCudaOutOfMemoryError(Qwen3VLError):
    """A Qwen request exceeded the explicit CUDA memory baseline."""


class Qwen3VLBenchmarkError(Qwen3VLError):
    """Cached inputs or benchmark gates are invalid."""


@dataclass(frozen=True)
class ResolvedQwen3VLArtifact:
    snapshot_dir: Path
    weights_path: Path
    sha256: str
    resolved_files: tuple[Path, ...]


class Qwen3VLArtifactResolver:
    """Lazily resolve exactly one pinned, integrity-checked Qwen snapshot."""

    def __init__(
        self,
        *,
        model_cache_dir: str | Path | None = None,
        hub_download: Callable[..., str] | None = None,
    ) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir)
            if model_cache_dir is not None
            else get_model_cache_dir()
        )
        self._hub_download = hub_download

    def resolve(self, *, local_files_only: bool = False) -> ResolvedQwen3VLArtifact:
        download = self._hub_download
        if download is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise Qwen3VLArtifactUnavailableError(
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
                source = "local model cache" if local_files_only else "Hugging Face Hub"
                raise Qwen3VLArtifactUnavailableError(
                    f"Unable to resolve pinned Qwen file '{filename}' from {source} "
                    f"({type(exc).__name__})."
                ) from exc
            if not path.is_file():
                raise Qwen3VLArtifactUnavailableError(
                    f"Pinned Qwen file '{filename}' is not readable."
                )
            paths.append(path)

        snapshot_dirs = {path.parent.resolve() for path in paths}
        if len(snapshot_dirs) != 1:
            raise Qwen3VLArtifactUnavailableError(
                "Pinned Qwen files did not resolve to one local snapshot."
            )
        _verify_file_manifest(dict(zip(MODEL_FILE_MANIFEST, paths, strict=True)))
        return ResolvedQwen3VLArtifact(
            snapshot_dir=next(iter(snapshot_dirs)),
            weights_path=paths[0],
            sha256=MODEL_WEIGHTS_SHA256,
            resolved_files=tuple(paths),
        )


class ImageDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class QwenImageMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ImageDimensions
    processed: ImageDimensions
    grid_thw: tuple[int, int, int]
    visual_tokens: int = Field(gt=0)


class QwenProcessorMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_image_count: int = Field(gt=0)
    images: tuple[QwenImageMetric, ...]
    pixel_values_shape: tuple[int, ...]
    image_grid_thw_shape: tuple[int, ...]
    input_ids_shape: tuple[int, ...]
    total_visual_tokens: int = Field(gt=0)
    input_sequence_length: int = Field(gt=0)


class QwenRuntimeProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    revision: str
    checkpoint_sha256: str
    model_class: str
    processor_class: str
    parameter_count: int
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
    experimental: Literal[True] = True


class QwenOutputTokenBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_token_counts: dict[str, int]
    eos_token_ids: tuple[int, ...]
    eos_tokens_reserved: Literal[1] = 1
    max_new_tokens: int = Field(gt=0)


class QwenGeneration(BaseModel):
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
    tokens_per_second: float | None = Field(default=None, ge=0.0)
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)
    processor_metrics: QwenProcessorMetrics | None
    provenance: QwenRuntimeProvenance


@dataclass
class PreparedQwenRequest:
    model_inputs: dict[str, Any]
    prompt_input_length: int
    chat_template_seconds: float
    processor_seconds: float
    processor_metrics: QwenProcessorMetrics


@dataclass
class Qwen3VLRuntime:
    torch: Any
    processor: Any
    model: Any
    provenance: QwenRuntimeProvenance
    patch_size: int
    merge_size: int

    def inspect_output_budget(self) -> QwenOutputTokenBudget:
        candidates = ("YES", "NO", "YES.", "NO.")
        counts = {value: _token_count(self.processor.tokenizer, value) for value in candidates}
        eos_ids = _generation_eos_ids(self.model, self.processor.tokenizer)
        return QwenOutputTokenBudget(
            candidate_token_counts=counts,
            eos_token_ids=eos_ids,
            max_new_tokens=max(counts.values()) + 1,
        )

    def prepare(
        self,
        request: VLMVerificationRequest,
        category: str,
    ) -> PreparedQwenRequest:
        conversation = build_qwen_binary_conversation(request, category)
        chat_started = time.perf_counter()
        try:
            prompt = self.processor.apply_chat_template(
                conversation,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as exc:
            raise Qwen3VLModelContractError(
                f"Pinned Qwen chat-template processing failed ({type(exc).__name__})."
            ) from exc
        chat_seconds = time.perf_counter() - chat_started

        processor_started = time.perf_counter()
        try:
            encoded = self.processor(
                text=[prompt],
                images=list(request.images),
                return_tensors="pt",
            )
        except Exception as exc:
            raise Qwen3VLModelContractError(
                f"Pinned Qwen multi-image processing failed ({type(exc).__name__})."
            ) from exc
        processor_seconds = time.perf_counter() - processor_started
        metrics = extract_processor_metrics(
            encoded,
            request,
            patch_size=self.patch_size,
            merge_size=self.merge_size,
        )
        model_inputs = _move_model_inputs(
            encoded,
            device="cuda",
            dtype=self.torch.bfloat16,
        )
        return PreparedQwenRequest(
            model_inputs=model_inputs,
            prompt_input_length=metrics.input_sequence_length,
            chat_template_seconds=chat_seconds,
            processor_seconds=processor_seconds,
            processor_metrics=metrics,
        )

    def generate_binary(
        self,
        request: VLMVerificationRequest,
        category: str,
        *,
        max_new_tokens: int,
    ) -> QwenGeneration:
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
            raise Qwen3VLCudaOutOfMemoryError(
                f"Qwen CUDA OOM for {len(request.images)} cached images."
            ) from exc
        except Qwen3VLError:
            raise
        except Exception as exc:  # noqa: BLE001 - model backend failure boundary
            return self._failure(
                request,
                error=f"model generation failed ({type(exc).__name__}): {exc}",
                total_seconds=time.perf_counter() - started,
            )
        generation_seconds = time.perf_counter() - generation_started
        decode_started = time.perf_counter()
        try:
            sequences = getattr(generated, "sequences", generated)
            if getattr(sequences, "ndim", None) != 2 or int(sequences.shape[0]) != 1:
                raise Qwen3VLModelContractError(
                    "Native Qwen generation did not return one token sequence."
                )
            new_tokens = sequences[:, prepared.prompt_input_length :]
            generated_count = int(new_tokens.shape[1])
            raw_text = self.processor.batch_decode(
                new_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
            eos_ids = set(_generation_eos_ids(self.model, self.processor.tokenizer))
            last_id = int(new_tokens[0, -1].item()) if generated_count else None
            truncated = generated_count >= max_new_tokens and last_id not in eos_ids
        except Exception as exc:  # noqa: BLE001 - generated-output trust boundary
            return self._failure(
                request,
                error=f"generated text decode failed ({type(exc).__name__}): {exc}",
                prepared=prepared,
                generation_seconds=generation_seconds,
                decode_seconds=time.perf_counter() - decode_started,
                total_seconds=time.perf_counter() - started,
            )
        decode_seconds = time.perf_counter() - decode_started
        return QwenGeneration(
            event_id=request.metadata.event_id,
            raw_generated_text=raw_text,
            error=(
                "generation reached max_new_tokens without an EOS token"
                if truncated
                else None
            ),
            truncated=truncated,
            generated_token_count=generated_count,
            chat_template_seconds=prepared.chat_template_seconds,
            processor_seconds=prepared.processor_seconds,
            generation_seconds=generation_seconds,
            decode_seconds=decode_seconds,
            total_seconds=time.perf_counter() - started,
            tokens_per_second=(
                generated_count / generation_seconds
                if generation_seconds > 0.0
                else None
            ),
            peak_cuda_allocated_bytes=int(self.torch.cuda.max_memory_allocated()),
            peak_cuda_reserved_bytes=int(self.torch.cuda.max_memory_reserved()),
            processor_metrics=prepared.processor_metrics,
            provenance=self.provenance,
        )

    def _failure(
        self,
        request: VLMVerificationRequest,
        *,
        error: str,
        prepared: PreparedQwenRequest | None = None,
        generation_seconds: float = 0.0,
        decode_seconds: float = 0.0,
        total_seconds: float,
    ) -> QwenGeneration:
        return QwenGeneration(
            event_id=request.metadata.event_id,
            raw_generated_text="",
            error=error,
            truncated=False,
            generated_token_count=0,
            chat_template_seconds=prepared.chat_template_seconds if prepared else 0.0,
            processor_seconds=prepared.processor_seconds if prepared else 0.0,
            generation_seconds=generation_seconds,
            decode_seconds=decode_seconds,
            total_seconds=total_seconds,
            tokens_per_second=None,
            peak_cuda_allocated_bytes=int(self.torch.cuda.max_memory_allocated()),
            peak_cuda_reserved_bytes=int(self.torch.cuda.max_memory_reserved()),
            processor_metrics=prepared.processor_metrics if prepared else None,
            provenance=self.provenance,
        )


class Qwen3VLRuntimeFactory:
    """Load the native Qwen model once using explicit CUDA/BF16/SDPA."""

    def __init__(
        self,
        *,
        torch_module: Any | None = None,
        auto_processor_class: Any | None = None,
        auto_model_class: Any | None = None,
        expected_processor_class: Any | None = None,
        expected_model_class: Any | None = None,
        transformers_version: str | None = None,
    ) -> None:
        self._torch = torch_module
        self._auto_processor = auto_processor_class
        self._auto_model = auto_model_class
        self._expected_processor = expected_processor_class
        self._expected_model = expected_model_class
        self._transformers_version = transformers_version

    def create(self, artifact: ResolvedQwen3VLArtifact) -> Qwen3VLRuntime:
        (
            torch_module,
            auto_processor,
            auto_model,
            expected_processor,
            expected_model,
            transformers_version,
        ) = self._dependencies()
        _validate_cuda_bf16(torch_module)
        try:
            processor = auto_processor.from_pretrained(
                str(artifact.snapshot_dir),
                trust_remote_code=False,
                local_files_only=True,
            )
            model = auto_model.from_pretrained(
                str(artifact.snapshot_dir),
                trust_remote_code=False,
                local_files_only=True,
                use_safetensors=True,
                dtype=torch_module.bfloat16,
                attn_implementation=EXPECTED_ATTENTION,
            )
            model = model.to("cuda")
            model.eval()
            torch_module.cuda.synchronize()
        except torch_module.OutOfMemoryError as exc:
            torch_module.cuda.empty_cache()
            raise Qwen3VLCudaOutOfMemoryError(
                "Pinned Qwen model does not fit the CUDA baseline during loading."
            ) from exc
        except Exception as exc:
            raise Qwen3VLModelLoadError(
                "Pinned snapshot could not load through AutoProcessor/"
                "AutoModelForMultimodalLM with CUDA BF16 SDPA; no fallback was "
                f"attempted ({type(exc).__name__}): {exc}"
            ) from exc
        validate_runtime_classes(
            processor,
            model,
            expected_processor_class=expected_processor,
            expected_model_class=expected_model,
        )
        provenance, patch_size, merge_size = inspect_loaded_runtime(
            torch_module,
            processor,
            model,
            artifact,
            transformers_version=transformers_version,
        )
        return Qwen3VLRuntime(
            torch=torch_module,
            processor=processor,
            model=model,
            provenance=provenance,
            patch_size=patch_size,
            merge_size=merge_size,
        )

    def _dependencies(self) -> tuple[Any, Any, Any, Any, Any, str]:
        supplied = (
            self._torch,
            self._auto_processor,
            self._auto_model,
            self._expected_processor,
            self._expected_model,
            self._transformers_version,
        )
        if all(value is not None for value in supplied):
            return supplied  # type: ignore[return-value]
        try:
            import torch
            import transformers
            from transformers import (
                AutoModelForMultimodalLM,
                AutoProcessor,
                Qwen3VLForConditionalGeneration,
                Qwen3VLProcessor,
            )
        except ImportError as exc:
            raise Qwen3VLModelLoadError(
                "Native Qwen3-VL dependencies are unavailable; install requirements-ai.txt."
            ) from exc
        return (
            self._torch or torch,
            self._auto_processor or AutoProcessor,
            self._auto_model or AutoModelForMultimodalLM,
            self._expected_processor or Qwen3VLProcessor,
            self._expected_model or Qwen3VLForConditionalGeneration,
            self._transformers_version or str(transformers.__version__),
        )


class Qwen3VLProvider:
    """Lazy experimental provider; construction performs no I/O or model loading."""

    def __init__(
        self,
        *,
        resolver: Qwen3VLArtifactResolver | None = None,
        runtime_factory: Qwen3VLRuntimeFactory | None = None,
        local_files_only: bool = False,
    ) -> None:
        self.resolver = resolver or Qwen3VLArtifactResolver()
        self.runtime_factory = runtime_factory or Qwen3VLRuntimeFactory()
        self.local_files_only = local_files_only
        self.artifact_resolution_seconds = 0.0
        self.model_load_seconds = 0.0
        self._artifact: ResolvedQwen3VLArtifact | None = None
        self._runtime: Qwen3VLRuntime | None = None

    def runtime(self) -> Qwen3VLRuntime:
        if self._runtime is None:
            started = time.perf_counter()
            self._artifact = self.resolver.resolve(
                local_files_only=self.local_files_only
            )
            self.artifact_resolution_seconds = time.perf_counter() - started
            started = time.perf_counter()
            self._runtime = self.runtime_factory.create(self._artifact)
            self.model_load_seconds = time.perf_counter() - started
        return self._runtime


class QwenBinaryAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str
    answer: BinaryAnswer
    validation_error: str | None
    generation: QwenGeneration


class QwenBinaryEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    start_timestamp_us: int = Field(ge=0)
    end_timestamp_us: int = Field(ge=0)
    selected_frame_timestamps_us: tuple[int, ...]
    selected_frame_paths: tuple[str, ...]
    silver_overlaps: tuple[SilverIntervalReference, ...]
    answers: tuple[QwenBinaryAttempt, ...]

    def answer_for(self, category: str) -> BinaryAnswer:
        for attempt in self.answers:
            if attempt.category == category:
                return attempt.answer
        raise Qwen3VLBenchmarkError(
            f"Binary result for {self.event_id} lacks category '{category}'."
        )


class LatencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_count: int = Field(ge=0)
    total_processor_seconds: float = Field(ge=0.0)
    total_generation_seconds: float = Field(ge=0.0)
    total_request_seconds: float = Field(ge=0.0)
    mean_request_seconds: float | None = Field(default=None, ge=0.0)
    p50_request_seconds: float | None = Field(default=None, ge=0.0)
    p90_request_seconds: float | None = Field(default=None, ge=0.0)
    p95_request_seconds: float | None = Field(default=None, ge=0.0)
    maximum_request_seconds: float | None = Field(default=None, ge=0.0)
    total_generated_tokens: int = Field(ge=0)


class QwenBinarySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_count: int = Field(ge=1)
    request_count: int = Field(ge=1)
    valid_yes_no_count: int = Field(ge=0)
    valid_yes_no_rate: float = Field(ge=0.0, le=1.0)
    valid_yes_count: int = Field(ge=0)
    valid_no_count: int = Field(ge=0)
    unverified_count: int = Field(ge=0)
    known_unsafe_detected_intervals: int = Field(ge=0)
    total_intervals: int = Field(ge=1)
    known_unsafe_recall: float = Field(ge=0.0, le=1.0)
    category_detected_intervals: int = Field(ge=0)
    category_aware_recall: float = Field(ge=0.0, le=1.0)
    category_metrics: tuple[CategoryBinaryMetrics, ...]
    missed_interval_ids: tuple[str, ...]
    latency: LatencySummary
    latency_by_image_count: dict[int, LatencySummary]
    peak_cuda_allocated_bytes: int = Field(ge=0)
    peak_cuda_reserved_bytes: int = Field(ge=0)


class SmokeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    image_count: int
    category: str
    raw_answer_text: str
    parsed_answer: BinaryAnswer
    succeeded: bool
    generation: QwenGeneration


class QwenSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    experimental: Literal[True] = True
    artifact_resolution_seconds: float = Field(ge=0.0)
    model_load_seconds: float = Field(ge=0.0)
    provenance: QwenRuntimeProvenance
    token_budget: QwenOutputTokenBudget
    cache_validation: dict[str, Any]
    cases: tuple[SmokeCase, ...]
    six_image_gate_passed: bool


class SmolQwenComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    smol_artifact_path: str
    metrics: dict[str, dict[str, Any]]


class QwenBinaryCapabilityReport(BaseModel):
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
    provenance: QwenRuntimeProvenance
    token_budget: QwenOutputTokenBudget
    generation_settings: dict[str, Any]
    events: tuple[QwenBinaryEventResult, ...]
    summary: QwenBinarySummary
    comparison: SmolQwenComparison
    metric_notes: tuple[str, ...]


def build_qwen_binary_conversation(
    request: VLMVerificationRequest,
    category: str,
) -> list[dict[str, Any]]:
    try:
        question = CATEGORY_QUESTIONS[category]
    except KeyError as exc:
        raise Qwen3VLBenchmarkError(
            f"Unknown binary capability category '{category}'."
        ) from exc
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Inspect every supplied frame. The images are one time-ordered event. "
                "Report only visible evidence and do not infer unseen events from "
                "dialogue or context.\n"
            ),
        }
    ]
    for descriptor, image in zip(
        request.metadata.frames, request.images, strict=True
    ):
        content.extend(
            (
                {"type": "text", "text": f"Frame {descriptor.frame_index}:\n"},
                {"type": "image", "image": image},
            )
        )
    content.append(
        {"type": "text", "text": f"Question: {question}\nAnswer only YES or NO."}
    )
    return [{"role": "user", "content": content}]


def extract_processor_metrics(
    encoded: Any,
    request: VLMVerificationRequest,
    *,
    patch_size: int,
    merge_size: int,
) -> QwenProcessorMetrics:
    try:
        pixel_values = encoded["pixel_values"]
        grid_tensor = encoded["image_grid_thw"]
        input_ids = encoded["input_ids"]
        grids = grid_tensor.tolist()
    except Exception as exc:
        raise Qwen3VLModelContractError(
            f"Qwen processor outputs are incomplete ({type(exc).__name__})."
        ) from exc
    if len(grids) != len(request.images):
        raise Qwen3VLModelContractError(
            "Qwen image_grid_thw count does not match the supplied image count."
        )
    if getattr(input_ids, "ndim", None) != 2 or int(input_ids.shape[0]) != 1:
        raise Qwen3VLModelContractError("Qwen input_ids must have shape [1, sequence].")
    image_metrics: list[QwenImageMetric] = []
    for image, raw_grid in zip(request.images, grids, strict=True):
        if len(raw_grid) != 3:
            raise Qwen3VLModelContractError("Qwen image grid must contain T/H/W.")
        grid = tuple(int(value) for value in raw_grid)
        if any(value <= 0 for value in grid):
            raise Qwen3VLModelContractError("Qwen image grid dimensions must be positive.")
        product = grid[0] * grid[1] * grid[2]
        divisor = merge_size * merge_size
        if product % divisor:
            raise Qwen3VLModelContractError(
                "Qwen visual grid is incompatible with the configured spatial merge."
            )
        image_metrics.append(
            QwenImageMetric(
                source=ImageDimensions(width=image.width, height=image.height),
                processed=ImageDimensions(
                    width=grid[2] * patch_size,
                    height=grid[1] * patch_size,
                ),
                grid_thw=grid,
                visual_tokens=product // divisor,
            )
        )
    return QwenProcessorMetrics(
        input_image_count=len(request.images),
        images=tuple(image_metrics),
        pixel_values_shape=tuple(int(value) for value in pixel_values.shape),
        image_grid_thw_shape=tuple(int(value) for value in grid_tensor.shape),
        input_ids_shape=tuple(int(value) for value in input_ids.shape),
        total_visual_tokens=sum(item.visual_tokens for item in image_metrics),
        input_sequence_length=int(input_ids.shape[1]),
    )


def run_smoke_benchmark(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    *,
    frame_cache_root: str | Path,
    provider: Qwen3VLProvider,
) -> QwenSmokeReport:
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = provider.runtime()
    budget = runtime.inspect_output_budget()
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    cases: list[SmokeCase] = []
    for count in SMOKE_IMAGE_COUNTS:
        event = next(
            (event for event in known_events if len(event.selected_frames) == count),
            None,
        )
        if event is None:
            raise Qwen3VLBenchmarkError(
                f"Known-silver cache has no unchanged {count}-image event for smoke."
            )
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        try:
            generation = runtime.generate_binary(
                request,
                "weapons",
                max_new_tokens=budget.max_new_tokens,
            )
        finally:
            for image in images:
                image.close()
        answer = (
            BinaryAnswer.UNVERIFIED
            if generation.error is not None or generation.truncated
            else parse_binary_answer(generation.raw_generated_text)
        )
        succeeded = generation.error is None and generation.processor_metrics is not None
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
    gate = len(cases) == len(SMOKE_IMAGE_COUNTS) and all(
        case.succeeded for case in cases
    )
    return QwenSmokeReport(
        artifact_resolution_seconds=provider.artifact_resolution_seconds,
        model_load_seconds=provider.model_load_seconds,
        provenance=runtime.provenance,
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
    provider: Qwen3VLProvider,
    smoke: QwenSmokeReport,
    smol_baseline_path: str | Path,
    progress_callback: Callable[[int, int], None] | None = None,
) -> QwenBinaryCapabilityReport:
    if not smoke.six_image_gate_passed:
        raise Qwen3VLBenchmarkError(
            "Six-image smoke gate failed; the 144-request quality run is forbidden."
        )
    known_events = validate_known_silver_inputs(
        events_artifact, ground_truth, frame_manifest
    )
    runtime = provider.runtime()
    entries = {entry.sample_id: entry for entry in frame_manifest.entries}
    records: list[QwenBinaryEventResult] = []
    total = len(known_events) * len(CATEGORY_IDS)
    completed = 0
    for event in known_events:
        event_entries = entries_for_event(event, entries)
        request, images = build_verification_request(
            event, event_entries, Path(frame_cache_root).resolve()
        )
        attempts: list[QwenBinaryAttempt] = []
        try:
            for category in CATEGORY_IDS:
                generation = runtime.generate_binary(
                    request,
                    category,
                    max_new_tokens=smoke.token_budget.max_new_tokens,
                )
                answer = (
                    BinaryAnswer.UNVERIFIED
                    if generation.error is not None or generation.truncated
                    else parse_binary_answer(generation.raw_generated_text)
                )
                attempts.append(
                    QwenBinaryAttempt(
                        category=category,
                        answer=answer,
                        validation_error=_validation_error(generation, answer),
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
            QwenBinaryEventResult(
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
    summary = summarize_qwen_binary(records, ground_truth.intervals)
    comparison = compare_with_smol(summary, smol_baseline_path)
    return QwenBinaryCapabilityReport(
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
            "do_sample": False,
            "num_beams": 1,
            "temperature": None,
            "max_new_tokens": smoke.token_budget.max_new_tokens,
            "processor_pixel_limits": "pinned defaults",
            "quantization": None,
        },
        events=tuple(records),
        summary=summary,
        comparison=comparison,
        metric_notes=(
            "The exact six SmolVLM category questions and strict parser are reused.",
            "Unexpected YES responses are not false positives because silver annotations are not exhaustive.",
            "No movie, preprocessing, Stage-1, clustering, or frame selection was rerun.",
        ),
    )


def validate_known_silver_inputs(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
) -> tuple[CandidateEvent, ...]:
    known_events = tuple(
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
    known_images = sum(len(event.selected_frames) for event in known_events)
    if len(ground_truth.intervals) != EXPECTED_SILVER_INTERVALS:
        raise Qwen3VLBenchmarkError(
            f"Ground truth has {len(ground_truth.intervals)} intervals; expected 16."
        )
    if len(known_events) != EXPECTED_KNOWN_SILVER_EVENTS:
        raise Qwen3VLBenchmarkError(
            f"Known-silver subset has {len(known_events)} events; expected 24."
        )
    if known_images != EXPECTED_KNOWN_SILVER_IMAGES:
        raise Qwen3VLBenchmarkError(
            f"Known-silver subset has {known_images} images; expected 104."
        )
    if not frame_manifest.all_references_resolved:
        raise Qwen3VLBenchmarkError("Selected-frame cache is not fully resolved.")
    return known_events


def cache_validation_summary(
    events_artifact: ExperimentalCandidateEventsArtifact,
    ground_truth: GroundTruthArtifact,
    frame_manifest: SelectedFrameCacheManifest,
    known_events: Sequence[CandidateEvent],
) -> dict[str, Any]:
    return {
        "total_events": len(events_artifact.events),
        "total_cached_images": len(frame_manifest.entries),
        "silver_intervals": len(ground_truth.intervals),
        "known_silver_events": len(known_events),
        "known_silver_images": sum(len(event.selected_frames) for event in known_events),
        "all_references_resolved": frame_manifest.all_references_resolved,
    }


def summarize_qwen_binary(
    records: Sequence[QwenBinaryEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> QwenBinarySummary:
    attempts = [attempt for record in records for attempt in record.answers]
    counts = Counter(attempt.answer for attempt in attempts)
    detected = 0
    category_detected = 0
    missed: list[str] = []
    for index, interval in enumerate(intervals):
        interval_id = f"silver:{index:03d}"
        matching = records_for_interval(records, interval_id)
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
    category_metrics = tuple(
        summarize_category(category, records, intervals) for category in CATEGORY_IDS
    )
    by_count: dict[int, list[QwenGeneration]] = defaultdict(list)
    for record in records:
        by_count[len(record.selected_frame_timestamps_us)].extend(
            attempt.generation for attempt in record.answers
        )
    generations = tuple(attempt.generation for attempt in attempts)
    valid_count = counts[BinaryAnswer.YES] + counts[BinaryAnswer.NO]
    return QwenBinarySummary(
        event_count=len(records),
        request_count=len(attempts),
        valid_yes_no_count=valid_count,
        valid_yes_no_rate=valid_count / len(attempts),
        valid_yes_count=counts[BinaryAnswer.YES],
        valid_no_count=counts[BinaryAnswer.NO],
        unverified_count=counts[BinaryAnswer.UNVERIFIED],
        known_unsafe_detected_intervals=detected,
        total_intervals=len(intervals),
        known_unsafe_recall=detected / len(intervals),
        category_detected_intervals=category_detected,
        category_aware_recall=category_detected / len(intervals),
        category_metrics=category_metrics,
        missed_interval_ids=tuple(missed),
        latency=summarize_latency(generations),
        latency_by_image_count={
            count: summarize_latency(values) for count, values in sorted(by_count.items())
        },
        peak_cuda_allocated_bytes=max(
            generation.peak_cuda_allocated_bytes for generation in generations
        ),
        peak_cuda_reserved_bytes=max(
            generation.peak_cuda_reserved_bytes for generation in generations
        ),
    )


def summarize_category(
    category: str,
    records: Sequence[QwenBinaryEventResult],
    intervals: Sequence[GroundTruthInterval],
) -> CategoryBinaryMetrics:
    matching_intervals = [
        (index, interval)
        for index, interval in enumerate(intervals)
        if interval.category == category
    ]
    detected = 0
    for index, _interval in matching_intervals:
        interval_records = records_for_interval(records, f"silver:{index:03d}")
        detected += any(
            record.answer_for(category) == BinaryAnswer.YES
            for record in interval_records
        )
    attempts = [
        attempt
        for record in records
        for attempt in record.answers
        if attempt.category == category
    ]
    counts = Counter(attempt.answer for attempt in attempts)
    total = len(matching_intervals)
    return CategoryBinaryMetrics(
        category=category,
        silver_intervals=total,
        detected_intervals=detected,
        recall=detected / total if total else None,
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


def summarize_latency(generations: Iterable[QwenGeneration]) -> LatencySummary:
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


def compare_with_smol(
    qwen: QwenBinarySummary,
    smol_baseline_path: str | Path,
) -> SmolQwenComparison:
    path = Path(smol_baseline_path).resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        smol = payload["summary"]
        smol_categories = {
            item["category"]: item for item in smol["category_metrics"]
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Qwen3VLBenchmarkError(
            f"Smol baseline artifact is invalid ({type(exc).__name__})."
        ) from exc
    qwen_categories = {item.category: item for item in qwen.category_metrics}
    metrics: dict[str, dict[str, Any]] = {
        "binary_validity": {
            "smolvlm2_500m": smol["valid_yes_no_rate"],
            "qwen3vl_2b": qwen.valid_yes_no_rate,
        },
        "any_category_recall": {
            "smolvlm2_500m": smol["known_unsafe_recall"],
            "qwen3vl_2b": qwen.known_unsafe_recall,
        },
        "category_aware_recall": {
            "smolvlm2_500m": smol["category_aware_recall"],
            "qwen3vl_2b": qwen.category_aware_recall,
        },
        "aggregate_request_seconds": {
            "smolvlm2_500m": smol["latency"]["total_request_seconds"],
            "qwen3vl_2b": qwen.latency.total_request_seconds,
        },
        "generation_seconds": {
            "smolvlm2_500m": smol["latency"]["total_generation_seconds"],
            "qwen3vl_2b": qwen.latency.total_generation_seconds,
        },
        "mean_request_seconds": {
            "smolvlm2_500m": smol["latency"]["mean_request_seconds"],
            "qwen3vl_2b": qwen.latency.mean_request_seconds,
        },
        "peak_cuda_allocated_bytes": {
            "smolvlm2_500m": _smol_peak(payload, "peak_cuda_allocated_bytes"),
            "qwen3vl_2b": qwen.peak_cuda_allocated_bytes,
        },
    }
    for category in CATEGORY_IDS:
        metrics[f"{category}_recall"] = {
            "smolvlm2_500m": smol_categories[category]["recall"],
            "qwen3vl_2b": qwen_categories[category].recall,
        }
    return SmolQwenComparison(smol_artifact_path=str(path), metrics=metrics)


def records_for_interval(
    records: Sequence[QwenBinaryEventResult], interval_id: str
) -> tuple[QwenBinaryEventResult, ...]:
    return tuple(
        record
        for record in records
        if any(
            overlap.interval_id == interval_id and overlap.exact_overlap
            for overlap in record.silver_overlaps
        )
    )


def entries_for_event(
    event: CandidateEvent,
    entries: dict[str, CachedSelectedFrame],
) -> tuple[CachedSelectedFrame, ...]:
    try:
        return tuple(entries[item.sample.sample_id] for item in event.selected_frames)
    except KeyError as exc:
        raise Qwen3VLBenchmarkError(
            f"Cached selected frame is missing for {event.event_id}: {exc.args[0]}"
        ) from exc


def inspect_loaded_runtime(
    torch_module: Any,
    processor: Any,
    model: Any,
    artifact: ResolvedQwen3VLArtifact,
    *,
    transformers_version: str,
) -> tuple[QwenRuntimeProvenance, int, int]:
    try:
        parameters = list(model.parameters())
        parameter_count = sum(int(parameter.numel()) for parameter in parameters)
        devices = {str(parameter.device.type) for parameter in parameters}
        floating_dtypes = {
            str(parameter.dtype).removeprefix("torch.")
            for parameter in parameters
            if bool(parameter.is_floating_point())
        }
        attention = str(model.config._attn_implementation)
        vision_config = model.config.vision_config
        patch_size = int(vision_config.patch_size)
        merge_size = int(vision_config.spatial_merge_size)
    except Exception as exc:
        raise Qwen3VLModelContractError(
            f"Loaded Qwen metadata is not inspectable ({type(exc).__name__})."
        ) from exc
    if parameter_count != EXPECTED_PARAMETER_COUNT:
        raise Qwen3VLModelContractError(
            f"Loaded parameter count is {parameter_count}, expected {EXPECTED_PARAMETER_COUNT}."
        )
    if devices != {"cuda"}:
        raise Qwen3VLModelContractError(
            f"Loaded Qwen parameters are not entirely on CUDA: {sorted(devices)}."
        )
    if floating_dtypes != {EXPECTED_DTYPE}:
        raise Qwen3VLModelContractError(
            f"Loaded Qwen floating dtypes are {sorted(floating_dtypes)}, expected BF16."
        )
    if attention != EXPECTED_ATTENTION:
        raise Qwen3VLModelContractError(
            f"Loaded attention backend is {attention}, expected {EXPECTED_ATTENTION}."
        )
    if patch_size <= 0 or merge_size <= 0:
        raise Qwen3VLModelContractError("Loaded Qwen visual geometry is invalid.")
    properties = torch_module.cuda.get_device_properties(0)
    return (
        QwenRuntimeProvenance(
            repository_id=MODEL_REPOSITORY_ID,
            revision=MODEL_REVISION,
            checkpoint_sha256=artifact.sha256,
            model_class=type(model).__name__,
            processor_class=type(processor).__name__,
            parameter_count=parameter_count,
            model_dtype=EXPECTED_DTYPE,
            device="cuda",
            transformers_version=transformers_version,
            torch_version=str(torch_module.__version__),
            attention_implementation=attention,
            gpu_name=str(torch_module.cuda.get_device_name(0)),
            gpu_total_memory_bytes=int(properties.total_memory),
            gpu_compute_capability=tuple(
                int(value) for value in torch_module.cuda.get_device_capability(0)
            ),
            cuda_bf16_supported=True,
            steady_model_cuda_allocated_bytes=int(
                torch_module.cuda.memory_allocated()
            ),
            steady_model_cuda_reserved_bytes=int(torch_module.cuda.memory_reserved()),
        ),
        patch_size,
        merge_size,
    )


def validate_runtime_classes(
    processor: Any,
    model: Any,
    *,
    expected_processor_class: type[Any],
    expected_model_class: type[Any],
) -> None:
    if not isinstance(processor, expected_processor_class) or (
        type(processor).__name__ != EXPECTED_PROCESSOR_CLASS
    ):
        raise Qwen3VLModelContractError(
            "Loaded processor is not the expected native Qwen3VLProcessor."
        )
    if not isinstance(model, expected_model_class) or (
        type(model).__name__ != EXPECTED_MODEL_CLASS
    ):
        raise Qwen3VLModelContractError(
            "Loaded model is not the expected native Qwen3VLForConditionalGeneration."
        )


def _validate_cuda_bf16(torch_module: Any) -> None:
    if not bool(torch_module.cuda.is_available()):
        raise Qwen3VLModelLoadError("CUDA is required for this Qwen experiment.")
    if not bool(torch_module.cuda.is_bf16_supported()):
        raise Qwen3VLModelLoadError(
            "CUDA BF16 is required for this Qwen experiment and is unsupported."
        )


def _move_model_inputs(batch: Any, *, device: str, dtype: Any) -> dict[str, Any]:
    try:
        moved = batch.to(device=device, dtype=dtype)
        return dict(moved)
    except Exception as exc:
        raise Qwen3VLModelContractError(
            f"Qwen processor tensors could not move to CUDA BF16 ({type(exc).__name__})."
        ) from exc


def _generation_eos_ids(model: Any, tokenizer: Any) -> tuple[int, ...]:
    raw = getattr(getattr(model, "generation_config", None), "eos_token_id", None)
    if raw is None:
        raw = getattr(tokenizer, "eos_token_id", None)
    if raw is None:
        raise Qwen3VLModelContractError("Loaded Qwen configuration has no EOS token.")
    values = raw if isinstance(raw, (list, tuple)) else (raw,)
    result = tuple(int(value) for value in values)
    if not result or any(value < 0 for value in result):
        raise Qwen3VLModelContractError("Loaded Qwen EOS token contract is invalid.")
    return result


def _token_count(tokenizer: Any, value: str) -> int:
    encoded = tokenizer(value, add_special_tokens=False)
    ids = encoded["input_ids"]
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    count = len(ids)
    if count <= 0:
        raise Qwen3VLModelContractError(
            f"Qwen tokenizer produced no tokens for {value!r}."
        )
    return count


def _validation_error(
    generation: QwenGeneration,
    answer: BinaryAnswer,
) -> str | None:
    if generation.error is not None:
        return generation.error
    if generation.truncated:
        return "generation was truncated"
    if answer == BinaryAnswer.UNVERIFIED:
        return "generated text is not strict YES or NO"
    return None


def _verify_file_manifest(paths: dict[str, Path]) -> None:
    for filename, (expected_size, expected_sha) in MODEL_FILE_MANIFEST.items():
        path = paths.get(filename)
        if path is None or not path.is_file():
            raise Qwen3VLArtifactIntegrityError(
                f"Pinned Qwen artifact is missing: {filename}."
            )
        size = path.stat().st_size
        if size != expected_size:
            raise Qwen3VLArtifactIntegrityError(
                f"Pinned Qwen artifact size mismatch for {filename}: "
                f"expected {expected_size}, got {size}."
            )
        digest = _sha256_file(path)
        if digest != expected_sha:
            raise Qwen3VLArtifactIntegrityError(
                f"Pinned Qwen artifact SHA-256 mismatch for {filename}: "
                f"expected {expected_sha}, got {digest}."
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile for an empty sequence.")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _smol_peak(payload: dict[str, Any], key: str) -> int | None:
    values = [
        attempt.get("generation", {}).get(key)
        for event in payload.get("events", [])
        for attempt in event.get("answers", [])
    ]
    numeric = [int(value) for value in values if value is not None]
    return max(numeric) if numeric else None
