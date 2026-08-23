from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from services.analysis.cancellation import CancellationToken
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.representative_fanout import (
    FinalizableRepresentativeFanout,
    RepresentativeConsumerFailure,
)
from services.analysis.stage1_benchmark import (
    Stage1MemoryMetrics,
    _ProcessTreeMemoryMonitor,
)
from services.analysis.stage1_safety import (
    ONNXSafetySessionFactory,
    ResolvedSafetyModelArtifact,
    SafetyModelArtifactResolver,
    SafetyONNXSession,
    Stage1BatchConsumer,
    Stage1SafetyClassifier,
)
from services.analysis.tinyclip_semantic import (
    MODEL_REPOSITORY_ID,
    MODEL_REVISION,
    ExperimentalPromptBank,
    TinyCLIPBatchConsumer,
    TinyCLIPFrameInput,
    TinyCLIPSemanticClassifier,
)


class TinyCLIPBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_size: int = Field(gt=0)
    successful: bool
    failure: str | None = None
    iterations: int = Field(ge=0)
    mean_batch_latency_ms: float | None = None
    mean_image_preprocessing_ms: float | None = None
    mean_image_encoder_ms: float | None = None
    mean_similarity_ms: float | None = None
    image_encoder_frames_per_second: float | None = None
    end_to_end_frames_per_second: float | None = None
    memory: Stage1MemoryMetrics


class TinyCLIPBenchmarkProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    revision: str
    checkpoint_sha256: str
    torch_version: str
    transformers_version: str
    device: str
    dtype: str
    processor_class: str
    tokenizer_class: str


class TinyCLIPBenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    experimental: bool = True
    artifact_resolution_seconds: float = Field(ge=0.0)
    processor_setup_seconds: float = Field(ge=0.0)
    weights_load_seconds: float = Field(ge=0.0)
    runtime_validation_seconds: float = Field(ge=0.0)
    text_tokenization_seconds: float = Field(ge=0.0)
    text_embedding_seconds: float = Field(ge=0.0)
    prompt_count: int = Field(gt=0)
    prompt_bank_digest: str
    model: TinyCLIPBenchmarkProvenance
    cases: tuple[TinyCLIPBenchmarkCase, ...]
    notes: tuple[str, ...]


class CombinedSafetyTinyCLIPBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    video_path: str
    safety_batch_size: int = Field(gt=0)
    tinyclip_batch_size: int = Field(gt=0)
    movie_duration_seconds: float = Field(ge=0.0)
    combined_wall_seconds: float = Field(gt=0.0)
    media_throughput: float = Field(ge=0.0)
    representatives: int = Field(ge=0)
    safety_results: int = Field(ge=0)
    tinyclip_results: int = Field(ge=0)
    onnx_inference_seconds: float = Field(ge=0.0)
    tinyclip_image_preprocessing_seconds: float = Field(ge=0.0)
    tinyclip_image_encoder_seconds: float = Field(ge=0.0)
    tinyclip_similarity_seconds: float = Field(ge=0.0)
    safety_batch_count: int = Field(ge=0)
    tinyclip_batch_count: int = Field(ge=0)
    failures: tuple[RepresentativeConsumerFailure, ...]
    memory: Stage1MemoryMetrics


