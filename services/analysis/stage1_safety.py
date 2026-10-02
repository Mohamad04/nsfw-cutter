from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.paths import get_model_cache_dir
from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import FrameSample

MODEL_REPOSITORY_ID = "OwenElliott/image-safety-classifier-s"
MODEL_REVISION = "015042b0eab17f1b17f2986527386346fb0d94be"
MODEL_FILENAME = "onnx/image-safety-classifier-s.onnx"
MODEL_SHA256 = "fef443ed68ae25ed693b6fef9e456071692ed3963cff4168acb39c3de6f017e7"
INPUT_NAME = "image"
OUTPUT_NAME = "probabilities"
IMAGE_SIZE = 224
LABELS: tuple[Literal["NSFL", "NSFW", "SFW"], ...] = ("NSFL", "NSFW", "SFW")
CPU_EXECUTION_PROVIDER = "CPUExecutionProvider"


class Stage1SafetyError(RuntimeError):
    """Base error for the independent Stage-1 ONNX safety classifier."""


class SafetyModelArtifactUnavailableError(Stage1SafetyError):
    """The pinned artifact could not be obtained from the configured cache/Hub."""


class SafetyModelArtifactIntegrityError(Stage1SafetyError):
    """The resolved artifact does not match the expected pinned SHA-256."""


class SafetyModelSessionError(Stage1SafetyError):
    """ONNX Runtime could not create a CPU session for the verified artifact."""


class SafetyModelContractError(Stage1SafetyError):
    """The real ONNX metadata contradicts the pinned Stage-1 contract."""


class SafetyImagePreprocessingError(Stage1SafetyError):
    """An in-memory representative frame cannot be converted into model input."""


class SafetyInferenceError(Stage1SafetyError):
    """ONNX inference failed or returned invalid probability data."""


@dataclass(frozen=True)
class ResolvedSafetyModelArtifact:
    path: Path
    sha256: str


@dataclass(frozen=True)
class Stage1FrameInput:
    """Ephemeral frame data accepted by the batch classifier; never persisted."""

    sample_id: str
    source_timestamp_us: int
    rgb_bytes: bytes
    width: int
    height: int
    content_rect: tuple[int, int, int, int]


class Stage1Result(BaseModel):
    """Path-free, pixel-free provenance and raw model probabilities for one frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_id: str = Field(min_length=1)
    source_timestamp_us: int = Field(ge=0)
    nsfl_probability: float = Field(ge=0.0, le=1.0)
    nsfw_probability: float = Field(ge=0.0, le=1.0)
    sfw_probability: float = Field(ge=0.0, le=1.0)
    selected_label: Literal["NSFL", "NSFW", "SFW"]
    model_repository_id: str
    model_revision: str
    artifact_sha256: str
    onnxruntime_version: str
    execution_providers: tuple[str, ...]

    @field_validator(
        "nsfl_probability",
        "nsfw_probability",
        "sfw_probability",
    )
    @classmethod
    def finite_probability(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("probabilities must be finite")
        return value


class SafetyModelArtifactResolver:
    """Resolve only the pinned ONNX artifact into the application's HF cache."""

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

    def resolve(self, *, local_files_only: bool = False) -> ResolvedSafetyModelArtifact:
        download = self._hub_download
        if download is None:
            try:
                from huggingface_hub import hf_hub_download
            except ImportError as exc:
                raise SafetyModelArtifactUnavailableError(
                    "huggingface_hub is unavailable; install the Stage-1 AI dependencies."
                ) from exc
            download = hf_hub_download

        try:
            resolved_path = download(
                repo_id=MODEL_REPOSITORY_ID,
                filename=MODEL_FILENAME,
                revision=MODEL_REVISION,
                cache_dir=self.model_cache_dir,
                local_files_only=local_files_only,
            )
        except Exception as exc:
            mode = "local cache" if local_files_only else "Hugging Face Hub"
            raise SafetyModelArtifactUnavailableError(
                f"Unable to resolve pinned Stage-1 model from {mode} ({type(exc).__name__})."
            ) from exc

        path = Path(resolved_path)
        if not path.is_file():
            raise SafetyModelArtifactUnavailableError(
                "The pinned Stage-1 model resolver did not return a readable artifact."
            )
        digest = _sha256_file(path)
        if digest != MODEL_SHA256:
            raise SafetyModelArtifactIntegrityError(
                "Pinned Stage-1 model SHA-256 mismatch; refusing to load the artifact."
            )
        return ResolvedSafetyModelArtifact(path=path, sha256=digest)


