from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, computed_field

from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_safety import (
    CPU_EXECUTION_PROVIDER,
    IMAGE_SIZE,
    MODEL_REPOSITORY_ID,
    MODEL_REVISION,
    ONNXSafetySessionFactory,
    ResolvedSafetyModelArtifact,
    SafetyModelArtifactResolver,
    SafetyONNXSession,
    Stage1BatchConsumer,
    Stage1FrameInput,
    Stage1SafetyClassifier,
)

STAGE1_BENCHMARK_SCHEMA_VERSION = 2


class Stage1BenchmarkModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_id: str
    revision: str
    artifact_sha256: str
    onnxruntime_version: str
    execution_providers: tuple[str, ...]


class Stage1MemoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    monitoring_available: bool
    unavailable_reason: str | None = None
    sample_interval_seconds: float | None = Field(default=None, gt=0.0)
    samples: int = Field(ge=0)
    baseline_python_rss_bytes: int | None = Field(default=None, ge=0)
    peak_python_rss_bytes: int | None = Field(default=None, ge=0)
    peak_child_rss_bytes: int | None = Field(default=None, ge=0)
    peak_process_tree_rss_bytes: int | None = Field(default=None, ge=0)
    peak_process_tree_rss_delta_bytes: int | None = Field(default=None, ge=0)
    measurement_note: str


class IsolatedInferenceBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_size: int = Field(gt=0)
    warmup_runs: int = Field(ge=0)
    measured_runs: int = Field(gt=0)
    frames_measured: int = Field(gt=0)
    onnx_inference_seconds: float = Field(gt=0.0)
    measured_loop_seconds: float = Field(gt=0.0)
    frames_per_onnx_second: float = Field(gt=0.0)
    mean_onnx_call_milliseconds: float = Field(gt=0.0)
    mean_onnx_frame_milliseconds: float = Field(gt=0.0)
    memory: Stage1MemoryMetrics


class CombinedPreprocessingStage1Benchmark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    video_path: str
    batch_size: int = Field(gt=0)
    movie_duration_seconds: float = Field(gt=0.0)
    combined_wall_seconds: float = Field(gt=0.0)
    media_throughput: float = Field(ge=0.0)
    representatives_classified: int = Field(ge=0)
    representative_frames_per_second: float = Field(ge=0.0)
    stage1_callback_seconds: float = Field(ge=0.0)
    onnx_inference_seconds: float = Field(ge=0.0)
    onnx_inference_calls: int = Field(ge=0)
    observed_batch_sizes: tuple[int, ...] = Field(exclude=True)
    result_count_matches_representatives: bool
    input_order_preserved: bool
    memory: Stage1MemoryMetrics

    @computed_field
    @property
    def valid(self) -> bool:
        return self.result_count_matches_representatives and self.input_order_preserved

    @computed_field
    @property
    def inference_batch_count(self) -> int:
        return len(self.observed_batch_sizes)

    @computed_field
    @property
    def full_batch_count(self) -> int:
        return sum(size == self.batch_size for size in self.observed_batch_sizes)

    @computed_field
    @property
    def partial_batch_count(self) -> int:
        return sum(size < self.batch_size for size in self.observed_batch_sizes)

    @computed_field
    @property
    def average_batch_occupancy(self) -> float:
        if not self.observed_batch_sizes:
            return 0.0
        return sum(self.observed_batch_sizes) / (
            len(self.observed_batch_sizes) * self.batch_size
        )

    @computed_field
    @property
    def final_batch_size(self) -> int | None:
        return self.observed_batch_sizes[-1] if self.observed_batch_sizes else None


class Stage1ThroughputBenchmarkResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = STAGE1_BENCHMARK_SCHEMA_VERSION
    generated_at_utc: str
    model: Stage1BenchmarkModelInfo
    isolated_inference: tuple[IsolatedInferenceBenchmark, ...]
    preprocessing_plus_stage1: tuple[CombinedPreprocessingStage1Benchmark, ...]
    notes: tuple[str, ...]

    @computed_field
    @property
    def valid(self) -> bool:
        return all(case.valid for case in self.preprocessing_plus_stage1)


