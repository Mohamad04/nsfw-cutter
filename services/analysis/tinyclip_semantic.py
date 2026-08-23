from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.paths import get_model_cache_dir
from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import FrameSample

MODEL_REPOSITORY_ID = "wkcn/TinyCLIP-ViT-8M-16-Text-3M-YFCC15M"
MODEL_REVISION = "a2a8c6eaa2549ad66eb7c31b85022bf58273a26c"
MODEL_WEIGHTS_FILENAME = "model.safetensors"
MODEL_WEIGHTS_SIZE = 93_812_468
MODEL_WEIGHTS_SHA256 = (
    "9339ee3d736344d0ddcaa6c03edc9f89688f08caaea5401220885233da726fcc"
)
MODEL_REQUIRED_FILES = (
    MODEL_WEIGHTS_FILENAME,
    "config.json",
    "preprocessor_config.json",
    "tokenizer.json",
)
TEXT_MAX_LENGTH = 77
IMAGE_SIZE = 224
CPU_DEVICE = "cpu"


class TinyCLIPSemanticError(RuntimeError):
    """Base error for the experimental TinyCLIP semantic specialist."""


class TinyCLIPArtifactUnavailableError(TinyCLIPSemanticError):
    """The pinned TinyCLIP snapshot could not be resolved."""


class TinyCLIPArtifactIntegrityError(TinyCLIPSemanticError):
    """The TinyCLIP safetensors artifact failed size or digest validation."""


class TinyCLIPModelLoadError(TinyCLIPSemanticError):
    """Native Transformers could not load the pinned TinyCLIP snapshot."""


class TinyCLIPModelContractError(TinyCLIPSemanticError):
    """Runtime inspection contradicted the verified TinyCLIP contract."""


class TinyCLIPImagePreprocessingError(TinyCLIPSemanticError):
    """An accepted representative could not be processed by CLIPProcessor."""


class TinyCLIPInferenceError(TinyCLIPSemanticError):
    """TinyCLIP inference failed or produced invalid similarity scores."""


@dataclass(frozen=True)
class ResolvedTinyCLIPArtifact:
    snapshot_dir: Path
    weights_path: Path
    sha256: str
    resolved_files: tuple[Path, ...]


@dataclass(frozen=True)
class TinyCLIPFrameInput:
    """Ephemeral representative input; its RGB bytes are never persisted."""

    sample_id: str
    source_timestamp_us: int
    rgb_bytes: bytes
    width: int
    height: int
    content_rect: tuple[int, int, int, int]


class SemanticPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @field_validator("concept_id", "text")
    @classmethod
    def normalize_nonblank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt fields cannot be blank")
        return normalized