@dataclass
class SafetyONNXSession:
    session: Any
    onnxruntime_version: str
    execution_providers: tuple[str, ...]
    inference_calls: int = 0
    onnx_inference_seconds: float = 0.0

    def run(self, input_tensor: np.ndarray) -> np.ndarray:
        probabilities, _ = self.run_timed(input_tensor)
        return probabilities

    def run_timed(self, input_tensor: np.ndarray) -> tuple[np.ndarray, float]:
        """Run one validated ONNX batch and report only session.run wall time."""
        batch_size = int(input_tensor.shape[0]) if input_tensor.ndim == 4 else 0
        _validate_input_tensor(input_tensor, expected_batch_size=batch_size)
        started_at = time.perf_counter()
        try:
            outputs = self.session.run(
                [OUTPUT_NAME],
                {INPUT_NAME: input_tensor},
            )
        except Exception as exc:
            raise SafetyInferenceError(
                f"Stage-1 ONNX inference failed ({type(exc).__name__})."
            ) from exc
        inference_seconds = time.perf_counter() - started_at
        probabilities = _validate_probability_output(outputs, batch_size)
        self.inference_calls += 1
        self.onnx_inference_seconds += inference_seconds
        return probabilities, inference_seconds


# Kept as an internal compatibility alias for existing Stage-1 tests/imports.
_SafetySession = SafetyONNXSession


class ONNXSafetySessionFactory:
    """Create and validate a CPU-only ONNX Runtime session for Stage 1."""

    def __init__(self, ort_module: Any | None = None) -> None:
        self._ort_module = ort_module

    def create(self, artifact: ResolvedSafetyModelArtifact) -> SafetyONNXSession:
        ort_module = self._ort_module
        if ort_module is None:
            try:
                import onnxruntime as ort_module
            except ImportError as exc:
                raise SafetyModelSessionError(
                    "onnxruntime is unavailable; install the Stage-1 AI dependencies."
                ) from exc

        try:
            session = ort_module.InferenceSession(
                str(artifact.path),
                providers=[CPU_EXECUTION_PROVIDER],
            )
        except Exception as exc:
            raise SafetyModelSessionError(
                f"Unable to create CPU ONNX safety session ({type(exc).__name__})."
            ) from exc

        _validate_session_contract(session)
        return SafetyONNXSession(
            session=session,
            onnxruntime_version=str(ort_module.__version__),
            execution_providers=tuple(session.get_providers()),
        )


class SafetyImageAdapter:
    """Convert cropped, in-memory RGB representative frames to float32 NCHW tensors."""

    def prepare_batch(self, frames: Sequence[Stage1FrameInput]) -> np.ndarray:
        if not frames:
            raise SafetyImagePreprocessingError("Stage-1 inference requires at least one frame.")
        tensors = [self._prepare_frame(frame) for frame in frames]
        batch = np.stack(tensors, axis=0)
        _validate_input_tensor(batch, expected_batch_size=len(frames))
        return batch

    def _prepare_frame(self, frame: Stage1FrameInput) -> np.ndarray:
        _validate_frame_input(frame)
        try:
            canvas = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb_bytes)
            left, top, width, height = frame.content_rect
            content = canvas.crop((left, top, left + width, top + height))
            resized = content.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
            pixels = np.asarray(resized, dtype=np.float32)
        except Exception as exc:
            raise SafetyImagePreprocessingError(
                f"Unable to prepare Stage-1 frame '{frame.sample_id}' ({type(exc).__name__})."
            ) from exc

        if pixels.shape != (IMAGE_SIZE, IMAGE_SIZE, 3):
            raise SafetyImagePreprocessingError(
                "Stage-1 RGB resize did not produce a 224x224 three-channel image."
            )
        return np.transpose(pixels, (2, 0, 1))