def run_stage1_throughput_benchmark(
    video_path: str | Path,
    batch_sizes: Sequence[int],
    *,
    config: PreprocessingConfig | None = None,
    isolated_iterations: int = 10,
    warmup_runs: int = 2,
    monitor_memory: bool = True,
    local_files_only: bool = False,
    artifact_resolver: SafetyModelArtifactResolver | None = None,
    session_factory: ONNXSafetySessionFactory | None = None,
    preprocessing_service_factory: Callable[[], MoviePreprocessingService] | None = None,
) -> Stage1ThroughputBenchmarkResult:
    """Measure batch effects without selecting a production batch size."""
    resolved_video_path = Path(video_path).expanduser().resolve()
    if not resolved_video_path.is_file():
        raise FileNotFoundError(f"Video does not exist: {resolved_video_path}")
    normalized_batch_sizes = _validate_benchmark_inputs(
        batch_sizes,
        isolated_iterations=isolated_iterations,
        warmup_runs=warmup_runs,
    )
    resolver = artifact_resolver or SafetyModelArtifactResolver()
    factory = session_factory or ONNXSafetySessionFactory()
    artifact = resolver.resolve(local_files_only=local_files_only)

    isolated_cases: list[IsolatedInferenceBenchmark] = []
    combined_cases: list[CombinedPreprocessingStage1Benchmark] = []
    model_info: Stage1BenchmarkModelInfo | None = None
    for batch_size in normalized_batch_sizes:
        isolated_session = factory.create(artifact)
        model_info = model_info or _model_info(artifact, isolated_session)
        isolated_cases.append(
            _run_isolated_case(
                isolated_session,
                batch_size=batch_size,
                iterations=isolated_iterations,
                warmup_runs=warmup_runs,
                monitor_memory=monitor_memory,
            )
        )

        combined_session = factory.create(artifact)
        combined_cases.append(
            _run_combined_case(
                resolved_video_path,
                artifact,
                combined_session,
                batch_size=batch_size,
                config=config or PreprocessingConfig(),
                monitor_memory=monitor_memory,
                preprocessing_service_factory=preprocessing_service_factory,
            )
        )

    if model_info is None:  # pragma: no cover - validated batch sizes are non-empty
        raise ValueError("at least one batch size is required")
    return Stage1ThroughputBenchmarkResult(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        model=model_info,
        isolated_inference=tuple(isolated_cases),
        preprocessing_plus_stage1=tuple(combined_cases),
        notes=(
            "No batch size is selected or recommended by this benchmark.",
            "ONNX-only timing measures session.run on a prebuilt float32 NCHW tensor.",
            "Artifact resolution, SHA-256 verification, session creation, and warm-up are excluded from throughput timing.",
            "Combined timing includes movie probe, extraction, frame filtering, image adaptation, ONNX inference, and final partial-batch flush.",
            "RSS is sampled and may miss allocations shorter than the sampling interval; child RSS includes FFmpeg during combined runs.",
            "Filesystem and native-runtime caches may warm across cases; compare repeated benchmark executions before making a later tuning decision.",
        ),
    )


def _run_isolated_case(
    session: SafetyONNXSession,
    *,
    batch_size: int,
    iterations: int,
    warmup_runs: int,
    monitor_memory: bool,
) -> IsolatedInferenceBenchmark:
    monitor = _ProcessTreeMemoryMonitor(enabled=monitor_memory)
    monitor.start()
    input_tensor = np.zeros(
        (batch_size, 3, IMAGE_SIZE, IMAGE_SIZE),
        dtype=np.float32,
    )
    monitor.capture()
    try:
        for _ in range(warmup_runs):
            session.run(input_tensor)
            monitor.capture()

        total_onnx_seconds = 0.0
        loop_started_at = time.perf_counter()
        for _ in range(iterations):
            _probabilities, inference_seconds = session.run_timed(input_tensor)
            total_onnx_seconds += inference_seconds
            monitor.capture()
        loop_seconds = time.perf_counter() - loop_started_at
    finally:
        memory = monitor.stop()

    frames_measured = batch_size * iterations
    return IsolatedInferenceBenchmark(
        batch_size=batch_size,
        warmup_runs=warmup_runs,
        measured_runs=iterations,
        frames_measured=frames_measured,
        onnx_inference_seconds=total_onnx_seconds,
        measured_loop_seconds=loop_seconds,
        frames_per_onnx_second=frames_measured / total_onnx_seconds,
        mean_onnx_call_milliseconds=(total_onnx_seconds / iterations) * 1_000.0,
        mean_onnx_frame_milliseconds=(total_onnx_seconds / frames_measured) * 1_000.0,
        memory=memory,
    )


