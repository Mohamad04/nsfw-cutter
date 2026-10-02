from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from core.paths import get_model_cache_dir
from services.analysis.cancellation import CancellationToken

MODEL_REPOSITORY_ID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
MODEL_REVISION = "7b375e1b73b11138ff12fe22c8f2822d8fe03467"
MODEL_WEIGHTS_FILENAME = "model.safetensors"
MODEL_WEIGHTS_SIZE = 2_029_990_624
MODEL_WEIGHTS_SHA256 = (
    "b9bfd456c9472c0acd5719d6e514c4b859891af205ee1a736552fd3497b8b0c3"
)
EXPECTED_MODEL_CLASS = "SmolVLMForConditionalGeneration"
EXPECTED_PROCESSOR_CLASS = "SmolVLMProcessor"
EXPECTED_PARAMETER_COUNT = 507_482_304
EXPECTED_CONTEXT_LENGTH = 8192

# Every runtime file is pinned and integrity checked. Pickle weights are intentionally absent.
MODEL_FILE_MANIFEST: dict[str, tuple[int, str]] = {
    MODEL_WEIGHTS_FILENAME: (MODEL_WEIGHTS_SIZE, MODEL_WEIGHTS_SHA256),
    "config.json": (
        3_767,
        "ea6bc1237e96247f6258de3e202e2e62b93d6f386dc47e7b36b5588bf3a15e17",
    ),
    "preprocessor_config.json": (
        599,
        "149e315d9410368e5491455bb06e0f763426e9e56cca731c13b24404a29b6374",
    ),
    "processor_config.json": (
        67,
        "f3ad45028447b3562b4752be0d5916d6806c1ef589091a469608dcf0faa1737c",
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
        28_626,
        "dd9ce2ab89a3dd881bd9378f1a79b943a064b9275a7e1706d5b7b47b68977913",
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


@dataclass(frozen=True)
class SmolVLMModelSpec:
    """Pinned native SmolVLM identity, artifact, and runtime contract."""

    repository_id: str
    revision: str
    file_manifest: Mapping[str, tuple[int, str]]
    primary_artifact_filename: str
    primary_artifact_sha256: str
    expected_model_class: str
    expected_processor_class: str
    expected_parameter_count: int
    expected_context_length: int


def default_smolvlm_model_spec() -> SmolVLMModelSpec:
    """Build the original 500M specification from compatibility constants."""
    return SmolVLMModelSpec(
        repository_id=MODEL_REPOSITORY_ID,
        revision=MODEL_REVISION,
        file_manifest=MODEL_FILE_MANIFEST,
        primary_artifact_filename=MODEL_WEIGHTS_FILENAME,
        primary_artifact_sha256=MODEL_WEIGHTS_SHA256,
        expected_model_class=EXPECTED_MODEL_CLASS,
        expected_processor_class=EXPECTED_PROCESSOR_CLASS,
        expected_parameter_count=EXPECTED_PARAMETER_COUNT,
        expected_context_length=EXPECTED_CONTEXT_LENGTH,
    )


class SmolVLMError(RuntimeError):
    """Base error for the isolated experimental SmolVLM verifier."""


class SmolVLMArtifactUnavailableError(SmolVLMError):
    """The exact pinned snapshot could not be resolved."""


class SmolVLMArtifactIntegrityError(SmolVLMError):
    """A pinned artifact failed its size or SHA-256 check."""


class SmolVLMModelLoadError(SmolVLMError):
    """The pinned snapshot failed to load through native Transformers."""


class SmolVLMModelContractError(SmolVLMError):
    """Runtime inspection contradicted the verified model contract."""


class SmolVLMCudaOutOfMemoryError(SmolVLMError):
    """The explicit CUDA experiment exceeded available device memory."""


class SmolVLMRequestError(SmolVLMError):
    """An isolated verification request is invalid."""


@dataclass(frozen=True)
class ResolvedSmolVLMArtifact:
    snapshot_dir: Path
    weights_path: Path
    sha256: str
    resolved_files: tuple[Path, ...]
    model_spec: SmolVLMModelSpec


class SmolVLMArtifactResolver:
    """Lazily resolve and verify the exact evaluation snapshot."""

    def __init__(
        self,
        *,
        model_cache_dir: str | Path | None = None,
        hub_download: Callable[..., str] | None = None,
        model_spec: SmolVLMModelSpec | None = None,
    ) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir)
            if model_cache_dir is not None
            else get_model_cache_dir()
        )
        self._hub_download = hub_download
        self.model_spec = model_spec or default_smolvlm_model_spec()

    def resolve(self, *, local_files_only: bool = False) -> ResolvedSmolVLMArtifact:
        download = self._hub_download
        if download is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise SmolVLMArtifactUnavailableError(
                    "huggingface_hub is unavailable; install requirements-ai.txt."
                ) from exc
            download = hf_hub_download

        resolved: list[Path] = []
        for filename in self.model_spec.file_manifest:
            try:
                path = Path(
                    download(
                        repo_id=self.model_spec.repository_id,
                        filename=filename,
                        revision=self.model_spec.revision,
                        cache_dir=self.model_cache_dir,
                        local_files_only=local_files_only,
                    )
                )
            except Exception as exc:
                source = "local model cache" if local_files_only else "Hugging Face Hub"
                raise SmolVLMArtifactUnavailableError(
                    f"Unable to resolve pinned SmolVLM file '{filename}' from {source} "
                    f"({type(exc).__name__})."
                ) from exc
            if not path.is_file():
                raise SmolVLMArtifactUnavailableError(
                    f"Pinned SmolVLM file '{filename}' is not readable."
                )
            resolved.append(path)

        snapshot_dirs = {path.parent.resolve() for path in resolved}
        if len(snapshot_dirs) != 1:
            raise SmolVLMArtifactUnavailableError(
                "Pinned SmolVLM files did not resolve to one local snapshot."
            )
        resolved_by_name = dict(
            zip(self.model_spec.file_manifest, resolved, strict=True)
        )
        _verify_file_manifest(
            resolved_by_name,
            manifest=self.model_spec.file_manifest,
        )
        return ResolvedSmolVLMArtifact(
            snapshot_dir=next(iter(snapshot_dirs)),
            weights_path=resolved_by_name[self.model_spec.primary_artifact_filename],
            sha256=self.model_spec.primary_artifact_sha256,
            resolved_files=tuple(resolved),
            model_spec=self.model_spec,
        )