class Stage1SafetyClassifier:
    """Lazy, batch-capable CPU classifier that returns raw three-class probabilities."""

    def __init__(
        self,
        *,
        artifact_resolver: SafetyModelArtifactResolver | None = None,
        session_factory: ONNXSafetySessionFactory | None = None,
        image_adapter: SafetyImageAdapter | None = None,
    ) -> None:
        self._artifact_resolver = artifact_resolver or SafetyModelArtifactResolver()
        self._session_factory = session_factory or ONNXSafetySessionFactory()
        self._image_adapter = image_adapter or SafetyImageAdapter()
        self._artifact: ResolvedSafetyModelArtifact | None = None
        self._safety_session: SafetyONNXSession | None = None

    def classify(self, frames: Sequence[Stage1FrameInput]) -> list[Stage1Result]:
        ordered_frames = list(frames)
        if not ordered_frames:
            return []
        safety_session = self._get_session()
        input_tensor = self._image_adapter.prepare_batch(ordered_frames)
        probabilities = safety_session.run(input_tensor)
        artifact = self._artifact
        if artifact is None:  # pragma: no cover - _get_session establishes this invariant
            raise SafetyModelSessionError("Stage-1 session has no resolved model artifact.")
        return [
            Stage1Result(
                sample_id=frame.sample_id,
                source_timestamp_us=frame.source_timestamp_us,
                nsfl_probability=float(row[0]),
                nsfw_probability=float(row[1]),
                sfw_probability=float(row[2]),
                selected_label=LABELS[int(np.argmax(row))],
                model_repository_id=MODEL_REPOSITORY_ID,
                model_revision=MODEL_REVISION,
                artifact_sha256=artifact.sha256,
                onnxruntime_version=safety_session.onnxruntime_version,
                execution_providers=safety_session.execution_providers,
            )
            for frame, row in zip(ordered_frames, probabilities, strict=True)
        ]

    def _get_session(self) -> SafetyONNXSession:
        if self._safety_session is None:
            self._artifact = self._artifact_resolver.resolve()
            self._safety_session = self._session_factory.create(self._artifact)
        return self._safety_session


class Stage1BatchConsumer:
    """Bounded, in-memory batching callback for accepted representative frames."""

    def __init__(self, classifier: Stage1SafetyClassifier, *, batch_size: int) -> None:
        if batch_size <= 0:
            raise ValueError("Stage-1 batch size must be positive.")
        self.classifier = classifier
        self.batch_size = batch_size
        self.results: list[Stage1Result] = []
        self.inference_calls = 0
        self.classification_seconds = 0.0
        self.observed_batch_sizes: list[int] = []
        self._pending: list[Stage1FrameInput] = []

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
        batch_results = self.classifier.classify(pending)
        elapsed_seconds = time.perf_counter() - started_at
        if len(batch_results) != len(pending):
            raise SafetyInferenceError(
                "Stage-1 classifier result count does not match the buffered batch."
            )
        self.results.extend(batch_results)
        self.inference_calls += 1
        self.classification_seconds += elapsed_seconds
        self.observed_batch_sizes.append(len(pending))


class Stage1RepresentativeConsumer(Stage1BatchConsumer):
    """Compatibility callback retaining the Stage-1B one-frame behavior."""

    def __init__(self, classifier: Stage1SafetyClassifier) -> None:
        super().__init__(classifier, batch_size=1)


def _frame_input(frame: ExtractedFrame, sample: FrameSample) -> Stage1FrameInput:
    return Stage1FrameInput(
        sample_id=_sample_id(sample),
        source_timestamp_us=sample.timestamp_us,
        rgb_bytes=frame.rgb_bytes,
        width=frame.width,
        height=frame.height,
        content_rect=frame.content_rect,
    )


def _sample_id(sample: FrameSample) -> str:
    source_pts = "none" if sample.source_pts is None else str(sample.source_pts)
    return f"representative:{sample.owning_chunk_index}:{sample.timestamp_us}:{source_pts}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as artifact:
            while chunk := artifact.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SafetyModelArtifactUnavailableError(
            "The pinned Stage-1 model artifact cannot be read."
        ) from exc
    return digest.hexdigest()


def _validate_session_contract(session: Any) -> None:
    try:
        inputs = list(session.get_inputs())
        outputs = list(session.get_outputs())
        providers = tuple(session.get_providers())
    except Exception as exc:
        raise SafetyModelContractError(
            f"Unable to inspect Stage-1 ONNX metadata ({type(exc).__name__})."
        ) from exc

    if providers != (CPU_EXECUTION_PROVIDER,):
        raise SafetyModelContractError(
            "Stage-1 ONNX session did not activate exactly CPUExecutionProvider."
        )
    if len(inputs) != 1:
        raise SafetyModelContractError("Stage-1 model must expose exactly one input.")
    if len(outputs) != 1:
        raise SafetyModelContractError("Stage-1 model must expose exactly one output.")
    _validate_node_arg(
        inputs[0],
        expected_name=INPUT_NAME,
        expected_type="tensor(float)",
        expected_tail=(3, IMAGE_SIZE, IMAGE_SIZE),
        kind="input",
    )
    _validate_node_arg(
        outputs[0],
        expected_name=OUTPUT_NAME,
        expected_type="tensor(float)",
        expected_tail=(3,),
        kind="output",
    )


