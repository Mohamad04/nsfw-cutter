from __future__ import annotations

import importlib
import statistics
import threading
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from services.analysis.chunking import owning_chunk_index
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    PreprocessingConfig,
    PreprocessingResult,
    SampleReason,
)
from services.analysis.preprocessing_instrumentation import (
    InstrumentationSnapshot,
    PreprocessingInstrumentation,
)
from services.export.media_probe_service import MediaInfo, MediaProbeService
from services.infrastructure.ffmpeg.runner import FFmpegService

BENCHMARK_SCHEMA_VERSION = 1


class BenchmarkSourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    path: str
    container: str | None
    duration_seconds: float = Field(gt=0.0)
    selected_video_stream_index: int = Field(ge=0)
    codec: str | None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    display_aspect_ratio: str | None
    nominal_fps: float | None = Field(default=None, gt=0.0)
    frame_rate_mode: Literal["likely_cfr", "likely_vfr", "undetermined"]
    frame_rate_evidence: str


class BenchmarkConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sampling_gap_seconds: float = Field(gt=0.0)
    chunk_duration_seconds: float = Field(gt=0.0)
    chunk_overlap_seconds: float = Field(ge=0.0)
    target_width: int = Field(gt=0)
    target_height: int = Field(gt=0)
    selected_video_stream_index: int = Field(ge=0)
    scene_threshold: float = Field(ge=0.0, le=1.0)
    black_pixel_luma_threshold: int = Field(ge=0, le=255)
    black_frame_ratio_threshold: float = Field(ge=0.0, le=1.0)
    black_mean_luma_threshold: float = Field(ge=0.0, le=255.0)
    perceptual_hash_algorithm: str
    perceptual_hash_version: int = Field(ge=1)
    duplicate_hamming_threshold: int = Field(ge=0)
    static_suppression_limit_seconds: float = Field(gt=0.0)
    physical_execution_mode: Literal["one_ffmpeg_process_per_logical_chunk"] = (
        "one_ffmpeg_process_per_logical_chunk"
    )


class BenchmarkStageTimings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    media_probe_seconds: float = Field(ge=0.0)
    process_popen_seconds: float = Field(ge=0.0)
    startup_seek_to_first_rgb_seconds: float = Field(ge=0.0)
    ffmpeg_process_lifetime_seconds: float = Field(ge=0.0)
    frame_stream_wait_seconds: float = Field(ge=0.0)
    frame_assembly_seconds: float = Field(ge=0.0)
    python_frame_preparation_seconds: float = Field(ge=0.0)
    black_filtering_seconds: float = Field(ge=0.0)
    perceptual_hashing_seconds: float = Field(ge=0.0)
    duplicate_static_reduction_seconds: float = Field(ge=0.0)
    result_materialization_seconds: float = Field(ge=0.0)
    python_filter_total_seconds: float = Field(ge=0.0)
    chunk_merge_finalization_seconds: float = Field(ge=0.0)
    total_preprocessing_wall_seconds: float = Field(ge=0.0)
    correctness_verification_seconds: float = Field(ge=0.0)
    measurement_notes: tuple[str, ...]


class BenchmarkCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunks: int = Field(ge=0)
    ffmpeg_process_launches: int = Field(ge=0)
    temporal_samples: int = Field(ge=0)
    scene_samples: int = Field(ge=0)
    union_samples: int = Field(ge=0)
    overlap_context_samples_discarded: int = Field(ge=0)
    black_frames_removed: int = Field(ge=0)
    near_duplicates_removed: int = Field(ge=0)
    static_frames_suppressed: int = Field(ge=0)
    representatives_retained: int = Field(ge=0)