class VerificationPolicy(BaseModel):
    """Explicit experiment policy; it does not interpret a free-form user prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    allowed_categories: tuple[str, ...] = Field(min_length=1)
    allowed_severities: tuple[str, ...] = Field(min_length=1)
    prompt_template_version: str = Field(min_length=1)
    experimental: Literal[True] = True
    production_approved: Literal[False] = False

    @field_validator("policy_id", "version", "prompt_template_version", mode="after")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("verification policy identity fields cannot be blank")
        return normalized

    @field_validator("allowed_categories", "allowed_severities", mode="after")
    @classmethod
    def unique_nonblank_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("verification policy allowlists cannot contain blanks")
        if len(normalized) != len(set(normalized)):
            raise ValueError("verification policy allowlists must be unique")
        return normalized


EXPERIMENTAL_VISUAL_SAFETY_POLICY = VerificationPolicy(
    policy_id="visual-safety-verifier",
    version="experimental-v1",
    allowed_categories=(
        "nudity",
        "sexual_content",
        "violence",
        "graphic_violence",
        "weapons",
        "drugs",
    ),
    allowed_severities=("low", "medium", "high"),
    prompt_template_version="smolvlm-json-v1",
)


class VLMFrameDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_index: int = Field(ge=1)
    timestamp_us: int = Field(ge=0)
    selection_reasons: tuple[str, ...] = ()

    @field_validator("selection_reasons", mode="after")
    @classmethod
    def nonblank_reasons(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("frame selection reasons cannot be blank")
        return values


class VLMVerificationRequestMetadata(BaseModel):
    """Pixel-free request metadata that can be persisted independently."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    frames: tuple[VLMFrameDescriptor, ...] = Field(min_length=1, max_length=6)
    policy: VerificationPolicy

    @model_validator(mode="after")
    def ordered_frames(self) -> VLMVerificationRequestMetadata:
        expected_indices = tuple(range(1, len(self.frames) + 1))
        actual_indices = tuple(frame.frame_index for frame in self.frames)
        if actual_indices != expected_indices:
            raise ValueError("frame indices must be consecutive and ordered from 1")
        timestamps = tuple(frame.timestamp_us for frame in self.frames)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("verification frames must be ordered by timestamp")
        return self


@dataclass(frozen=True)
class VLMVerificationRequest:
    """Provider-neutral metadata plus ephemeral, already-cropped PIL payloads."""

    metadata: VLMVerificationRequestMetadata
    images: tuple[Image.Image, ...]

    def __post_init__(self) -> None:
        if len(self.images) != len(self.metadata.frames):
            raise SmolVLMRequestError(
                "verification image count must match the ordered frame descriptors"
            )
        for image in self.images:
            if not isinstance(image, Image.Image):
                raise SmolVLMRequestError("verification payloads must be PIL images")
            if image.mode != "RGB":
                raise SmolVLMRequestError(
                    "verification images must already be cropped RGB PIL images"
                )
            if image.width <= 0 or image.height <= 0:
                raise SmolVLMRequestError("verification images must have positive size")


class GeneratedVerificationPayload(BaseModel):
    """Strict wire payload expected from the model-generated JSON object."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unsafe: StrictBool
    categories: tuple[str, ...]
    severity: str | None
    reason: str = Field(min_length=1, max_length=500)
    evidence_frame_indices: tuple[int, ...] = Field(max_length=6)

    @field_validator("reason", mode="after")
    @classmethod
    def bounded_nonblank_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("verification reason cannot be blank")
        return normalized

    @field_validator("categories", mode="after")
    @classmethod
    def unique_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("verification categories must be unique")
        return values

    @field_validator("evidence_frame_indices", mode="after")
    @classmethod
    def unique_evidence(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) != len(set(values)):
            raise ValueError("evidence frame indices must be unique")
        return values


class VerificationStatus(StrEnum):
    VERIFIED_UNSAFE = "verified_unsafe"
    VERIFIED_SAFE = "verified_safe"
    UNVERIFIED = "unverified"


class ImageDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ProcessorExpansionMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_splitting: bool
    input_image_count: int = Field(gt=0)
    original_image_dimensions: tuple[ImageDimensions, ...]
    pixel_values_shape: tuple[int, ...]
    visual_block_count: int = Field(gt=0)
    pixel_attention_mask_shape: tuple[int, ...] | None
    input_ids_shape: tuple[int, ...]
    pre_expansion_prompt_token_count: int = Field(gt=0)
    visual_token_count: int = Field(gt=0)
    non_visual_input_token_count: int = Field(ge=0)
    input_sequence_length: int = Field(gt=0)
    declared_context_length: int = Field(gt=0)
    remaining_context_before_generation: int
    remaining_context_after_requested_generation: int


class SmolVLMRuntimeProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    revision: str
    checkpoint_sha256: str
    model_class: str
    processor_class: str
    parameter_count: int
    model_dtype: str
    device: str
    transformers_version: str
    torch_version: str
    attention_implementation: str | None
    experimental: Literal[True] = True


class VLMVerificationResult(BaseModel):
    """Pixel-free result. A malformed or failed generation is always unverified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    status: VerificationStatus
    payload: GeneratedVerificationPayload | None
    evidence_timestamps_us: tuple[int, ...]
    raw_generated_text: str
    error: str | None
    truncated: bool
    generated_token_count: int = Field(ge=0)
    chat_template_seconds: float = Field(ge=0.0)
    processor_seconds: float = Field(ge=0.0)
    generation_seconds: float = Field(ge=0.0)
    decode_and_validation_seconds: float = Field(ge=0.0)
    total_seconds: float = Field(ge=0.0)
    tokens_per_second: float | None = Field(default=None, ge=0.0)
    expansion: ProcessorExpansionMetrics | None
    provenance: SmolVLMRuntimeProvenance