def _validate_node_arg(
    node_arg: Any,
    *,
    expected_name: str,
    expected_type: str,
    expected_tail: tuple[int, ...],
    kind: str,
) -> None:
    name = getattr(node_arg, "name", None)
    value_type = getattr(node_arg, "type", None)
    shape = getattr(node_arg, "shape", None)
    if name != expected_name:
        raise SafetyModelContractError(
            f"Stage-1 model {kind} name mismatch: expected '{expected_name}', got '{name}'."
        )
    if value_type != expected_type:
        raise SafetyModelContractError(
            f"Stage-1 model {kind} type mismatch: expected '{expected_type}', got '{value_type}'."
        )
    if not isinstance(shape, Sequence) or len(shape) != len(expected_tail) + 1:
        raise SafetyModelContractError(
            f"Stage-1 model {kind} rank mismatch; expected batch plus {len(expected_tail)} axes."
        )
    if tuple(shape[1:]) != expected_tail:
        raise SafetyModelContractError(
            f"Stage-1 model {kind} shape mismatch: expected dynamic batch plus "
            f"{list(expected_tail)}, got '{shape}'."
        )


def _validate_frame_input(frame: Stage1FrameInput) -> None:
    if not frame.sample_id:
        raise SafetyImagePreprocessingError("Stage-1 frame identity cannot be empty.")
    if frame.source_timestamp_us < 0:
        raise SafetyImagePreprocessingError("Stage-1 frame timestamp cannot be negative.")
    if frame.width <= 0 or frame.height <= 0:
        raise SafetyImagePreprocessingError("Stage-1 frame dimensions must be positive.")
    if len(frame.rgb_bytes) != frame.width * frame.height * 3:
        raise SafetyImagePreprocessingError(
            "Stage-1 RGB frame byte count does not match its dimensions."
        )
    left, top, width, height = frame.content_rect
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise SafetyImagePreprocessingError("Stage-1 content rectangle is invalid.")
    if left + width > frame.width or top + height > frame.height:
        raise SafetyImagePreprocessingError("Stage-1 content rectangle exceeds the RGB frame.")


def _validate_input_tensor(tensor: np.ndarray, *, expected_batch_size: int) -> None:
    if expected_batch_size <= 0:
        raise SafetyImagePreprocessingError("Stage-1 input batch cannot be empty.")
    if tensor.dtype != np.float32:
        raise SafetyImagePreprocessingError("Stage-1 input tensor must be float32.")
    if tensor.shape != (expected_batch_size, 3, IMAGE_SIZE, IMAGE_SIZE):
        raise SafetyImagePreprocessingError(
            "Stage-1 input tensor must have shape [B, 3, 224, 224]."
        )
    if not np.isfinite(tensor).all():
        raise SafetyImagePreprocessingError("Stage-1 input tensor contains non-finite values.")
    if float(tensor.min()) < 0.0 or float(tensor.max()) > 255.0:
        raise SafetyImagePreprocessingError(
            "Stage-1 input tensor must retain RGB pixel values in the 0-255 range."
        )


def _validate_probability_output(outputs: Any, batch_size: int) -> np.ndarray:
    if not isinstance(outputs, Sequence) or len(outputs) != 1:
        raise SafetyInferenceError("Stage-1 ONNX inference must return exactly one output.")
    probabilities = np.asarray(outputs[0])
    if probabilities.dtype != np.float32:
        raise SafetyInferenceError("Stage-1 ONNX probabilities must be float32.")
    if probabilities.shape != (batch_size, len(LABELS)):
        raise SafetyInferenceError(
            "Stage-1 ONNX probabilities must have shape [B, 3] matching the input batch."
        )
    if not np.isfinite(probabilities).all():
        raise SafetyInferenceError("Stage-1 ONNX probabilities contain non-finite values.")
    if float(probabilities.min()) < 0.0 or float(probabilities.max()) > 1.0:
        raise SafetyInferenceError("Stage-1 ONNX probabilities must be within [0, 1].")
    if not np.allclose(probabilities.sum(axis=1), 1.0, rtol=1e-5, atol=1e-5):
        raise SafetyInferenceError("Stage-1 ONNX probability rows must sum to one.")
    return probabilities