def _run_combined_case(
    video_path: Path,
    artifact: ResolvedSafetyModelArtifact,
    session: SafetyONNXSession,
    *,
    batch_size: int,
    config: PreprocessingConfig,
    monitor_memory: bool,
    preprocessing_service_factory: Callable[[], MoviePreprocessingService] | None,
) -> CombinedPreprocessingStage1Benchmark:
    classifier = Stage1SafetyClassifier(
        artifact_resolver=_ResolvedArtifactResolver(artifact),
        session_factory=_ResolvedSessionFactory(session),
    )
    # A one-frame warm-up excludes lazy session ownership and first-run costs without
    # preallocating the batch-specific buffers that the memory measurement targets.
    classifier.classify([_synthetic_frame_input()])
    initial_calls = session.inference_calls
    initial_onnx_seconds = session.onnx_inference_seconds

    consumer = Stage1BatchConsumer(classifier, batch_size=batch_size)
    preprocessing_service = (
        preprocessing_service_factory()
        if preprocessing_service_factory is not None
        else MoviePreprocessingService()
    )
    monitor = _ProcessTreeMemoryMonitor(enabled=monitor_memory)
    monitor.start()
    combined_started_at = time.perf_counter()
    try:
        preprocessing_result = preprocessing_service.preprocess(
            video_path,
            config=config,
            representative_callback=consumer,
        )
        combined_wall_seconds = time.perf_counter() - combined_started_at
        monitor.capture()
    finally:
        memory = monitor.stop()

    representatives = preprocessing_result.representative_frames
    result_ids = [result.sample_id for result in consumer.results]
    expected_ids = [_sample_id_from_metadata(sample) for sample in representatives]
    representative_count = len(representatives)
    return CombinedPreprocessingStage1Benchmark(
        video_path=str(video_path),
        batch_size=batch_size,
        movie_duration_seconds=preprocessing_result.statistics.movie_duration_seconds,
        combined_wall_seconds=combined_wall_seconds,
        media_throughput=(
            preprocessing_result.statistics.movie_duration_seconds / combined_wall_seconds
        ),
        representatives_classified=len(consumer.results),
        representative_frames_per_second=len(consumer.results) / combined_wall_seconds,
        stage1_callback_seconds=consumer.classification_seconds,
        onnx_inference_seconds=(session.onnx_inference_seconds - initial_onnx_seconds),
        onnx_inference_calls=session.inference_calls - initial_calls,
        observed_batch_sizes=tuple(consumer.observed_batch_sizes),
        result_count_matches_representatives=(
            len(consumer.results) == representative_count
        ),
        input_order_preserved=result_ids == expected_ids,
        memory=memory,
    )


def _validate_benchmark_inputs(
    batch_sizes: Sequence[int],
    *,
    isolated_iterations: int,
    warmup_runs: int,
) -> tuple[int, ...]:
    normalized = tuple(dict.fromkeys(batch_sizes))
    if not normalized:
        raise ValueError("at least one batch size is required")
    if any(batch_size <= 0 for batch_size in normalized):
        raise ValueError("batch sizes must be positive")
    if isolated_iterations <= 0:
        raise ValueError("isolated iterations must be positive")
    if warmup_runs < 0:
        raise ValueError("warm-up runs cannot be negative")
    return normalized