class RawSmolVLMGeneration(BaseModel):
    """Provider output before an experiment-specific structured parser runs."""

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
    expansion: ProcessorExpansionMetrics | None
    provenance: SmolVLMRuntimeProvenance


@dataclass
class PreparedSmolVLMRequest:
    model_inputs: Any
    prompt_input_length: int
    prompt_text: str
    chat_template_seconds: float
    processor_seconds: float
    expansion: ProcessorExpansionMetrics


@dataclass
class SmolVLMRuntime:
    torch: Any
    processor: Any
    model: Any
    provenance: SmolVLMRuntimeProvenance
    context_length: int
    image_splitting_supported: bool

    def prepare(
        self,
        request: VLMVerificationRequest,
        *,
        max_new_tokens: int,
        image_splitting: bool,
        conversation: list[dict[str, Any]] | None = None,
    ) -> PreparedSmolVLMRequest:
        if max_new_tokens <= 0:
            raise SmolVLMRequestError("max_new_tokens must be positive")
        if not self.image_splitting_supported and not image_splitting:
            raise SmolVLMModelContractError(
                "The installed official processor does not expose image-splitting control."
            )
        chat_started = time.perf_counter()
        resolved_conversation = conversation or _build_conversation(request.metadata)
        try:
            prompt = self.processor.apply_chat_template(
                resolved_conversation,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as exc:
            raise SmolVLMModelContractError(
                f"Pinned SmolVLM chat-template processing failed ({type(exc).__name__})."
            ) from exc
        chat_seconds = time.perf_counter() - chat_started

        processor_started = time.perf_counter()
        try:
            pre_expansion = self.processor.tokenizer(
                prompt,
                add_special_tokens=True,
                return_tensors="pt",
            )
            encoded = self.processor(
                text=[prompt],
                images=[list(request.images)],
                return_tensors="pt",
                do_image_splitting=image_splitting,
            )
        except Exception as exc:
            raise SmolVLMModelContractError(
                f"Pinned SmolVLM multi-image processing failed ({type(exc).__name__})."
            ) from exc
        processor_seconds = time.perf_counter() - processor_started
        expansion = _inspect_processor_expansion(
            self,
            request,
            encoded,
            pre_expansion,
            image_splitting=image_splitting,
            max_new_tokens=max_new_tokens,
        )
        if expansion.remaining_context_after_requested_generation < 0:
            raise SmolVLMModelContractError(
                "Processed request plus requested generation exceeds the declared context."
            )
        model_inputs = _move_model_inputs(
            encoded,
            device=self.provenance.device,
            dtype=getattr(self.model, "dtype", None),
        )
        return PreparedSmolVLMRequest(
            model_inputs=model_inputs,
            prompt_input_length=expansion.input_sequence_length,
            prompt_text=prompt,
            chat_template_seconds=chat_seconds,
            processor_seconds=processor_seconds,
            expansion=expansion,
        )

    def generate_raw(
        self,
        request: VLMVerificationRequest,
        conversation: list[dict[str, Any]],
        *,
        max_new_tokens: int,
        image_splitting: bool,
        cancellation: CancellationToken | None = None,
    ) -> RawSmolVLMGeneration:
        """Generate text for an explicit experimental conversation without parsing it."""
        started = time.perf_counter()
        if cancellation is not None and cancellation.is_cancelled:
            return self._raw_failure(
                request,
                error="generation cancelled before processing",
                total_seconds=time.perf_counter() - started,
            )
        try:
            prepared = self.prepare(
                request,
                max_new_tokens=max_new_tokens,
                image_splitting=image_splitting,
                conversation=conversation,
            )
        except SmolVLMError as exc:
            return self._raw_failure(
                request,
                error=str(exc),
                total_seconds=time.perf_counter() - started,
            )
        generation_started = time.perf_counter()
        try:
            stopping_criteria = _cancellation_stopping_criteria(cancellation)
            _synchronize_if_cuda(self.torch, self.provenance.device)
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **prepared.model_inputs,
                    do_sample=False,
                    num_beams=1,
                    max_new_tokens=max_new_tokens,
                    **(
                        {"stopping_criteria": stopping_criteria}
                        if stopping_criteria
                        else {}
                    ),
                )
            _synchronize_if_cuda(self.torch, self.provenance.device)
        except self.torch.OutOfMemoryError as exc:
            self.torch.cuda.empty_cache()
            raise SmolVLMCudaOutOfMemoryError(
                f"SmolVLM CUDA OOM for {len(request.images)} supplied images."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - model backend failure boundary
            return self._raw_failure(
                request,
                error=f"model generation failed ({type(exc).__name__})",
                prepared=prepared,
                generation_seconds=time.perf_counter() - generation_started,
                total_seconds=time.perf_counter() - started,
            )
        generation_seconds = time.perf_counter() - generation_started
        if cancellation is not None and cancellation.is_cancelled:
            return self._raw_failure(
                request,
                error="generation cancelled during generation",
                prepared=prepared,
                generation_seconds=generation_seconds,
                total_seconds=time.perf_counter() - started,
            )
        decode_started = time.perf_counter()
        try:
            sequences = getattr(generated, "sequences", generated)
            if getattr(sequences, "ndim", None) != 2 or int(sequences.shape[0]) != 1:
                raise SmolVLMModelContractError(
                    "Native generation did not return one token sequence."
                )
            new_tokens = sequences[:, prepared.prompt_input_length :]
            generated_count = int(new_tokens.shape[1])
            raw_text = self.processor.batch_decode(
                new_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
            truncated = _is_truncated(
                self.model,
                new_tokens,
                generated_count=generated_count,
                max_new_tokens=max_new_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - generated-output trust boundary
            return self._raw_failure(
                request,
                error=f"generated text decode failed ({type(exc).__name__}): {exc}",
                prepared=prepared,
                generation_seconds=generation_seconds,
                decode_seconds=time.perf_counter() - decode_started,
                total_seconds=time.perf_counter() - started,
            )
        decode_seconds = time.perf_counter() - decode_started
        return RawSmolVLMGeneration(
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
            expansion=prepared.expansion,
            provenance=self.provenance,
        )

    def verify(
        self,
        request: VLMVerificationRequest,
        *,
        max_new_tokens: int,
        image_splitting: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> VLMVerificationResult:
        started = time.perf_counter()
        if cancellation is not None and cancellation.is_cancelled:
            return self._unverified(
                request,
                error="verification cancelled before processing",
                total_seconds=time.perf_counter() - started,
            )
        try:
            prepared = self.prepare(
                request,
                max_new_tokens=max_new_tokens,
                image_splitting=image_splitting,
            )
        except SmolVLMError as exc:
            return self._unverified(
                request,
                error=str(exc),
                total_seconds=time.perf_counter() - started,
            )

        generation_started = time.perf_counter()
        try:
            stopping_criteria = _cancellation_stopping_criteria(cancellation)
            _synchronize_if_cuda(self.torch, self.provenance.device)
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **prepared.model_inputs,
                    do_sample=False,
                    num_beams=1,
                    max_new_tokens=max_new_tokens,
                    **(
                        {"stopping_criteria": stopping_criteria}
                        if stopping_criteria
                        else {}
                    ),
                )
            _synchronize_if_cuda(self.torch, self.provenance.device)
        except Exception as exc:  # noqa: BLE001 - model backend failure boundary
            return self._unverified(
                request,
                error=f"model generation failed ({type(exc).__name__})",
                prepared=prepared,
                generation_seconds=time.perf_counter() - generation_started,
                total_seconds=time.perf_counter() - started,
            )
        generation_seconds = time.perf_counter() - generation_started
        if cancellation is not None and cancellation.is_cancelled:
            return self._unverified(
                request,
                error="verification cancelled during generation",
                prepared=prepared,
                generation_seconds=generation_seconds,
                total_seconds=time.perf_counter() - started,
            )

        validation_started = time.perf_counter()
        try:
            sequences = getattr(generated, "sequences", generated)
            if getattr(sequences, "ndim", None) != 2 or int(sequences.shape[0]) != 1:
                raise SmolVLMModelContractError(
                    "Native generation did not return one token sequence."
                )
            new_tokens = sequences[:, prepared.prompt_input_length :]
            generated_count = int(new_tokens.shape[1])
            raw_text = self.processor.batch_decode(
                new_tokens,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]
            truncated = _is_truncated(
                self.model,
                new_tokens,
                generated_count=generated_count,
                max_new_tokens=max_new_tokens,
            )
            if truncated:
                raise ValueError(
                    "generation reached max_new_tokens without an EOS token"
                )
            payload = parse_verification_json(raw_text, request.metadata)
            status = (
                VerificationStatus.VERIFIED_UNSAFE
                if payload.unsafe
                else VerificationStatus.VERIFIED_SAFE
            )
            timestamps = tuple(
                request.metadata.frames[index - 1].timestamp_us
                for index in payload.evidence_frame_indices
            )
            validation_seconds = time.perf_counter() - validation_started
            return VLMVerificationResult(
                event_id=request.metadata.event_id,
                status=status,
                payload=payload,
                evidence_timestamps_us=timestamps,
                raw_generated_text=raw_text,
                error=None,
                truncated=False,
                generated_token_count=generated_count,
                chat_template_seconds=prepared.chat_template_seconds,
                processor_seconds=prepared.processor_seconds,
                generation_seconds=generation_seconds,
                decode_and_validation_seconds=validation_seconds,
                total_seconds=time.perf_counter() - started,
                tokens_per_second=(
                    generated_count / generation_seconds
                    if generation_seconds > 0.0
                    else None
                ),
                expansion=prepared.expansion,
                provenance=self.provenance,
            )
        except Exception as exc:  # noqa: BLE001 - generated-output trust boundary
            validation_seconds = time.perf_counter() - validation_started
            generated_count = locals().get("generated_count", 0)
            raw_text = locals().get("raw_text", "")
            truncated = bool(locals().get("truncated", False))
            return self._unverified(
                request,
                error=f"structured output invalid ({type(exc).__name__}): {exc}",
                raw_text=raw_text,
                generated_token_count=generated_count,
                truncated=truncated,
                prepared=prepared,
                generation_seconds=generation_seconds,
                validation_seconds=validation_seconds,
                total_seconds=time.perf_counter() - started,
            )

    def validate_generation_contract(
        self,
        *,
        image_count: int = 1,
        max_new_tokens: int = 1,
    ) -> ProcessorExpansionMetrics:
        """Gated real-model smoke check, including the observed pad-token discrepancy."""
        request = synthetic_verification_request(image_count)
        prepared = self.prepare(
            request,
            max_new_tokens=max_new_tokens,
            image_splitting=True,
        )
        try:
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **prepared.model_inputs,
                    do_sample=False,
                    num_beams=1,
                    max_new_tokens=max_new_tokens,
                )
            sequences = getattr(generated, "sequences", generated)
            if int(sequences.shape[1]) <= prepared.prompt_input_length:
                raise ValueError("generation returned no new token")
        except self.torch.OutOfMemoryError as exc:
            self.torch.cuda.empty_cache()
            raise SmolVLMCudaOutOfMemoryError(
                "Pinned SmolVLM generation contract exceeded CUDA memory."
            ) from exc
        except Exception as exc:
            raise SmolVLMModelContractError(
                "Pinned SmolVLM generation contract failed; token IDs were not repaired "
                f"or overwritten ({type(exc).__name__})."
            ) from exc
        return prepared.expansion

    def _unverified(
        self,
        request: VLMVerificationRequest,
        *,
        error: str,
        raw_text: str = "",
        generated_token_count: int = 0,
        truncated: bool = False,
        prepared: PreparedSmolVLMRequest | None = None,
        generation_seconds: float = 0.0,
        validation_seconds: float = 0.0,
        total_seconds: float,
    ) -> VLMVerificationResult:
        return VLMVerificationResult(
            event_id=request.metadata.event_id,
            status=VerificationStatus.UNVERIFIED,
            payload=None,
            evidence_timestamps_us=(),
            raw_generated_text=raw_text,
            error=error,
            truncated=truncated,
            generated_token_count=generated_token_count,
            chat_template_seconds=(prepared.chat_template_seconds if prepared else 0.0),
            processor_seconds=(prepared.processor_seconds if prepared else 0.0),
            generation_seconds=generation_seconds,
            decode_and_validation_seconds=validation_seconds,
            total_seconds=total_seconds,
            tokens_per_second=(
                generated_token_count / generation_seconds
                if generation_seconds > 0.0
                else None
            ),
            expansion=prepared.expansion if prepared else None,
            provenance=self.provenance,
        )

    def _raw_failure(
        self,
        request: VLMVerificationRequest,
        *,
        error: str,
        prepared: PreparedSmolVLMRequest | None = None,
        generation_seconds: float = 0.0,
        decode_seconds: float = 0.0,
        total_seconds: float,
    ) -> RawSmolVLMGeneration:
        return RawSmolVLMGeneration(
            event_id=request.metadata.event_id,
            raw_generated_text="",
            error=error,
            truncated=False,
            generated_token_count=0,
            chat_template_seconds=(prepared.chat_template_seconds if prepared else 0.0),
            processor_seconds=(prepared.processor_seconds if prepared else 0.0),
            generation_seconds=generation_seconds,
            decode_seconds=decode_seconds,
            total_seconds=total_seconds,
            tokens_per_second=None,
            expansion=prepared.expansion if prepared else None,
            provenance=self.provenance,
        )


class SmolVLMRuntimeFactory:
    """Load native SmolVLM classes on one explicit device; no fallback route."""

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

    def create(
        self,
        artifact: ResolvedSmolVLMArtifact,
        *,
        device: Literal["cpu", "cuda"] = "cpu",
        dtype: Literal["native", "bfloat16"] = "native",
        attention_implementation: str | None = None,
    ) -> SmolVLMRuntime:
        (
            torch_module,
            auto_processor,
            auto_model,
            expected_processor,
            expected_model,
            transformers_version,
        ) = self._dependencies()
        if device == "cuda" and not bool(torch_module.cuda.is_available()):
            raise SmolVLMModelLoadError("CUDA was requested but is unavailable.")
        if (
            device == "cuda"
            and dtype == "bfloat16"
            and not bool(torch_module.cuda.is_bf16_supported())
        ):
            raise SmolVLMModelLoadError(
                "CUDA BF16 was requested but the installed runtime/device rejects it."
            )
        if device not in {"cpu", "cuda"}:
            raise SmolVLMModelLoadError(f"Unsupported explicit device: {device}")
        model_kwargs: dict[str, Any] = {
            "trust_remote_code": False,
            "local_files_only": True,
            "use_safetensors": True,
        }
        if dtype != "native":
            model_kwargs["dtype"] = getattr(torch_module, dtype)
        if attention_implementation is not None:
            model_kwargs["attn_implementation"] = attention_implementation
        try:
            processor = auto_processor.from_pretrained(
                str(artifact.snapshot_dir),
                trust_remote_code=False,
                local_files_only=True,
            )
            model = auto_model.from_pretrained(
                str(artifact.snapshot_dir),
                **model_kwargs,
            )
            model = model.to(device)
            model.eval()
        except torch_module.OutOfMemoryError as exc:
            torch_module.cuda.empty_cache()
            raise SmolVLMCudaOutOfMemoryError(
                "Pinned SmolVLM model does not fit during explicit CUDA loading."
            ) from exc
        except Exception as exc:
            raise SmolVLMModelLoadError(
                "Pinned snapshot could not load through AutoProcessor/"
                "AutoModelForMultimodalLM; no fallback was attempted "
                f"({type(exc).__name__})."
            ) from exc
        spec = artifact.model_spec
        if not isinstance(processor, expected_processor) or (
            type(processor).__name__ != spec.expected_processor_class
        ):
            raise SmolVLMModelContractError(
                "Loaded processor is not the expected native SmolVLMProcessor."
            )
        if not isinstance(model, expected_model) or (
            type(model).__name__ != spec.expected_model_class
        ):
            raise SmolVLMModelContractError(
                "Loaded model is not the expected native "
                "SmolVLMForConditionalGeneration."
            )
        provenance, context_length = _inspect_loaded_model(
            torch_module,
            processor,
            model,
            artifact,
            device=device,
            transformers_version=transformers_version,
        )
        if dtype != "native" and provenance.model_dtype != dtype:
            raise SmolVLMModelContractError(
                f"Loaded model dtype is {provenance.model_dtype}, expected {dtype}."
            )
        if attention_implementation is not None and (
            provenance.attention_implementation != attention_implementation
        ):
            raise SmolVLMModelContractError(
                "Loaded attention implementation is "
                f"{provenance.attention_implementation}, expected "
                f"{attention_implementation}."
            )
        return SmolVLMRuntime(
            torch=torch_module,
            processor=processor,
            model=model,
            provenance=provenance,
            context_length=context_length,
            image_splitting_supported=_supports_image_splitting(processor),
        )

    def _dependencies(self) -> tuple[Any, Any, Any, Any, Any, str]:
        if all(
            dependency is not None
            for dependency in (
                self._torch,
                self._auto_processor,
                self._auto_model,
                self._expected_processor,
                self._expected_model,
                self._transformers_version,
            )
        ):
            return (
                self._torch,
                self._auto_processor,
                self._auto_model,
                self._expected_processor,
                self._expected_model,
                self._transformers_version,
            )
        try:
            import torch
            import transformers
            from transformers import AutoModelForMultimodalLM, AutoProcessor
            from transformers.models.smolvlm.modeling_smolvlm import (
                SmolVLMForConditionalGeneration,
            )
            from transformers.models.smolvlm.processing_smolvlm import (
                SmolVLMProcessor,
            )
        except ImportError as exc:
            raise SmolVLMModelLoadError(
                "Native SmolVLM dependencies are unavailable; install "
                "requirements-ai.txt (including num2words)."
            ) from exc
        return (
            self._torch or torch,
            self._auto_processor or AutoProcessor,
            self._auto_model or AutoModelForMultimodalLM,
            self._expected_processor or SmolVLMProcessor,
            self._expected_model or SmolVLMForConditionalGeneration,
            self._transformers_version or str(transformers.__version__),
        )


class SmolVLMVerifier:
    """Lazy isolated verifier; construction never resolves or loads model files."""

    def __init__(
        self,
        *,
        resolver: SmolVLMArtifactResolver | None = None,
        runtime_factory: SmolVLMRuntimeFactory | None = None,
        local_files_only: bool = False,
        device: Literal["cpu", "cuda"] = "cpu",
        model_spec: SmolVLMModelSpec | None = None,
        dtype: Literal["native", "bfloat16"] = "native",
        attention_implementation: str | None = None,
    ) -> None:
        self.resolver = resolver or SmolVLMArtifactResolver(model_spec=model_spec)
        self.runtime_factory = runtime_factory or SmolVLMRuntimeFactory()
        self.local_files_only = local_files_only
        self.device = device
        self.dtype = dtype
        self.attention_implementation = attention_implementation
        self.artifact_resolution_seconds = 0.0
        self.model_load_seconds = 0.0
        self._artifact: ResolvedSmolVLMArtifact | None = None
        self._runtime: SmolVLMRuntime | None = None

    def runtime(self) -> SmolVLMRuntime:
        if self._runtime is None:
            resolution_started = time.perf_counter()
            self._artifact = self.resolver.resolve(
                local_files_only=self.local_files_only
            )
            self.artifact_resolution_seconds += time.perf_counter() - resolution_started
            load_started = time.perf_counter()
            self._runtime = self.runtime_factory.create(
                self._artifact,
                device=self.device,
                dtype=self.dtype,
                attention_implementation=self.attention_implementation,
            )
            self.model_load_seconds += time.perf_counter() - load_started
        return self._runtime

    def verify(
        self,
        request: VLMVerificationRequest,
        *,
        max_new_tokens: int,
        image_splitting: bool = True,
        cancellation: CancellationToken | None = None,
    ) -> VLMVerificationResult:
        return self.runtime().verify(
            request,
            max_new_tokens=max_new_tokens,
            image_splitting=image_splitting,
            cancellation=cancellation,
        )


def parse_verification_json(
    raw_text: str,
    metadata: VLMVerificationRequestMetadata,
) -> GeneratedVerificationPayload:
    """Strictly parse one JSON object, then enforce the application policy."""
    stripped = raw_text.strip()
    decoded = json.loads(stripped)
    if not isinstance(decoded, dict):
        raise TypeError("generated output must be exactly one JSON object")
    payload = GeneratedVerificationPayload.model_validate_json(stripped, strict=True)
    policy = metadata.policy
    if any(
        category not in policy.allowed_categories for category in payload.categories
    ):
        raise ValueError("generated output contains a category outside the policy")
    if payload.unsafe:
        if not payload.categories or payload.severity not in policy.allowed_severities:
            raise ValueError(
                "unsafe output requires categories and a policy-approved severity"
            )
        if not payload.evidence_frame_indices:
            raise ValueError("unsafe output requires at least one evidence frame")
    elif (
        payload.categories
        or payload.severity is not None
        or (payload.evidence_frame_indices)
    ):
        raise ValueError(
            "safe output requires empty categories/evidence and null severity"
        )
    valid_indices = {frame.frame_index for frame in metadata.frames}
    if any(index not in valid_indices for index in payload.evidence_frame_indices):
        raise ValueError("generated output references an unavailable evidence frame")
    return payload


def synthetic_verification_request(image_count: int) -> VLMVerificationRequest:
    if not 1 <= image_count <= 6:
        raise SmolVLMRequestError("synthetic image count must be between 1 and 6")
    images: list[Image.Image] = []
    frames: list[VLMFrameDescriptor] = []
    for index in range(1, image_count + 1):
        image = Image.new(
            "RGB",
            (384, 384),
            ((index * 37) % 256, (index * 73) % 256, (index * 109) % 256),
        )
        images.append(image)
        frames.append(
            VLMFrameDescriptor(
                frame_index=index,
                timestamp_us=(index - 1) * 1_000_000,
                selection_reasons=("deterministic_synthetic_benchmark",),
            )
        )
    return VLMVerificationRequest(
        metadata=VLMVerificationRequestMetadata(
            event_id=f"synthetic-{image_count}-images",
            frames=tuple(frames),
            policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
        ),
        images=tuple(images),
    )


def _build_conversation(
    metadata: VLMVerificationRequestMetadata,
) -> list[dict[str, Any]]:
    categories = ", ".join(metadata.policy.allowed_categories)
    severities = ", ".join(metadata.policy.allowed_severities)
    content: list[dict[str, str]] = [
        {
            "type": "text",
            "text": (
                "Task: classify visible evidence in the ordered images below as one "
                "temporal event. The surrounding text is instruction, not visual "
                "evidence. "
                f"Allowed categories: [{categories}]. Allowed unsafe severities: "
                f"[{severities}].\n"
            ),
        }
    ]
    for frame in metadata.frames:
        content.append({"type": "text", "text": f"Frame {frame.frame_index}:\n"})
        content.append({"type": "image"})
    content.append(
        {
            "type": "text",
            "text": (
                "\nReturn ONLY one compact JSON object with exactly these keys and "
                "types: {\"unsafe\":false,\"categories\":[],\"severity\":null,"
                "\"reason\":\"brief visible evidence\","
                "\"evidence_frame_indices\":[]}. For unsafe evidence, use true, "
                "allowed categories/severity, and 1-based supplied Frame numbers. For "
                "safe evidence, keep categories/evidence empty and severity null. No "
                "markdown, extra keys, timestamps, or confidence."
            ),
        }
    )
    return [{"role": "user", "content": content}]


def _inspect_loaded_model(
    torch_module: Any,
    processor: Any,
    model: Any,
    artifact: ResolvedSmolVLMArtifact,
    *,
    device: str,
    transformers_version: str,
) -> tuple[SmolVLMRuntimeProvenance, int]:
    spec = artifact.model_spec
    try:
        parameters = list(model.parameters())
        parameter_count = sum(int(parameter.numel()) for parameter in parameters)
        actual_device = str(parameters[0].device.type)
        dtypes = {
            str(parameter.dtype).removeprefix("torch.") for parameter in parameters
        }
        context_length = int(model.config.text_config.max_position_embeddings)
        attention = getattr(model.config, "_attn_implementation", None)
        image_seq_len = int(processor.image_seq_len)
        image_token_id = int(processor.image_token_id)
    except Exception as exc:
        raise SmolVLMModelContractError(
            f"Loaded SmolVLM metadata is not inspectable ({type(exc).__name__})."
        ) from exc
    if parameter_count != spec.expected_parameter_count:
        raise SmolVLMModelContractError(
            f"Loaded parameter count is {parameter_count}, expected "
            f"{spec.expected_parameter_count}."
        )
    if actual_device != device:
        raise SmolVLMModelContractError(
            f"Loaded model device is {actual_device}, expected {device}."
        )
    if len(dtypes) != 1:
        raise SmolVLMModelContractError(
            f"Loaded model parameters use mixed dtypes: {sorted(dtypes)}."
        )
    if context_length != spec.expected_context_length:
        raise SmolVLMModelContractError(
            f"Loaded context length is {context_length}, expected "
            f"{spec.expected_context_length}."
        )
    if image_seq_len <= 0 or image_token_id < 0:
        raise SmolVLMModelContractError(
            "Loaded processor did not expose valid image-token metadata."
        )
    return (
        SmolVLMRuntimeProvenance(
            repository_id=spec.repository_id,
            revision=spec.revision,
            checkpoint_sha256=artifact.sha256,
            model_class=type(model).__name__,
            processor_class=type(processor).__name__,
            parameter_count=parameter_count,
            model_dtype=next(iter(dtypes)),
            device=device,
            transformers_version=transformers_version,
            torch_version=str(torch_module.__version__),
            attention_implementation=(
                str(attention) if attention is not None else None
            ),
        ),
        context_length,
    )


def _supports_image_splitting(processor: Any) -> bool:
    valid_kwargs = getattr(
        getattr(processor, "image_processor", None), "valid_kwargs", None
    )
    annotations = getattr(valid_kwargs, "__annotations__", {})
    return "do_image_splitting" in annotations


def _inspect_processor_expansion(
    runtime: SmolVLMRuntime,
    request: VLMVerificationRequest,
    encoded: Any,
    pre_expansion: Any,
    *,
    image_splitting: bool,
    max_new_tokens: int,
) -> ProcessorExpansionMetrics:
    try:
        pixel_values = encoded["pixel_values"]
        input_ids = encoded["input_ids"]
        pixel_mask = encoded.get("pixel_attention_mask")
        if pixel_values.ndim != 5 or int(pixel_values.shape[0]) != 1:
            raise ValueError("pixel_values must have shape [1, blocks, 3, H, W]")
        if input_ids.ndim != 2 or int(input_ids.shape[0]) != 1:
            raise ValueError("input_ids must have shape [1, sequence]")
        visual_blocks = int(pixel_values.shape[1])
        visual_tokens = int(
            (input_ids == runtime.processor.image_token_id).sum().item()
        )
        expected_visual_tokens = visual_blocks * int(runtime.processor.image_seq_len)
        if visual_tokens != expected_visual_tokens:
            raise ValueError(
                f"actual visual tokens {visual_tokens} do not equal blocks × image_seq_len "
                f"({expected_visual_tokens})"
            )
        sequence_length = int(input_ids.shape[1])
        pre_expansion_count = int(pre_expansion["input_ids"].shape[1])
    except Exception as exc:
        raise SmolVLMModelContractError(
            f"SmolVLM processor expansion is incompatible ({type(exc).__name__}: {exc})."
        ) from exc
    return ProcessorExpansionMetrics(
        image_splitting=image_splitting,
        input_image_count=len(request.images),
        original_image_dimensions=tuple(
            ImageDimensions(width=image.width, height=image.height)
            for image in request.images
        ),
        pixel_values_shape=tuple(int(value) for value in pixel_values.shape),
        visual_block_count=visual_blocks,
        pixel_attention_mask_shape=(
            tuple(int(value) for value in pixel_mask.shape)
            if pixel_mask is not None
            else None
        ),
        input_ids_shape=tuple(int(value) for value in input_ids.shape),
        pre_expansion_prompt_token_count=pre_expansion_count,
        visual_token_count=visual_tokens,
        non_visual_input_token_count=sequence_length - visual_tokens,
        input_sequence_length=sequence_length,
        declared_context_length=runtime.context_length,
        remaining_context_before_generation=runtime.context_length - sequence_length,
        remaining_context_after_requested_generation=(
            runtime.context_length - sequence_length - max_new_tokens
        ),
    )


def _move_model_inputs(batch: Any, *, device: str, dtype: Any) -> dict[str, Any]:
    moved = batch.to(device) if callable(getattr(batch, "to", None)) else batch
    result = dict(moved)
    pixel_values = result.get("pixel_values")
    if pixel_values is not None and dtype is not None:
        result["pixel_values"] = pixel_values.to(dtype=dtype)
    return result


def _cancellation_stopping_criteria(cancellation: CancellationToken | None) -> Any:
    if cancellation is None:
        return None
    try:
        from transformers import StoppingCriteria, StoppingCriteriaList
    except ImportError as exc:  # pragma: no cover - runtime dependency gate
        raise SmolVLMModelLoadError(
            "Transformers stopping criteria are unavailable."
        ) from exc

    class _CancellationCriteria(StoppingCriteria):
        def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> Any:
            del scores, kwargs
            return input_ids.new_full(
                (int(input_ids.shape[0]),), cancellation.is_cancelled
            ).bool()

    return StoppingCriteriaList([_CancellationCriteria()])


def _is_truncated(
    model: Any,
    new_tokens: Any,
    *,
    generated_count: int,
    max_new_tokens: int,
) -> bool:
    if generated_count < max_new_tokens or generated_count == 0:
        return False
    eos = getattr(getattr(model, "generation_config", None), "eos_token_id", None)
    eos_ids = (
        {int(eos)} if isinstance(eos, int) else {int(value) for value in (eos or [])}
    )
    last_token = int(new_tokens[0, -1].item())
    return last_token not in eos_ids


def _synchronize_if_cuda(torch_module: Any, device: str) -> None:
    if device == "cuda":
        torch_module.cuda.synchronize()


def _verify_file_manifest(
    paths: dict[str, Path],
    *,
    manifest: Mapping[str, tuple[int, str]] | None = None,
) -> None:
    expected_manifest = manifest or MODEL_FILE_MANIFEST
    for filename, (expected_size, expected_sha256) in expected_manifest.items():
        path = paths.get(filename)
        if path is None or not path.is_file():
            raise SmolVLMArtifactUnavailableError(
                f"Pinned SmolVLM file '{filename}' is unavailable."
            )
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise SmolVLMArtifactUnavailableError(
                f"Pinned SmolVLM file '{filename}' cannot be inspected."
            ) from exc
        if size != expected_size:
            raise SmolVLMArtifactIntegrityError(
                f"Pinned SmolVLM file '{filename}' size mismatch: "
                f"expected {expected_size}, got {size}."
            )
        digest = _sha256_file(path)
        if digest != expected_sha256:
            raise SmolVLMArtifactIntegrityError(
                f"Pinned SmolVLM file '{filename}' SHA-256 mismatch; refusing to load."
            )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as artifact:
            while chunk := artifact.read(4 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SmolVLMArtifactUnavailableError(
            f"Pinned SmolVLM file '{path.name}' cannot be read."
        ) from exc
    return digest.hexdigest()