def run_tinyclip_benchmark(
    prompt_bank: ExperimentalPromptBank,
    batch_sizes: Sequence[int],
    *,
    iterations: int = 5,
    warmup_runs: int = 1,
    local_files_only: bool = False,
    monitor_memory: bool = True,
) -> TinyCLIPBenchmarkResult:
    if not batch_sizes or any(size <= 0 for size in batch_sizes):
        raise ValueError("TinyCLIP benchmark batch sizes must be positive.")
    if iterations <= 0 or warmup_runs < 0:
        raise ValueError("TinyCLIP benchmark iteration counts are invalid.")

    classifier = TinyCLIPSemanticClassifier(local_files_only=local_files_only)
    load_started = time.perf_counter()
    runtime = classifier.ensure_runtime()
    total_load_seconds = time.perf_counter() - load_started
    artifact = classifier.artifact
    if artifact is None:
        raise RuntimeError("TinyCLIP benchmark has no resolved artifact.")

    token_before = runtime.timing.text_tokenization_seconds
    embedding_before = runtime.timing.text_embedding_seconds
    text_features = runtime.prepare_text_features(prompt_bank)
    text_tokenization_seconds = runtime.timing.text_tokenization_seconds - token_before
    text_embedding_seconds = runtime.timing.text_embedding_seconds - embedding_before

    cases: list[TinyCLIPBenchmarkCase] = []
    for batch_size in batch_sizes:
        monitor = _ProcessTreeMemoryMonitor(enabled=monitor_memory)
        monitor.start()
        try:
            frames = _synthetic_frames(batch_size)
            for _ in range(warmup_runs):
                _run_one(runtime, frames, text_features)
            latencies: list[float] = []
            preprocessing_times: list[float] = []
            encoder_times: list[float] = []
            similarity_times: list[float] = []
            for _ in range(iterations):
                pre_before = runtime.timing.image_preprocessing_seconds
                encoder_before = runtime.timing.image_encoder_seconds
                similarity_before = runtime.timing.similarity_seconds
                started_at = time.perf_counter()
                _run_one(runtime, frames, text_features)
                latencies.append(time.perf_counter() - started_at)
                preprocessing_times.append(
                    runtime.timing.image_preprocessing_seconds - pre_before
                )
                encoder_times.append(runtime.timing.image_encoder_seconds - encoder_before)
                similarity_times.append(
                    runtime.timing.similarity_seconds - similarity_before
                )
            memory = monitor.stop()
            mean_latency = statistics.fmean(latencies)
            mean_encoder = statistics.fmean(encoder_times)
            cases.append(
                TinyCLIPBenchmarkCase(
                    batch_size=batch_size,
                    successful=True,
                    iterations=iterations,
                    mean_batch_latency_ms=mean_latency * 1000.0,
                    mean_image_preprocessing_ms=(
                        statistics.fmean(preprocessing_times) * 1000.0
                    ),
                    mean_image_encoder_ms=mean_encoder * 1000.0,
                    mean_similarity_ms=statistics.fmean(similarity_times) * 1000.0,
                    image_encoder_frames_per_second=(
                        batch_size / mean_encoder if mean_encoder > 0.0 else 0.0
                    ),
                    end_to_end_frames_per_second=(
                        batch_size / mean_latency if mean_latency > 0.0 else 0.0
                    ),
                    memory=memory,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report per-size resource failures
            memory = monitor.stop()
            cases.append(
                TinyCLIPBenchmarkCase(
                    batch_size=batch_size,
                    successful=False,
                    failure=f"{type(exc).__name__}: {exc}",
                    iterations=0,
                    memory=memory,
                )
            )

    known_load_parts = (
        classifier.artifact_resolution_seconds
        + runtime.processor_setup_seconds
        + runtime.weights_load_seconds
    )
    return TinyCLIPBenchmarkResult(
        artifact_resolution_seconds=classifier.artifact_resolution_seconds,
        processor_setup_seconds=runtime.processor_setup_seconds,
        weights_load_seconds=runtime.weights_load_seconds,
        runtime_validation_seconds=max(0.0, total_load_seconds - known_load_parts),
        text_tokenization_seconds=text_tokenization_seconds,
        text_embedding_seconds=text_embedding_seconds,
        prompt_count=len(prompt_bank.prompts),
        prompt_bank_digest=prompt_bank.digest,
        model=TinyCLIPBenchmarkProvenance(
            repository_id=MODEL_REPOSITORY_ID,
            revision=MODEL_REVISION,
            checkpoint_sha256=artifact.sha256,
            torch_version=runtime.torch_version,
            transformers_version=runtime.transformers_version,
            device=runtime.device,
            dtype=runtime.dtype,
            processor_class=runtime.processor_class,
            tokenizer_class=runtime.tokenizer_class,
        ),
        cases=tuple(cases),
        notes=(
            "Synthetic images are used; results measure runtime mechanics, not semantics.",
            "Batch sizes are evaluation inputs and do not establish a production default.",
            "Scaled logits and cosine similarities are not calibrated probabilities.",
        ),
    )


def run_combined_safety_tinyclip_benchmark(
    video_path: str | Path,
    prompt_bank: ExperimentalPromptBank,
    *,
    safety_batch_size: int,
    tinyclip_batch_size: int,
    config: PreprocessingConfig | None = None,
    local_files_only: bool = False,
    monitor_memory: bool = True,
) -> CombinedSafetyTinyCLIPBenchmark:
    """Benchmark one decode feeding both Stage-1 specialists."""
    resolved_video = Path(video_path).expanduser().resolve()
    if not resolved_video.is_file():
        raise FileNotFoundError(f"Video does not exist: {resolved_video}")
    if safety_batch_size <= 0 or tinyclip_batch_size <= 0:
        raise ValueError("Combined benchmark batch sizes must be positive.")

    safety_artifact = SafetyModelArtifactResolver().resolve(
        local_files_only=local_files_only
    )
    safety_session = ONNXSafetySessionFactory().create(safety_artifact)
    safety_classifier = Stage1SafetyClassifier(
        artifact_resolver=_ResolvedSafetyArtifactResolver(safety_artifact),
        session_factory=_ResolvedSafetySessionFactory(safety_session),
    )
    safety_consumer = Stage1BatchConsumer(
        safety_classifier,
        batch_size=safety_batch_size,
    )

    tinyclip_classifier = TinyCLIPSemanticClassifier(
        local_files_only=local_files_only
    )
    tinyclip_classifier.prepare_prompt_bank(prompt_bank)
    tinyclip_consumer = TinyCLIPBatchConsumer(
        tinyclip_classifier,
        prompt_bank,
        batch_size=tinyclip_batch_size,
    )
    fanout = FinalizableRepresentativeFanout(
        (("onnx-safety", safety_consumer), ("tinyclip-semantic", tinyclip_consumer))
    )
    token = CancellationToken()
    monitor = _ProcessTreeMemoryMonitor(enabled=monitor_memory)
    monitor.start()
    started_at = time.perf_counter()
    try:
        result = MoviePreprocessingService().preprocess(
            resolved_video,
            config=config or PreprocessingConfig(),
            cancellation=token,
            representative_callback=fanout,
        )
    finally:
        combined_wall_seconds = time.perf_counter() - started_at
        memory = monitor.stop()
    runtime = tinyclip_classifier.runtime
    if runtime is None:
        raise RuntimeError("Combined benchmark did not initialize TinyCLIP.")
    duration_seconds = result.statistics.movie_duration_seconds
    return CombinedSafetyTinyCLIPBenchmark(
        video_path=str(resolved_video),
        safety_batch_size=safety_batch_size,
        tinyclip_batch_size=tinyclip_batch_size,
        movie_duration_seconds=duration_seconds,
        combined_wall_seconds=combined_wall_seconds,
        media_throughput=(
            duration_seconds / combined_wall_seconds
            if combined_wall_seconds > 0.0
            else 0.0
        ),
        representatives=len(result.representative_frames),
        safety_results=len(safety_consumer.results),
        tinyclip_results=len(tinyclip_consumer.results),
        onnx_inference_seconds=safety_session.onnx_inference_seconds,
        tinyclip_image_preprocessing_seconds=(
            runtime.timing.image_preprocessing_seconds
        ),
        tinyclip_image_encoder_seconds=runtime.timing.image_encoder_seconds,
        tinyclip_similarity_seconds=runtime.timing.similarity_seconds,
        safety_batch_count=safety_consumer.inference_calls,
        tinyclip_batch_count=tinyclip_consumer.inference_calls,
        failures=tuple(fanout.failures),
        memory=memory,
    )
def _run_one(runtime: object, frames: Sequence[TinyCLIPFrameInput], text: object) -> None:
    pixel_values = runtime.prepare_image_batch(frames)
    images = runtime.encode_image_features(pixel_values, expected_rows=len(frames))
    runtime.cosine_similarities(images, text)


def _synthetic_frames(batch_size: int) -> list[TinyCLIPFrameInput]:
    frames: list[TinyCLIPFrameInput] = []
    for index in range(batch_size):
        image = Image.new(
            "RGB",
            (384, 384),
            ((index * 37) % 256, (index * 67) % 256, (index * 97) % 256),
        )
        frames.append(
            TinyCLIPFrameInput(
                sample_id=f"synthetic:{index}",
                source_timestamp_us=index * 1_000_000,
                rgb_bytes=image.tobytes(),
                width=384,
                height=384,
                content_rect=(32, 64, 320, 256),
            )
        )
    return frames


class _ResolvedSafetyArtifactResolver:
    def __init__(self, artifact: ResolvedSafetyModelArtifact) -> None:
        self.artifact = artifact

    def resolve(self) -> ResolvedSafetyModelArtifact:
        return self.artifact


class _ResolvedSafetySessionFactory:
    def __init__(self, session: SafetyONNXSession) -> None:
        self.session = session

    def create(self, _artifact: ResolvedSafetyModelArtifact) -> SafetyONNXSession:
        return self.session