class BenchmarkDataVolume(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_rgb_bytes_received: int = Field(ge=0)
    approximate_python_rgb_bytes_processed: int = Field(ge=0)
    peak_stdout_queue_bytes: int = Field(ge=0)
    peak_stdout_queue_items: int = Field(ge=0)


class BenchmarkResourceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    monitoring_available: bool
    unavailable_reason: str | None = None
    sample_interval_seconds: float | None = Field(default=None, gt=0.0)
    samples: int = Field(ge=0)
    average_system_cpu_percent: float | None = Field(default=None, ge=0.0)
    peak_system_cpu_percent: float | None = Field(default=None, ge=0.0)
    average_python_cpu_percent: float | None = Field(default=None, ge=0.0)
    peak_python_cpu_percent: float | None = Field(default=None, ge=0.0)
    average_ffmpeg_cpu_percent: float | None = Field(default=None, ge=0.0)
    peak_ffmpeg_cpu_percent: float | None = Field(default=None, ge=0.0)
    average_process_tree_cpu_percent: float | None = Field(default=None, ge=0.0)
    peak_process_tree_cpu_percent: float | None = Field(default=None, ge=0.0)
    peak_python_rss_bytes: int | None = Field(default=None, ge=0)
    peak_ffmpeg_rss_bytes: int | None = Field(default=None, ge=0)
    measurement_note: str


class BenchmarkInvariantCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    detail: str


class BenchmarkCorrectness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    checks: tuple[BenchmarkInvariantCheck, ...]


class BenchmarkRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_index: int = Field(ge=1)
    source: BenchmarkSourceInfo
    configuration: BenchmarkConfiguration
    timings: BenchmarkStageTimings
    media_throughput: float = Field(ge=0.0)
    realtime_factor: float = Field(ge=0.0)
    counts: BenchmarkCounts
    data_volume: BenchmarkDataVolume
    resources: BenchmarkResourceMetrics
    correctness: BenchmarkCorrectness


class BenchmarkAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_count: int = Field(ge=1)
    valid_runs: int = Field(ge=0)
    invalid_runs: int = Field(ge=0)
    median_wall_seconds: float | None = Field(default=None, ge=0.0)
    minimum_wall_seconds: float | None = Field(default=None, ge=0.0)
    maximum_wall_seconds: float | None = Field(default=None, ge=0.0)
    median_media_throughput: float | None = Field(default=None, ge=0.0)
    repeated_run_caveat: str


class BenchmarkCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    configuration: BenchmarkConfiguration
    runs: tuple[BenchmarkRunResult, ...]
    aggregate: BenchmarkAggregate


class BenchmarkSuiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = BENCHMARK_SCHEMA_VERSION
    generated_at_utc: str
    video_path: str
    cases: tuple[BenchmarkCaseResult, ...]
    notes: tuple[str, ...]

    @computed_field
    @property
    def valid(self) -> bool:
        return all(run.correctness.valid for case in self.cases for run in case.runs)


def calculate_performance_rates(
    movie_duration_seconds: float,
    preprocessing_wall_seconds: float,
) -> tuple[float, float]:
    if movie_duration_seconds <= 0.0:
        raise ValueError("movie duration must be positive")
    if preprocessing_wall_seconds <= 0.0:
        raise ValueError("preprocessing wall time must be positive")
    return (
        movie_duration_seconds / preprocessing_wall_seconds,
        preprocessing_wall_seconds / movie_duration_seconds,
    )


def summarize_wall_times(wall_times: Sequence[float]) -> tuple[float, float, float]:
    if not wall_times:
        raise ValueError("at least one wall time is required")
    if any(value < 0.0 for value in wall_times):
        raise ValueError("wall times cannot be negative")
    return statistics.median(wall_times), min(wall_times), max(wall_times)


def run_benchmark_suite(
    video_path: str | Path,
    configurations: Sequence[PreprocessingConfig],
    *,
    runs: int = 1,
    monitor_resources: bool = True,
    ffmpeg_service: FFmpegService | None = None,
) -> BenchmarkSuiteResult:
    resolved_path = Path(video_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Video does not exist: {resolved_path}")
    if not resolved_path.is_file():
        raise ValueError(f"Video path is not a file: {resolved_path}")
    if not configurations:
        raise ValueError("at least one preprocessing configuration is required")
    if runs <= 0:
        raise ValueError("runs must be positive")

    resolved_ffmpeg_service = ffmpeg_service or FFmpegService()
    cases: list[BenchmarkCaseResult] = []
    for config in configurations:
        run_results = tuple(
            _run_once(
                resolved_path,
                config,
                run_index=run_index,
                monitor_resources=monitor_resources,
                ffmpeg_service=resolved_ffmpeg_service,
            )
            for run_index in range(1, runs + 1)
        )
        cases.append(
            BenchmarkCaseResult(
                configuration=_benchmark_configuration(config),
                runs=run_results,
                aggregate=aggregate_benchmark_runs(run_results),
            )
        )

    return BenchmarkSuiteResult(
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        video_path=str(resolved_path),
        cases=tuple(cases),
        notes=(
            "Repeated runs repeat preprocessing, but OS filesystem caches may warm between runs.",
            "Stage timings are not additive: FFmpeg process lifetime overlaps Python filtering.",
            "Benchmark instrumentation and optional resource sampling overhead are included.",
            (
                "Continuous decode is intentionally not implemented: a valid comparison requires "
                "decoupling physical extraction ranges from logical chunk ownership while keeping "
                "temporal buckets and scene state globally equivalent."
            ),
        ),
    )


def verify_preprocessing_result(
    result: PreprocessingResult,
    snapshot: InstrumentationSnapshot,
) -> BenchmarkCorrectness:
    checks: list[BenchmarkInvariantCheck] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append(BenchmarkInvariantCheck(name=name, passed=passed, detail=detail))

    observations = snapshot.observations
    timestamps = [observation.timestamp_us for observation in observations]
    duration_us = result.statistics.movie_duration_us

    add_check(
        "timestamps_sorted",
        timestamps == sorted(timestamps),
        f"observed {len(timestamps)} globally ordered sample timestamps",
    )
    timestamps_in_range = all(0 <= timestamp <= duration_us for timestamp in timestamps)
    add_check(
        "timestamps_within_media",
        timestamps_in_range,
        f"expected every timestamp in [0, {duration_us}] microseconds",
    )

    chunks = result.chunks
    complete_core_coverage = bool(chunks)
    if chunks:
        complete_core_coverage = (
            chunks[0].core_start_us == 0
            and chunks[-1].core_end_us == duration_us
            and all(
                left.core_end_us == right.core_start_us
                for left, right in pairwise(chunks)
            )
            and all(chunk.index == index for index, chunk in enumerate(chunks))
            and all(
                chunk.decode_start_us <= chunk.core_start_us
                and chunk.decode_end_us >= chunk.core_end_us
                for chunk in chunks
            )
        )
    add_check(
        "complete_chunk_core_coverage",
        complete_core_coverage,
        f"checked {len(chunks)} logical chunks against the full media duration",
    )

    owner_consistency = all(
        owning_chunk_index(chunks, observation.timestamp_us)
        == observation.owning_chunk_index
        for observation in observations
    )
    add_check(
        "deterministic_chunk_ownership",
        owner_consistency,
        "every considered sample belongs to its recorded half-open core range",
    )

    temporal_timestamps = [
        observation.timestamp_us
        for observation in observations
        if SampleReason.TEMPORAL_SAFETY in observation.sample_reasons
    ]
    temporal_coverage = bool(temporal_timestamps)
    maximum_observed_gap_us: int | None = None
    if temporal_timestamps:
        coverage_gaps = [temporal_timestamps[0]]
        coverage_gaps.extend(
            right - left for left, right in pairwise(temporal_timestamps)
        )
        coverage_gaps.append(duration_us - temporal_timestamps[-1])
        maximum_observed_gap_us = max(coverage_gaps)
        temporal_coverage = maximum_observed_gap_us <= result.config.max_sampling_gap_us
    add_check(
        "maximum_temporal_safety_gap",
        temporal_coverage,
        (
            f"maximum observed edge/inter-sample gap was {maximum_observed_gap_us} us; "
            f"configured maximum is {result.config.max_sampling_gap_us} us"
        ),
    )

    representative_timestamps = {
        observation.timestamp_us
        for observation in observations
        if observation.disposition is FrameDisposition.REPRESENTATIVE
    }
    static_policy_valid = all(
        observation.duplicate_of_timestamp_us in representative_timestamps
        and observation.duplicate_of_timestamp_us is not None
        and 0
        <= observation.timestamp_us - observation.duplicate_of_timestamp_us
        < result.config.static_suppression_limit_us
        and SampleReason.SCENE_TRANSITION not in observation.sample_reasons
        for observation in observations
        if observation.disposition is FrameDisposition.STATIC_SUPPRESSED
    )
    add_check(
        "static_representative_policy",
        static_policy_valid,
        "every suppressed static sample references a recent retained representative",
    )

    representative_count_valid = (
        result.statistics.representative_frames > 0
        and result.statistics.representative_frames == len(result.representative_frames)
    )
    add_check(
        "representatives_nonzero_and_consistent",
        representative_count_valid,
        (
            f"statistics={result.statistics.representative_frames}, "
            f"result={len(result.representative_frames)}"
        ),
    )

    disposition_total = (
        result.statistics.black_frames_removed
        + result.statistics.duplicates_removed
        + result.statistics.static_frames_suppressed
        + result.statistics.representative_frames
    )
    sample_accounting_valid = (
        result.statistics.samples_considered == len(observations)
        and result.statistics.samples_considered == disposition_total
    )
    add_check(
        "sample_accounting",
        sample_accounting_valid,
        (
            f"considered={result.statistics.samples_considered}, "
            f"observed={len(observations)}, dispositions={disposition_total}"
        ),
    )

    return BenchmarkCorrectness(
        valid=all(check.passed for check in checks),
        checks=tuple(checks),
    )


def _run_once(
    video_path: Path,
    config: PreprocessingConfig,
    *,
    run_index: int,
    monitor_resources: bool,
    ffmpeg_service: FFmpegService,
) -> BenchmarkRunResult:
    instrumentation = PreprocessingInstrumentation()
    probe_service = _RecordingMediaProbeService(
        MediaProbeService(ffmpeg_service=ffmpeg_service)
    )
    preprocessing_service = MoviePreprocessingService(
        ffmpeg_service=ffmpeg_service,
        media_probe_service=probe_service,
        instrumentation=instrumentation,
    )
    resource_monitor = _ResourceMonitor(
        instrumentation,
        enabled=monitor_resources,
    )
    resource_monitor.start()
    preprocessing_started_at = time.perf_counter()
    try:
        result = preprocessing_service.preprocess(video_path, config=config)
        preprocessing_wall_seconds = time.perf_counter() - preprocessing_started_at
    finally:
        resources = resource_monitor.stop()

    if probe_service.last_media_info is None:  # pragma: no cover - service invariant
        raise RuntimeError("Preprocessing completed without media probe information")
    snapshot = instrumentation.snapshot()
    verification_started_at = time.perf_counter()
    correctness = verify_preprocessing_result(result, snapshot)
    verification_seconds = time.perf_counter() - verification_started_at
    throughput, realtime_factor = calculate_performance_rates(
        result.statistics.movie_duration_seconds,
        preprocessing_wall_seconds,
    )
    return BenchmarkRunResult(
        run_index=run_index,
        source=_source_info(
            probe_service.last_media_info,
            config.selected_video_stream_index,
        ),
        configuration=_benchmark_configuration(config),
        timings=_stage_timings(
            snapshot,
            verification_seconds,
            preprocessing_wall_seconds,
        ),
        media_throughput=throughput,
        realtime_factor=realtime_factor,
        counts=_counts(result, snapshot),
        data_volume=_data_volume(snapshot),
        resources=resources,
        correctness=correctness,
    )


class _RecordingMediaProbeService:
    def __init__(self, delegate: MediaProbeService) -> None:
        self.delegate = delegate
        self.last_media_info: MediaInfo | None = None

    def probe(self, media_path: str | Path) -> MediaInfo:
        self.last_media_info = self.delegate.probe(media_path)
        return self.last_media_info


class _ResourceMonitor:
    def __init__(
        self,
        instrumentation: PreprocessingInstrumentation,
        *,
        enabled: bool,
        sample_interval_seconds: float = 0.05,
    ) -> None:
        self.instrumentation = instrumentation
        self.sample_interval_seconds = sample_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._system_cpu: list[float] = []
        self._python_cpu: list[float] = []
        self._ffmpeg_cpu: list[float] = []
        self._tree_cpu: list[float] = []
        self._python_rss: list[int] = []
        self._ffmpeg_rss: list[int] = []
        self._children: dict[int, object] = {}
        self._process_errors: tuple[type[BaseException], ...] = (OSError,)
        self._psutil = None
        self._parent = None
        self._unavailable_reason: str | None = None

        if not enabled:
            self._unavailable_reason = (
                "resource monitoring disabled by command-line option"
            )
            return
        try:
            self._psutil = importlib.import_module("psutil")
            self._parent = self._psutil.Process()
            self._process_errors = (self._psutil.Error, OSError)
        except (ImportError, OSError) as exc:
            self._unavailable_reason = f"optional psutil monitoring unavailable: {exc}"

    def start(self) -> None:
        if self._psutil is None or self._parent is None:
            return
        self._parent.cpu_percent(interval=None)
        self._psutil.cpu_percent(interval=None)
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="preprocessing-benchmark-resources",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> BenchmarkResourceMetrics:
        if self._psutil is None or self._parent is None:
            return BenchmarkResourceMetrics(
                monitoring_available=False,
                unavailable_reason=self._unavailable_reason,
                samples=0,
                measurement_note=(
                    "Install optional benchmark dependencies to collect CPU and RSS data."
                ),
            )
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if not self._system_cpu:
            self._capture_sample()
        return BenchmarkResourceMetrics(
            monitoring_available=True,
            sample_interval_seconds=self.sample_interval_seconds,
            samples=len(self._system_cpu),
            average_system_cpu_percent=_average(self._system_cpu),
            peak_system_cpu_percent=_maximum(self._system_cpu),
            average_python_cpu_percent=_average(self._python_cpu),
            peak_python_cpu_percent=_maximum(self._python_cpu),
            average_ffmpeg_cpu_percent=_average(self._ffmpeg_cpu),
            peak_ffmpeg_cpu_percent=_maximum(self._ffmpeg_cpu),
            average_process_tree_cpu_percent=_average(self._tree_cpu),
            peak_process_tree_cpu_percent=_maximum(self._tree_cpu),
            peak_python_rss_bytes=_maximum(self._python_rss),
            peak_ffmpeg_rss_bytes=_maximum(self._ffmpeg_rss),
            measurement_note=(
                "CPU values are sampled, may exceed 100% on multicore systems, and include "
                "Python plus active FFmpeg children where separately identified."
            ),
        )

    def _sample_loop(self) -> None:
        while not self._stop_event.wait(self.sample_interval_seconds):
            self._capture_sample()

    def _capture_sample(self) -> None:
        assert self._psutil is not None
        assert self._parent is not None
        try:
            system_cpu = float(self._psutil.cpu_percent(interval=None))
            python_cpu = float(self._parent.cpu_percent(interval=None))
            python_rss = int(self._parent.memory_info().rss)
        except self._process_errors:  # pragma: no cover - platform monitor failure
            return

        ffmpeg_cpu = 0.0
        ffmpeg_rss = 0
        active_ids = set(self.instrumentation.active_process_ids())
        for process_id in active_ids:
            process = self._children.get(process_id)
            if process is None:
                try:
                    process = self._psutil.Process(process_id)
                    process.cpu_percent(interval=None)
                    self._children[process_id] = process
                except self._process_errors:
                    process = None
                if process is None:
                    continue
            try:
                ffmpeg_cpu += float(process.cpu_percent(interval=None))
                ffmpeg_rss += int(process.memory_info().rss)
            except self._process_errors:
                self._children.pop(process_id, None)

        self._system_cpu.append(system_cpu)
        self._python_cpu.append(python_cpu)
        self._ffmpeg_cpu.append(ffmpeg_cpu)
        self._tree_cpu.append(python_cpu + ffmpeg_cpu)
        self._python_rss.append(python_rss)
        self._ffmpeg_rss.append(ffmpeg_rss)


def _benchmark_configuration(config: PreprocessingConfig) -> BenchmarkConfiguration:
    return BenchmarkConfiguration(
        sampling_gap_seconds=config.max_sampling_gap_seconds,
        chunk_duration_seconds=config.chunk_duration_seconds,
        chunk_overlap_seconds=config.chunk_overlap_seconds,
        target_width=config.target_width,
        target_height=config.target_height,
        selected_video_stream_index=config.selected_video_stream_index,
        scene_threshold=config.scene_threshold,
        black_pixel_luma_threshold=config.black_pixel_luma_threshold,
        black_frame_ratio_threshold=config.black_frame_ratio_threshold,
        black_mean_luma_threshold=config.black_mean_luma_threshold,
        perceptual_hash_algorithm=config.perceptual_hash_algorithm,
        perceptual_hash_version=config.perceptual_hash_version,
        duplicate_hamming_threshold=config.duplicate_hamming_threshold,
        static_suppression_limit_seconds=config.static_suppression_limit_seconds,
    )


def _source_info(
    media_info: MediaInfo, selected_stream_index: int
) -> BenchmarkSourceInfo:
    stream = next(
        (
            item
            for item in media_info.video_streams
            if item.index == selected_stream_index
        ),
        None,
    )
    if stream is None:
        raise ValueError(f"Video stream {selected_stream_index} is unavailable")
    raw_stream = next(
        (
            item
            for item in media_info.raw.get("streams", [])
            if item.get("codec_type") == "video"
            and int(item.get("index", -1)) == selected_stream_index
        ),
        {},
    )
    nominal_fps = stream.avg_frame_rate or stream.r_frame_rate
    frame_rate_mode, evidence = _frame_rate_assessment(
        stream.avg_frame_rate,
        stream.r_frame_rate,
    )
    return BenchmarkSourceInfo(
        filename=media_info.path.name,
        path=str(media_info.path.expanduser().resolve()),
        container=media_info.format_name,
        duration_seconds=media_info.duration_seconds,
        selected_video_stream_index=selected_stream_index,
        codec=stream.codec_name,
        width=stream.width,
        height=stream.height,
        display_aspect_ratio=_display_aspect_ratio(
            raw_stream, stream.width, stream.height
        ),
        nominal_fps=nominal_fps if nominal_fps and nominal_fps > 0.0 else None,
        frame_rate_mode=frame_rate_mode,
        frame_rate_evidence=evidence,
    )


def _frame_rate_assessment(
    average_frame_rate: float | None,
    real_frame_rate: float | None,
) -> tuple[Literal["likely_cfr", "likely_vfr", "undetermined"], str]:
    if not average_frame_rate or not real_frame_rate:
        return (
            "undetermined",
            "ffprobe did not provide both avg_frame_rate and r_frame_rate",
        )
    relative_difference = abs(average_frame_rate - real_frame_rate) / max(
        average_frame_rate,
        real_frame_rate,
    )
    if relative_difference > 0.005:
        return (
            "likely_vfr",
            "avg_frame_rate and r_frame_rate differ by more than 0.5%; this is heuristic",
        )
    return (
        "likely_cfr",
        "avg_frame_rate and r_frame_rate agree within 0.5%; this is heuristic",
    )


def _display_aspect_ratio(
    raw_stream: dict,
    width: int | None,
    height: int | None,
) -> str | None:
    display_aspect_ratio = raw_stream.get("display_aspect_ratio")
    if display_aspect_ratio and display_aspect_ratio != "0:1":
        return str(display_aspect_ratio)
    if not width or not height:
        return None
    sample_aspect_ratio = _colon_fraction(raw_stream.get("sample_aspect_ratio"))
    if sample_aspect_ratio is None:
        sample_aspect_ratio = Fraction(1, 1)
    ratio = Fraction(width, height) * sample_aspect_ratio
    return f"{ratio.numerator}:{ratio.denominator}"


def _colon_fraction(value: object) -> Fraction | None:
    if not value:
        return None
    try:
        numerator, denominator = str(value).split(":", maxsplit=1)
        if int(denominator) == 0:
            return None
        return Fraction(int(numerator), int(denominator))
    except (TypeError, ValueError):
        return None


def _stage_timings(
    snapshot: InstrumentationSnapshot,
    correctness_verification_seconds: float,
    preprocessing_wall_seconds: float,
) -> BenchmarkStageTimings:
    durations = snapshot.durations
    return BenchmarkStageTimings(
        media_probe_seconds=durations.get("media_probe_seconds", 0.0),
        process_popen_seconds=durations.get("process_popen_seconds", 0.0),
        startup_seek_to_first_rgb_seconds=durations.get(
            "time_to_first_rgb_seconds", 0.0
        ),
        ffmpeg_process_lifetime_seconds=durations.get(
            "ffmpeg_process_wall_seconds",
            0.0,
        ),
        frame_stream_wait_seconds=durations.get("extractor_stream_wait_seconds", 0.0),
        frame_assembly_seconds=durations.get("frame_assembly_seconds", 0.0),
        python_frame_preparation_seconds=durations.get(
            "frame_preparation_seconds",
            0.0,
        ),
        black_filtering_seconds=durations.get("black_filter_seconds", 0.0),
        perceptual_hashing_seconds=durations.get("perceptual_hash_seconds", 0.0),
        duplicate_static_reduction_seconds=durations.get(
            "duplicate_static_reduction_seconds",
            0.0,
        ),
        result_materialization_seconds=durations.get(
            "result_materialization_seconds",
            0.0,
        ),
        python_filter_total_seconds=durations.get("python_filter_total_seconds", 0.0),
        chunk_merge_finalization_seconds=durations.get(
            "chunk_merge_finalization_seconds",
            0.0,
        ),
        total_preprocessing_wall_seconds=preprocessing_wall_seconds,
        correctness_verification_seconds=correctness_verification_seconds,
        measurement_notes=(
            (
                "FFmpeg process lifetime includes startup, seek, decode, filtering, pipe "
                "transfer, and downstream backpressure; it overlaps Python filtering."
            ),
            (
                "Frame stream wait measures main-thread waits for stdout blocks and process "
                "finish; it is not pure transfer time."
            ),
            (
                "Frame assembly includes matching each RGB frame to its concurrently drained "
                "stderr timing metadata."
            ),
            (
                "Popen timing is exact for process creation, while time-to-first-RGB also "
                "includes seek and initial decoding."
            ),
            (
                "Pure decoder compute and pipe-copy time cannot be isolated without changing "
                "the pipeline or using an external profiler."
            ),
        ),
    )


def _counts(
    result: PreprocessingResult,
    snapshot: InstrumentationSnapshot,
) -> BenchmarkCounts:
    counters = snapshot.counters
    statistics_value = result.statistics
    return BenchmarkCounts(
        chunks=statistics_value.chunks_processed,
        ffmpeg_process_launches=counters.get("ffmpeg_process_launches", 0),
        temporal_samples=statistics_value.temporal_samples,
        scene_samples=statistics_value.scene_samples,
        union_samples=statistics_value.samples_considered,
        overlap_context_samples_discarded=counters.get(
            "overlap_samples_discarded_by_ownership",
            0,
        ),
        black_frames_removed=statistics_value.black_frames_removed,
        near_duplicates_removed=statistics_value.duplicates_removed,
        static_frames_suppressed=statistics_value.static_frames_suppressed,
        representatives_retained=statistics_value.representative_frames,
    )


def _data_volume(snapshot: InstrumentationSnapshot) -> BenchmarkDataVolume:
    return BenchmarkDataVolume(
        raw_rgb_bytes_received=snapshot.counters.get("raw_rgb_bytes_received", 0),
        approximate_python_rgb_bytes_processed=snapshot.counters.get(
            "python_rgb_bytes_processed",
            0,
        ),
        peak_stdout_queue_bytes=int(snapshot.peaks.get("stdout_queue_bytes", 0)),
        peak_stdout_queue_items=int(snapshot.peaks.get("stdout_queue_items", 0)),
    )


def aggregate_benchmark_runs(
    runs: Sequence[BenchmarkRunResult],
) -> BenchmarkAggregate:
    if not runs:
        raise ValueError("at least one benchmark run is required")
    valid_runs = [run for run in runs if run.correctness.valid]
    wall_times = [run.timings.total_preprocessing_wall_seconds for run in valid_runs]
    if wall_times:
        median_wall, minimum_wall, maximum_wall = summarize_wall_times(wall_times)
        median_throughput = statistics.median(
            run.media_throughput for run in valid_runs
        )
    else:
        median_wall = minimum_wall = maximum_wall = median_throughput = None
    return BenchmarkAggregate(
        run_count=len(runs),
        valid_runs=len(valid_runs),
        invalid_runs=len(runs) - len(valid_runs),
        median_wall_seconds=median_wall,
        minimum_wall_seconds=minimum_wall,
        maximum_wall_seconds=maximum_wall,
        median_media_throughput=median_throughput,
        repeated_run_caveat=(
            "No persistent preprocessing cache is used, but later runs may benefit from the "
            "operating system filesystem cache."
        ),
    )


def _average(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _maximum(values: Sequence[float] | Sequence[int]):
    return max(values) if values else None