class ExperimentalPromptBank(BaseModel):
    """Explicit evaluation prompt bank; never a production policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bank_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompts: tuple[SemanticPrompt, ...] = Field(min_length=1)
    experimental: Literal[True] = True
    production_approved: Literal[False] = False

    @field_validator("bank_id", "version")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt-bank identity cannot be blank")
        return normalized

    @model_validator(mode="after")
    def unique_concepts(self) -> ExperimentalPromptBank:
        concept_ids = [prompt.concept_id for prompt in self.prompts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("prompt-bank concept IDs must be unique")
        return self

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


EXPERIMENTAL_WEAPONS_DRUGS_PROMPT_BANK = ExperimentalPromptBank(
    bank_id="weapons-drugs-controls",
    version="experimental-v1",
    prompts=(
        SemanticPrompt(
            concept_id="weapons.person_holding_gun",
            text="a person holding a gun",
        ),
        SemanticPrompt(concept_id="weapons.firearm", text="a firearm"),
        SemanticPrompt(
            concept_id="weapons.aimed",
            text="a weapon being aimed at someone",
        ),
        SemanticPrompt(
            concept_id="weapons.collection",
            text="a large collection of guns",
        ),
        SemanticPrompt(
            concept_id="drugs.smoking_marijuana",
            text="a person smoking marijuana",
        ),
        SemanticPrompt(
            concept_id="drugs.person_using",
            text="a person using drugs",
        ),
        SemanticPrompt(
            concept_id="drugs.illegal_consumption",
            text="illegal drug consumption",
        ),
        SemanticPrompt(
            concept_id="drugs.paraphernalia",
            text="drug paraphernalia",
        ),
        SemanticPrompt(
            concept_id="control.phone",
            text="a person holding a phone",
        ),
        SemanticPrompt(
            concept_id="control.camera",
            text="a person holding a camera",
        ),
        SemanticPrompt(
            concept_id="control.tool",
            text="a person holding a tool",
        ),
        SemanticPrompt(
            concept_id="control.cigarette",
            text="a person smoking a cigarette",
        ),
        SemanticPrompt(
            concept_id="control.household_object",
            text="an ordinary household object",
        ),
    ),
)


class SemanticConceptScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)
    prompt_text: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    cosine_similarity: float
    scaled_logit: float

    @field_validator("cosine_similarity", "scaled_logit")
    @classmethod
    def finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("semantic similarity scores must be finite")
        return value


class TinyCLIPSemanticResult(BaseModel):
    """Pixel-free raw semantic measurements for one representative frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str = Field(min_length=1)
    source_timestamp_us: int = Field(ge=0)
    concept_scores: tuple[SemanticConceptScore, ...] = Field(min_length=1)
    prompt_bank_id: str = Field(min_length=1)
    prompt_bank_version: str = Field(min_length=1)
    prompt_bank_digest: str = Field(min_length=64, max_length=64)
    model_repository_id: str
    model_revision: str
    checkpoint_sha256: str = Field(min_length=64, max_length=64)
    transformers_version: str
    torch_version: str
    device: Literal["cpu"]
    dtype: str
    processor_class: str
    tokenizer_class: str
    logit_scale_exp: float = Field(gt=0.0)
    experimental_model: Literal[True] = True
    production_license_cleared: Literal[False] = False

    @field_validator("logit_scale_exp")
    @classmethod
    def finite_logit_scale(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("TinyCLIP logit scale must be finite")
        return value


class TinyCLIPModelResolver:
    """Resolve only the pinned evaluation snapshot into the app model cache."""

    def __init__(
        self,
        *,
        model_cache_dir: str | Path | None = None,
        hub_download: Callable[..., str] | None = None,
    ) -> None:
        self.model_cache_dir = (
            Path(model_cache_dir) if model_cache_dir is not None else get_model_cache_dir()
        )
        self._hub_download = hub_download

    def resolve(self, *, local_files_only: bool = False) -> ResolvedTinyCLIPArtifact:
        download = self._hub_download
        if download is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise TinyCLIPArtifactUnavailableError(
                    "huggingface_hub is unavailable; install requirements-ai.txt."
                ) from exc
            download = hf_hub_download

        resolved: list[Path] = []
        for filename in MODEL_REQUIRED_FILES:
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
                mode = "local cache" if local_files_only else "Hugging Face Hub"
                raise TinyCLIPArtifactUnavailableError(
                    f"Unable to resolve pinned TinyCLIP file '{filename}' from "
                    f"{mode} ({type(exc).__name__})."
                ) from exc
            if not path.is_file():
                raise TinyCLIPArtifactUnavailableError(
                    f"Pinned TinyCLIP file '{filename}' is not readable."
                )
            resolved.append(path)

        snapshot_dirs = {path.parent.resolve() for path in resolved}
        if len(snapshot_dirs) != 1:
            raise TinyCLIPArtifactUnavailableError(
                "Pinned TinyCLIP files did not resolve to one local snapshot."
            )
        weights_path = resolved[0]
        try:
            size = weights_path.stat().st_size
        except OSError as exc:
            raise TinyCLIPArtifactUnavailableError(
                "The TinyCLIP safetensors artifact cannot be inspected."
            ) from exc
        if size != MODEL_WEIGHTS_SIZE:
            raise TinyCLIPArtifactIntegrityError(
                "Pinned TinyCLIP safetensors size mismatch; refusing to load it."
            )
        digest = _sha256_file(weights_path)
        if digest != MODEL_WEIGHTS_SHA256:
            raise TinyCLIPArtifactIntegrityError(
                "Pinned TinyCLIP safetensors SHA-256 mismatch; refusing to load it."
            )
        return ResolvedTinyCLIPArtifact(
            snapshot_dir=next(iter(snapshot_dirs)),
            weights_path=weights_path,
            sha256=digest,
            resolved_files=tuple(resolved),
        )


@dataclass
class TinyCLIPRuntimeTiming:
    text_tokenization_seconds: float = 0.0
    text_embedding_seconds: float = 0.0
    image_preprocessing_seconds: float = 0.0
    image_encoder_seconds: float = 0.0
    similarity_seconds: float = 0.0
    text_embedding_calls: int = 0
    image_encoder_calls: int = 0
    similarity_calls: int = 0


@dataclass
class TinyCLIPRuntime:
    torch: Any
    processor: Any
    model: Any
    torch_version: str
    transformers_version: str
    device: Literal["cpu"]
    dtype: str
    projection_dim: int
    logit_scale_exp: float
    processor_class: str
    tokenizer_class: str
    processor_setup_seconds: float = 0.0
    weights_load_seconds: float = 0.0
    timing: TinyCLIPRuntimeTiming = field(default_factory=TinyCLIPRuntimeTiming)

    def prepare_text_features(self, prompt_bank: ExperimentalPromptBank) -> Any:
        prompts = [prompt.text for prompt in prompt_bank.prompts]
        tokenization_started = time.perf_counter()
        try:
            encoded = self.processor(
                text=prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=TEXT_MAX_LENGTH,
            )
            encoded = _move_batch_to_cpu(encoded)
            input_ids = encoded["input_ids"]
            attention_mask = encoded.get("attention_mask")
        except Exception as exc:
            raise TinyCLIPModelContractError(
                f"TinyCLIP prompt tokenization failed ({type(exc).__name__})."
            ) from exc
        self.timing.text_tokenization_seconds += (
            time.perf_counter() - tokenization_started
        )
        _validate_token_batch(input_ids, len(prompts))

        embedding_started = time.perf_counter()
        try:
            kwargs = {"input_ids": input_ids}
            if attention_mask is not None:
                kwargs["attention_mask"] = attention_mask
            with self.torch.inference_mode():
                feature_output = self.model.get_text_features(**kwargs)
        except Exception as exc:
            raise TinyCLIPInferenceError(
                f"TinyCLIP text encoding failed ({type(exc).__name__})."
            ) from exc
        features = _normalize_features(
            self.torch,
            _projected_feature_tensor(self.torch, feature_output, kind="text"),
            expected_rows=len(prompts),
            expected_columns=self.projection_dim,
            kind="text",
        )
        self.timing.text_embedding_seconds += time.perf_counter() - embedding_started
        self.timing.text_embedding_calls += 1
        return features.detach()

    def prepare_image_batch(self, frames: Sequence[TinyCLIPFrameInput]) -> Any:
        if not frames:
            raise TinyCLIPImagePreprocessingError(
                "TinyCLIP image inference requires at least one representative."
            )
        started_at = time.perf_counter()
        try:
            images = [_cropped_content_image(frame) for frame in frames]
            encoded = self.processor(images=images, return_tensors="pt")
            encoded = _move_batch_to_cpu(encoded)
            pixel_values = encoded["pixel_values"]
        except TinyCLIPImagePreprocessingError:
            raise
        except Exception as exc:
            raise TinyCLIPImagePreprocessingError(
                f"Official TinyCLIP image processing failed ({type(exc).__name__})."
            ) from exc
        _validate_pixel_values(self.torch, pixel_values, len(frames))
        self.timing.image_preprocessing_seconds += time.perf_counter() - started_at
        return pixel_values

    def encode_image_features(self, pixel_values: Any, *, expected_rows: int) -> Any:
        started_at = time.perf_counter()
        try:
            with self.torch.inference_mode():
                feature_output = self.model.get_image_features(
                    pixel_values=pixel_values
                )
        except Exception as exc:
            raise TinyCLIPInferenceError(
                f"TinyCLIP image encoding failed ({type(exc).__name__})."
            ) from exc
        features = _normalize_features(
            self.torch,
            _projected_feature_tensor(self.torch, feature_output, kind="image"),
            expected_rows=expected_rows,
            expected_columns=self.projection_dim,
            kind="image",
        )
        self.timing.image_encoder_seconds += time.perf_counter() - started_at
        self.timing.image_encoder_calls += 1
        return features

    def cosine_similarities(self, image_features: Any, text_features: Any) -> Any:
        started_at = time.perf_counter()
        try:
            with self.torch.inference_mode():
                similarities = image_features @ text_features.T
        except Exception as exc:
            raise TinyCLIPInferenceError(
                f"TinyCLIP similarity calculation failed ({type(exc).__name__})."
            ) from exc
        if similarities.ndim != 2 or not bool(
            self.torch.isfinite(similarities).all().item()
        ):
            raise TinyCLIPInferenceError(
                "TinyCLIP cosine similarity matrix is malformed or non-finite."
            )
        self.timing.similarity_seconds += time.perf_counter() - started_at
        self.timing.similarity_calls += 1
        return similarities


class TinyCLIPRuntimeFactory:
    """Load and validate the pinned native Transformers CLIP runtime on CPU."""

    def __init__(
        self,
        *,
        torch_module: Any | None = None,
        processor_class: Any | None = None,
        model_class: Any | None = None,
        transformers_version: str | None = None,
    ) -> None:
        self._torch_module = torch_module
        self._processor_class = processor_class
        self._model_class = model_class
        self._transformers_version = transformers_version

    def create(self, artifact: ResolvedTinyCLIPArtifact) -> TinyCLIPRuntime:
        torch_module = self._torch_module
        processor_class = self._processor_class
        model_class = self._model_class
        transformers_version = self._transformers_version
        if torch_module is None or processor_class is None or model_class is None:
            try:
                import torch
                import transformers
                from transformers import CLIPModel, CLIPProcessor
            except ImportError as exc:
                raise TinyCLIPModelLoadError(
                    "Native TinyCLIP dependencies are unavailable; install requirements-ai.txt."
                ) from exc
            torch_module = torch_module or torch
            processor_class = processor_class or CLIPProcessor
            model_class = model_class or CLIPModel
            transformers_version = transformers_version or str(transformers.__version__)

        try:
            processor_started = time.perf_counter()
            processor = processor_class.from_pretrained(
                str(artifact.snapshot_dir),
                local_files_only=True,
            )
            processor_setup_seconds = time.perf_counter() - processor_started
            model_started = time.perf_counter()
            model = model_class.from_pretrained(
                str(artifact.snapshot_dir),
                local_files_only=True,
                use_safetensors=True,
            )
            model = model.to(CPU_DEVICE)
            model.eval()
            weights_load_seconds = time.perf_counter() - model_started
        except Exception as exc:
            raise TinyCLIPModelLoadError(
                "Pinned TinyCLIP snapshot could not load through native CLIPProcessor/"
                f"CLIPModel ({type(exc).__name__}); no fallback was attempted."
            ) from exc

        runtime = _validate_loaded_runtime(
            torch_module,
            processor,
            model,
            model_class=model_class,
            transformers_version=transformers_version or "unknown",
        )
        runtime.processor_setup_seconds = processor_setup_seconds
        runtime.weights_load_seconds = weights_load_seconds
        return runtime


class TinyCLIPTextFeatureCache:
    """Analysis-local cache keyed by model identity and exact prompt-bank digest."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], Any] = {}

    def get_or_prepare(
        self,
        runtime: TinyCLIPRuntime,
        prompt_bank: ExperimentalPromptBank,
        *,
        model_revision: str,
        checkpoint_sha256: str,
    ) -> Any:
        key = (model_revision, checkpoint_sha256, prompt_bank.digest)
        features = self._entries.get(key)
        if features is None:
            features = runtime.prepare_text_features(prompt_bank)
            self._entries[key] = features
        return features

    @property
    def entry_count(self) -> int:
        return len(self._entries)


class TinyCLIPSemanticClassifier:
    """Lazy CPU-only batch classifier returning raw semantic similarities."""

    def __init__(
        self,
        *,
        artifact_resolver: TinyCLIPModelResolver | None = None,
        runtime_factory: TinyCLIPRuntimeFactory | None = None,
        text_feature_cache: TinyCLIPTextFeatureCache | None = None,
        local_files_only: bool = False,
    ) -> None:
        self._artifact_resolver = artifact_resolver or TinyCLIPModelResolver()
        self._runtime_factory = runtime_factory or TinyCLIPRuntimeFactory()
        self._text_feature_cache = text_feature_cache or TinyCLIPTextFeatureCache()
        self._local_files_only = local_files_only
        self._artifact: ResolvedTinyCLIPArtifact | None = None
        self._runtime: TinyCLIPRuntime | None = None
        self.artifact_resolution_seconds = 0.0
        self.model_load_seconds = 0.0

    @property
    def runtime(self) -> TinyCLIPRuntime | None:
        return self._runtime

    @property
    def artifact(self) -> ResolvedTinyCLIPArtifact | None:
        return self._artifact

    def classify(
        self,
        frames: Sequence[TinyCLIPFrameInput],
        prompt_bank: ExperimentalPromptBank,
    ) -> list[TinyCLIPSemanticResult]:
        ordered_frames = list(frames)
        if not ordered_frames:
            return []
        runtime, artifact = self._get_runtime()
        text_features = self._text_feature_cache.get_or_prepare(
            runtime,
            prompt_bank,
            model_revision=MODEL_REVISION,
            checkpoint_sha256=artifact.sha256,
        )
        pixel_values = runtime.prepare_image_batch(ordered_frames)
        image_features = runtime.encode_image_features(
            pixel_values,
            expected_rows=len(ordered_frames),
        )
        similarities = runtime.cosine_similarities(image_features, text_features)
        expected_shape = (len(ordered_frames), len(prompt_bank.prompts))
        if tuple(similarities.shape) != expected_shape:
            raise TinyCLIPInferenceError(
                f"TinyCLIP cosine matrix shape mismatch: expected {expected_shape}, "
                f"got {tuple(similarities.shape)}."
            )
        rows = similarities.detach().to(CPU_DEVICE).tolist()
        return [
            TinyCLIPSemanticResult(
                sample_id=frame.sample_id,
                source_timestamp_us=frame.source_timestamp_us,
                concept_scores=tuple(
                    SemanticConceptScore(
                        concept_id=prompt.concept_id,
                        prompt_text=prompt.text,
                        prompt_sha256=_text_sha256(prompt.text),
                        cosine_similarity=float(score),
                        scaled_logit=float(score) * runtime.logit_scale_exp,
                    )
                    for prompt, score in zip(prompt_bank.prompts, row, strict=True)
                ),
                prompt_bank_id=prompt_bank.bank_id,
                prompt_bank_version=prompt_bank.version,
                prompt_bank_digest=prompt_bank.digest,
                model_repository_id=MODEL_REPOSITORY_ID,
                model_revision=MODEL_REVISION,
                checkpoint_sha256=artifact.sha256,
                transformers_version=runtime.transformers_version,
                torch_version=runtime.torch_version,
                device=runtime.device,
                dtype=runtime.dtype,
                processor_class=runtime.processor_class,
                tokenizer_class=runtime.tokenizer_class,
                logit_scale_exp=runtime.logit_scale_exp,
            )
            for frame, row in zip(ordered_frames, rows, strict=True)
        ]

    def ensure_runtime(self) -> TinyCLIPRuntime:
        """Resolve and validate the lazy runtime without running a user batch."""
        runtime, _artifact = self._get_runtime()
        return runtime

    def prepare_prompt_bank(self, prompt_bank: ExperimentalPromptBank) -> None:
        """Populate the analysis-local text cache without encoding an image."""
        runtime, artifact = self._get_runtime()
        self._text_feature_cache.get_or_prepare(
            runtime,
            prompt_bank,
            model_revision=MODEL_REVISION,
            checkpoint_sha256=artifact.sha256,
        )

    def _get_runtime(self) -> tuple[TinyCLIPRuntime, ResolvedTinyCLIPArtifact]:
        if self._runtime is None:
            resolve_started = time.perf_counter()
            self._artifact = self._artifact_resolver.resolve(
                local_files_only=self._local_files_only
            )
            self.artifact_resolution_seconds += time.perf_counter() - resolve_started
            load_started = time.perf_counter()
            self._runtime = self._runtime_factory.create(self._artifact)
            self.model_load_seconds += time.perf_counter() - load_started
        if self._artifact is None:  # pragma: no cover - established above
            raise TinyCLIPModelLoadError("TinyCLIP runtime has no resolved artifact.")
        return self._runtime, self._artifact


class TinyCLIPBatchConsumer:
    """Bounded evaluation-only batching callback for semantic inference."""

    def __init__(
        self,
        classifier: TinyCLIPSemanticClassifier,
        prompt_bank: ExperimentalPromptBank,
        *,
        batch_size: int,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("TinyCLIP batch size must be positive.")
        self.classifier = classifier
        self.prompt_bank = prompt_bank
        self.batch_size = batch_size
        self.results: list[TinyCLIPSemanticResult] = []
        self.inference_calls = 0
        self.classification_seconds = 0.0
        self.observed_batch_sizes: list[int] = []
        self._pending: list[TinyCLIPFrameInput] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def __call__(
        self,
        frame: ExtractedFrame,
        sample: FrameSample,
        cancellation: CancellationToken,
    ) -> None:
        cancellation.raise_if_cancelled()
        self._pending.append(_frame_input(frame, sample))
        if len(self._pending) >= self.batch_size:
            self._classify_pending(cancellation)
        cancellation.raise_if_cancelled()

    def flush(self, cancellation: CancellationToken) -> None:
        cancellation.raise_if_cancelled()
        if self._pending:
            self._classify_pending(cancellation)
        cancellation.raise_if_cancelled()

    def _classify_pending(self, cancellation: CancellationToken) -> None:
        pending = self._pending
        self._pending = []
        cancellation.raise_if_cancelled()
        started_at = time.perf_counter()
        results = self.classifier.classify(pending, self.prompt_bank)
        elapsed = time.perf_counter() - started_at
        if len(results) != len(pending):
            raise TinyCLIPInferenceError(
                "TinyCLIP result count does not match its buffered batch."
            )
        self.results.extend(results)
        self.inference_calls += 1
        self.classification_seconds += elapsed
        self.observed_batch_sizes.append(len(pending))
        cancellation.raise_if_cancelled()


def _validate_loaded_runtime(
    torch_module: Any,
    processor: Any,
    model: Any,
    *,
    model_class: Any,
    transformers_version: str,
) -> TinyCLIPRuntime:
    if not isinstance(model, model_class):
        raise TinyCLIPModelContractError(
            "Loaded TinyCLIP model is not compatible with native CLIPModel."
        )
    try:
        parameter = next(model.parameters())
        device = str(parameter.device.type)
        dtype = str(parameter.dtype).removeprefix("torch.")
        text_limit = int(model.config.text_config.max_position_embeddings)
        configured_projection = int(model.config.projection_dim)
        text_projection = int(model.text_projection.out_features)
        image_projection = int(model.visual_projection.out_features)
    except Exception as exc:
        raise TinyCLIPModelContractError(
            f"Unable to inspect loaded TinyCLIP model metadata ({type(exc).__name__})."
        ) from exc
    if device != CPU_DEVICE:
        raise TinyCLIPModelContractError("TinyCLIP baseline must load on CPU.")
    if text_limit < TEXT_MAX_LENGTH:
        raise TinyCLIPModelContractError(
            "TinyCLIP text encoder does not support the verified 77-token length."
        )
    if configured_projection <= 0 or not (
        configured_projection == text_projection == image_projection
    ):
        raise TinyCLIPModelContractError(
            "TinyCLIP image/text projection dimensions do not agree."
        )
    try:
        scale_tensor = model.logit_scale.exp()
        logit_scale_exp = float(scale_tensor.detach().to(CPU_DEVICE).item())
    except Exception as exc:
        raise TinyCLIPModelContractError(
            f"TinyCLIP loaded logit_scale is unavailable ({type(exc).__name__})."
        ) from exc
    if not math.isfinite(logit_scale_exp) or logit_scale_exp <= 0.0:
        raise TinyCLIPModelContractError(
            "TinyCLIP loaded exp(logit_scale) must be finite and positive."
        )

    try:
        text_batch = processor(
            text=["a photo", "an object"],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=TEXT_MAX_LENGTH,
        )
        image_batch = processor(
            images=[
                Image.new("RGB", (32, 24), (0, 0, 0)),
                Image.new("RGB", (24, 32), (255, 255, 255)),
            ],
            return_tensors="pt",
        )
        text_batch = _move_batch_to_cpu(text_batch)
        image_batch = _move_batch_to_cpu(image_batch)
        _validate_token_batch(text_batch["input_ids"], 2)
        _validate_pixel_values(torch_module, image_batch["pixel_values"], 2)
        kwargs = {
            "input_ids": text_batch["input_ids"],
            "pixel_values": image_batch["pixel_values"],
        }
        if text_batch.get("attention_mask") is not None:
            kwargs["attention_mask"] = text_batch["attention_mask"]
        with torch_module.inference_mode():
            outputs = model(**kwargs)
    except TinyCLIPModelContractError:
        raise
    except Exception as exc:
        raise TinyCLIPModelContractError(
            f"TinyCLIP startup smoke inference failed ({type(exc).__name__})."
        ) from exc

    required_outputs = (
        "image_embeds",
        "text_embeds",
        "logits_per_image",
        "logits_per_text",
    )
    if any(getattr(outputs, name, None) is None for name in required_outputs):
        raise TinyCLIPModelContractError(
            "Native TinyCLIP output is missing CLIP embeddings or logits."
        )
    if tuple(outputs.image_embeds.shape) != (2, configured_projection):
        raise TinyCLIPModelContractError("TinyCLIP image embedding shape mismatch.")
    if tuple(outputs.text_embeds.shape) != (2, configured_projection):
        raise TinyCLIPModelContractError("TinyCLIP text embedding shape mismatch.")
    if tuple(outputs.logits_per_image.shape) != (2, 2):
        raise TinyCLIPModelContractError("TinyCLIP image/text logit shape mismatch.")
    for name in required_outputs:
        tensor = getattr(outputs, name)
        if not bool(torch_module.isfinite(tensor).all().item()):
            raise TinyCLIPModelContractError(
                f"TinyCLIP startup output '{name}' contains non-finite values."
            )

    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None:
        raise TinyCLIPModelContractError("CLIPProcessor did not expose its tokenizer.")
    return TinyCLIPRuntime(
        torch=torch_module,
        processor=processor,
        model=model,
        torch_version=str(torch_module.__version__),
        transformers_version=transformers_version,
        device="cpu",
        dtype=dtype,
        projection_dim=configured_projection,
        logit_scale_exp=logit_scale_exp,
        processor_class=type(processor).__name__,
        tokenizer_class=type(tokenizer).__name__,
    )


def _move_batch_to_cpu(batch: Any) -> Any:
    move = getattr(batch, "to", None)
    if callable(move):
        return move(CPU_DEVICE)
    return {
        key: value.to(CPU_DEVICE) if hasattr(value, "to") else value
        for key, value in batch.items()
    }


def _validate_token_batch(input_ids: Any, expected_rows: int) -> None:
    if input_ids.ndim != 2 or int(input_ids.shape[0]) != expected_rows:
        raise TinyCLIPModelContractError(
            "TinyCLIP tokenizer did not return one token row per prompt."
        )
    sequence_length = int(input_ids.shape[1])
    if sequence_length <= 0 or sequence_length > TEXT_MAX_LENGTH:
        raise TinyCLIPModelContractError(
            "TinyCLIP tokenized sequence length is incompatible with 77 tokens."
        )


def _validate_pixel_values(torch_module: Any, pixel_values: Any, batch_size: int) -> None:
    if tuple(pixel_values.shape) != (batch_size, 3, IMAGE_SIZE, IMAGE_SIZE):
        raise TinyCLIPModelContractError(
            "CLIPProcessor pixel_values must have shape [B, 3, 224, 224]."
        )
    if not bool(torch_module.is_floating_point(pixel_values)):
        raise TinyCLIPModelContractError("CLIPProcessor pixel_values must be floating point.")
    if not bool(torch_module.isfinite(pixel_values).all().item()):
        raise TinyCLIPModelContractError(
            "CLIPProcessor pixel_values contain non-finite values."
        )


def _normalize_features(
    torch_module: Any,
    features: Any,
    *,
    expected_rows: int,
    expected_columns: int,
    kind: str,
) -> Any:
    if tuple(features.shape) != (expected_rows, expected_columns):
        raise TinyCLIPInferenceError(
            f"TinyCLIP {kind} feature shape mismatch: expected "
            f"({expected_rows}, {expected_columns}), got {tuple(features.shape)}."
        )
    if not bool(torch_module.isfinite(features).all().item()):
        raise TinyCLIPInferenceError(
            f"TinyCLIP {kind} features contain non-finite values."
        )
    norms = torch_module.linalg.vector_norm(features, dim=-1, keepdim=True)
    if not bool(torch_module.isfinite(norms).all().item()) or bool(
        (norms <= 0).any().item()
    ):
        raise TinyCLIPInferenceError(
            f"TinyCLIP {kind} features cannot be L2 normalized."
        )
    return features / norms


def _projected_feature_tensor(torch_module: Any, output: Any, *, kind: str) -> Any:
    """Extract the projected tensor from the installed native CLIP API result."""
    if bool(torch_module.is_tensor(output)):
        return output
    pooled_output = getattr(output, "pooler_output", None)
    if pooled_output is not None and bool(torch_module.is_tensor(pooled_output)):
        return pooled_output
    raise TinyCLIPModelContractError(
        f"Native CLIP get_{kind}_features returned no projected feature tensor."
    )


def _cropped_content_image(frame: TinyCLIPFrameInput) -> Image.Image:
    _validate_frame_input(frame)
    try:
        canvas = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb_bytes)
        left, top, width, height = frame.content_rect
        return canvas.crop((left, top, left + width, top + height))
    except Exception as exc:
        raise TinyCLIPImagePreprocessingError(
            f"Unable to crop TinyCLIP frame '{frame.sample_id}' ({type(exc).__name__})."
        ) from exc


def _validate_frame_input(frame: TinyCLIPFrameInput) -> None:
    if not frame.sample_id:
        raise TinyCLIPImagePreprocessingError("TinyCLIP sample ID cannot be empty.")
    if frame.source_timestamp_us < 0:
        raise TinyCLIPImagePreprocessingError("TinyCLIP timestamp cannot be negative.")
    if frame.width <= 0 or frame.height <= 0:
        raise TinyCLIPImagePreprocessingError("TinyCLIP frame dimensions must be positive.")
    if len(frame.rgb_bytes) != frame.width * frame.height * 3:
        raise TinyCLIPImagePreprocessingError(
            "TinyCLIP RGB byte count does not match the frame dimensions."
        )
    left, top, width, height = frame.content_rect
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise TinyCLIPImagePreprocessingError("TinyCLIP content rectangle is invalid.")
    if left + width > frame.width or top + height > frame.height:
        raise TinyCLIPImagePreprocessingError(
            "TinyCLIP content rectangle exceeds the RGB frame."
        )


def _frame_input(frame: ExtractedFrame, sample: FrameSample) -> TinyCLIPFrameInput:
    source_pts = "none" if sample.source_pts is None else str(sample.source_pts)
    return TinyCLIPFrameInput(
        sample_id=(
            f"representative:{sample.owning_chunk_index}:"
            f"{sample.timestamp_us}:{source_pts}"
        ),
        source_timestamp_us=sample.timestamp_us,
        rgb_bytes=frame.rgb_bytes,
        width=frame.width,
        height=frame.height,
        content_rect=frame.content_rect,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as artifact:
            while chunk := artifact.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise TinyCLIPArtifactUnavailableError(
            "The TinyCLIP safetensors artifact cannot be read."
        ) from exc
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