def _model_info(
    artifact: ResolvedSafetyModelArtifact,
    session: SafetyONNXSession,
) -> Stage1BenchmarkModelInfo:
    if session.execution_providers != (CPU_EXECUTION_PROVIDER,):
        raise RuntimeError("Stage-1 benchmark requires exactly CPUExecutionProvider.")
    return Stage1BenchmarkModelInfo(
        repository_id=MODEL_REPOSITORY_ID,
        revision=MODEL_REVISION,
        artifact_sha256=artifact.sha256,
        onnxruntime_version=session.onnxruntime_version,
        execution_providers=session.execution_providers,
    )


def _synthetic_frame_input() -> Stage1FrameInput:
    width = 4
    height = 4
    return Stage1FrameInput(
        sample_id="benchmark-warmup",
        source_timestamp_us=0,
        rgb_bytes=bytes((127, 127, 127)) * width * height,
        width=width,
        height=height,
        content_rect=(0, 0, width, height),
    )


def _sample_id_from_metadata(sample: Any) -> str:
    source_pts = "none" if sample.source_pts is None else str(sample.source_pts)
    return (
        f"representative:{sample.owning_chunk_index}:"
        f"{sample.timestamp_us}:{source_pts}"
    )


class _ResolvedArtifactResolver:
    def __init__(self, artifact: ResolvedSafetyModelArtifact) -> None:
        self.artifact = artifact

    def resolve(self) -> ResolvedSafetyModelArtifact:
        return self.artifact


class _ResolvedSessionFactory:
    def __init__(self, session: SafetyONNXSession) -> None:
        self.session = session

    def create(self, _artifact: ResolvedSafetyModelArtifact) -> SafetyONNXSession:
        return self.session


class _ProcessTreeMemoryMonitor:
    def __init__(
        self,
        *,
        enabled: bool,
        sample_interval_seconds: float = 0.05,
    ) -> None:
        self.sample_interval_seconds = sample_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._python_rss: list[int] = []
        self._child_rss: list[int] = []
        self._tree_rss: list[int] = []
        self._psutil = None
        self._process = None
        self._process_errors: tuple[type[BaseException], ...] = (OSError,)
        self._unavailable_reason: str | None = None
        if not enabled:
            self._unavailable_reason = "memory monitoring disabled"
            return
        try:
            self._psutil = importlib.import_module("psutil")
            self._process = self._psutil.Process()
            self._process_errors = (self._psutil.Error, OSError)
        except (ImportError, OSError) as exc:
            self._unavailable_reason = f"optional psutil monitoring unavailable: {exc}"

    def start(self) -> None:
        if self._process is None:
            return
        self.capture()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="stage1-benchmark-memory",
            daemon=True,
        )
        self._thread.start()

    def capture(self) -> None:
        if self._process is None:
            return
        try:
            python_rss = int(self._process.memory_info().rss)
            children = self._process.children(recursive=True)
            child_rss = sum(int(child.memory_info().rss) for child in children)
        except self._process_errors:
            return
        self._python_rss.append(python_rss)
        self._child_rss.append(child_rss)
        self._tree_rss.append(python_rss + child_rss)

    def stop(self) -> Stage1MemoryMetrics:
        if self._process is None:
            return Stage1MemoryMetrics(
                monitoring_available=False,
                unavailable_reason=self._unavailable_reason,
                samples=0,
                measurement_note=(
                    "Install requirements-benchmark.txt to collect sampled RSS."
                ),
            )
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.capture()
        baseline = self._tree_rss[0]
        peak_tree = max(self._tree_rss)
        return Stage1MemoryMetrics(
            monitoring_available=True,
            sample_interval_seconds=self.sample_interval_seconds,
            samples=len(self._tree_rss),
            baseline_python_rss_bytes=self._python_rss[0],
            peak_python_rss_bytes=max(self._python_rss),
            peak_child_rss_bytes=max(self._child_rss),
            peak_process_tree_rss_bytes=peak_tree,
            peak_process_tree_rss_delta_bytes=max(0, peak_tree - baseline),
            measurement_note=(
                "RSS is sampled for the Python process and recursive child processes; "
                "native ONNX allocations are included in Python process RSS."
            ),
        )

    def _sample_loop(self) -> None:
        while not self._stop_event.wait(self.sample_interval_seconds):
            self.capture()
