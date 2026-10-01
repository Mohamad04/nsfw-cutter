from __future__ import annotations

import importlib
import json
import statistics
import threading
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.analysis.smolvlm_verifier import (
    SmolVLMRuntime,
    SmolVLMVerifier,
    VerificationStatus,
    VLMVerificationRequest,
    synthetic_verification_request,
)


class SmolVLMBenchmarkIteration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    processor_seconds: float = Field(ge=0.0)
    chat_template_seconds: float = Field(ge=0.0)
    generation_seconds: float = Field(ge=0.0)
    total_seconds: float = Field(ge=0.0)
    generated_tokens: int = Field(ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0.0)
    visual_blocks: int = Field(gt=0)
    visual_tokens: int = Field(gt=0)
    input_sequence_length: int = Field(gt=0)
    valid_json: bool
    pydantic_valid_json: bool
    status: VerificationStatus
    error: str | None
    peak_rss_bytes: int | None = Field(default=None, ge=0)
    rss_delta_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_allocated_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_reserved_bytes: int | None = Field(default=None, ge=0)


class SmolVLMBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image_count: int = Field(gt=0)
    max_new_tokens: int = Field(gt=0)
    image_splitting: bool
    warmup_runs: int = Field(ge=0)
    measured_iterations: int = Field(gt=0)
    mean_processor_seconds: float = Field(ge=0.0)
    mean_generation_seconds: float = Field(ge=0.0)
    median_generation_seconds: float = Field(ge=0.0)
    mean_total_seconds: float = Field(ge=0.0)
    mean_generated_tokens: float = Field(ge=0.0)
    mean_tokens_per_second: float | None = Field(default=None, ge=0.0)
    visual_blocks: int = Field(gt=0)
    visual_tokens: int = Field(gt=0)
    input_sequence_length: int = Field(gt=0)
    strict_json_successes: int = Field(ge=0)
    strict_json_success_rate: float = Field(ge=0.0, le=1.0)
    unverified_count: int = Field(ge=0)
    peak_rss_bytes: int | None = Field(default=None, ge=0)
    peak_rss_delta_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_allocated_bytes: int | None = Field(default=None, ge=0)
    peak_cuda_reserved_bytes: int | None = Field(default=None, ge=0)
    iterations: tuple[SmolVLMBenchmarkIteration, ...]


class SmolVLMBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    device: Literal["cpu", "cuda"]
    artifact_resolution_seconds: float = Field(ge=0.0)
    model_load_seconds: float = Field(ge=0.0)
    model_load_rss_delta_bytes: int | None
    model_load_cuda_allocated_bytes: int | None
    image_splitting_control_supported: bool
    provenance: dict[str, object]
    cases: tuple[SmolVLMBenchmarkCase, ...]
    measurement_notes: tuple[str, ...]


def run_smolvlm_benchmark(
    *,
    image_counts: Iterable[int],
    max_new_tokens_values: Iterable[int],
    split_modes: Iterable[bool],
    warmup_runs: int,
    measured_iterations: int,
    local_files_only: bool,
    device: Literal["cpu", "cuda"],
    monitor_memory: bool = True,
    verifier: SmolVLMVerifier | None = None,
) -> SmolVLMBenchmarkReport:
    if warmup_runs < 0 or measured_iterations <= 0:
        raise ValueError("warmup runs must be nonnegative and iterations positive")
    counts = tuple(image_counts)
    token_limits = tuple(max_new_tokens_values)
    modes = tuple(split_modes)
    if not counts or any(not 1 <= count <= 6 for count in counts):
        raise ValueError("image counts must be between 1 and 6")
    if not token_limits or any(limit <= 0 for limit in token_limits):
        raise ValueError("max_new_tokens values must be positive")
    if not modes:
        raise ValueError("at least one image-splitting mode is required")

    active_verifier = verifier or SmolVLMVerifier(
        local_files_only=local_files_only,
        device=device,
    )
    process = _optional_process() if monitor_memory else None
    load_rss_before = _rss(process)
    runtime = active_verifier.runtime()
    load_rss_after = _rss(process)
    load_rss_delta = (
        max(0, load_rss_after - load_rss_before)
        if load_rss_before is not None and load_rss_after is not None
        else None
    )
    load_cuda = _cuda_allocated(runtime) if device == "cuda" else None

    cases: list[SmolVLMBenchmarkCase] = []
    for image_splitting in modes:
        if not image_splitting and not runtime.image_splitting_supported:
            continue
        for image_count in counts:
            for max_new_tokens in token_limits:
                request = synthetic_verification_request(image_count)
                for _ in range(warmup_runs):
                    runtime.verify(
                        request,
                        max_new_tokens=max_new_tokens,
                        image_splitting=image_splitting,
                    )
                measurements = tuple(
                    _measure_iteration(
                        runtime,
                        request,
                        max_new_tokens=max_new_tokens,
                        image_splitting=image_splitting,
                        process=process,
                    )
                    for _ in range(measured_iterations)
                )
                cases.append(
                    summarize_benchmark_case(
                        image_count=image_count,
                        max_new_tokens=max_new_tokens,
                        image_splitting=image_splitting,
                        warmup_runs=warmup_runs,
                        measurements=measurements,
                    )
                )
    return SmolVLMBenchmarkReport(
        device=device,
        artifact_resolution_seconds=active_verifier.artifact_resolution_seconds,
        model_load_seconds=active_verifier.model_load_seconds,
        model_load_rss_delta_bytes=load_rss_delta,
        model_load_cuda_allocated_bytes=load_cuda,
        image_splitting_control_supported=runtime.image_splitting_supported,
        provenance=runtime.provenance.model_dump(mode="json"),
        cases=tuple(cases),
        measurement_notes=(
            "Synthetic inputs are deterministic 384x384 RGB images; no movie is opened.",
            "RSS is sampled and can miss allocations shorter than the sampling interval.",
            "Strict JSON success means the output passed both JSON and policy-aware Pydantic validation.",
            "CUDA timings synchronize before and after generation when device=cuda.",
        ),
    )


def summarize_benchmark_case(
    *,
    image_count: int,
    max_new_tokens: int,
    image_splitting: bool,
    warmup_runs: int,
    measurements: tuple[SmolVLMBenchmarkIteration, ...],
) -> SmolVLMBenchmarkCase:
    if not measurements:
        raise ValueError("benchmark case requires at least one measurement")
    first = measurements[0]
    for measurement in measurements[1:]:
        if (
            measurement.visual_blocks != first.visual_blocks
            or measurement.visual_tokens != first.visual_tokens
            or measurement.input_sequence_length != first.input_sequence_length
        ):
            raise ValueError("processor expansion changed within one benchmark case")
    rates = [
        measurement.tokens_per_second
        for measurement in measurements
        if measurement.tokens_per_second is not None
    ]
    json_successes = sum(
        measurement.pydantic_valid_json for measurement in measurements
    )
    return SmolVLMBenchmarkCase(
        image_count=image_count,
        max_new_tokens=max_new_tokens,
        image_splitting=image_splitting,
        warmup_runs=warmup_runs,
        measured_iterations=len(measurements),
        mean_processor_seconds=statistics.fmean(
            measurement.processor_seconds for measurement in measurements
        ),
        mean_generation_seconds=statistics.fmean(
            measurement.generation_seconds for measurement in measurements
        ),
        median_generation_seconds=statistics.median(
            measurement.generation_seconds for measurement in measurements
        ),
        mean_total_seconds=statistics.fmean(
            measurement.total_seconds for measurement in measurements
        ),
        mean_generated_tokens=statistics.fmean(
            measurement.generated_tokens for measurement in measurements
        ),
        mean_tokens_per_second=statistics.fmean(rates) if rates else None,
        visual_blocks=first.visual_blocks,
        visual_tokens=first.visual_tokens,
        input_sequence_length=first.input_sequence_length,
        strict_json_successes=json_successes,
        strict_json_success_rate=json_successes / len(measurements),
        unverified_count=sum(
            measurement.status == VerificationStatus.UNVERIFIED
            for measurement in measurements
        ),
        peak_rss_bytes=_max_optional(
            measurement.peak_rss_bytes for measurement in measurements
        ),
        peak_rss_delta_bytes=_max_optional(
            measurement.rss_delta_bytes for measurement in measurements
        ),
        peak_cuda_allocated_bytes=_max_optional(
            measurement.peak_cuda_allocated_bytes for measurement in measurements
        ),
        peak_cuda_reserved_bytes=_max_optional(
            measurement.peak_cuda_reserved_bytes for measurement in measurements
        ),
        iterations=measurements,
    )


def _measure_iteration(
    runtime: SmolVLMRuntime,
    request: VLMVerificationRequest,
    *,
    max_new_tokens: int,
    image_splitting: bool,
    process: object | None,
) -> SmolVLMBenchmarkIteration:
    monitor = _RSSMonitor(process)
    monitor.start()
    if runtime.provenance.device == "cuda":
        runtime.torch.cuda.reset_peak_memory_stats()
    result = runtime.verify(
        request,
        max_new_tokens=max_new_tokens,
        image_splitting=image_splitting,
    )
    peak_rss, rss_delta = monitor.stop()
    if result.expansion is None:
        raise RuntimeError(f"benchmark request was not processed: {result.error}")
    cuda_allocated = (
        int(runtime.torch.cuda.max_memory_allocated())
        if runtime.provenance.device == "cuda"
        else None
    )
    cuda_reserved = (
        int(runtime.torch.cuda.max_memory_reserved())
        if runtime.provenance.device == "cuda"
        else None
    )
    return SmolVLMBenchmarkIteration(
        processor_seconds=result.processor_seconds,
        chat_template_seconds=result.chat_template_seconds,
        generation_seconds=result.generation_seconds,
        total_seconds=result.total_seconds,
        generated_tokens=result.generated_token_count,
        tokens_per_second=result.tokens_per_second,
        visual_blocks=result.expansion.visual_block_count,
        visual_tokens=result.expansion.visual_token_count,
        input_sequence_length=result.expansion.input_sequence_length,
        valid_json=_is_single_json_object(result.raw_generated_text),
        pydantic_valid_json=result.payload is not None,
        status=result.status,
        error=result.error,
        peak_rss_bytes=peak_rss,
        rss_delta_bytes=rss_delta,
        peak_cuda_allocated_bytes=cuda_allocated,
        peak_cuda_reserved_bytes=cuda_reserved,
    )


class _RSSMonitor:
    def __init__(self, process: object | None, interval_seconds: float = 0.05) -> None:
        self.process = process
        self.interval_seconds = interval_seconds
        self._values: list[int] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.capture()
        if self.process is not None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self) -> tuple[int | None, int | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.capture()
        if not self._values:
            return None, None
        return max(self._values), max(0, max(self._values) - self._values[0])

    def capture(self) -> None:
        value = _rss(self.process)
        if value is not None:
            self._values.append(value)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.capture()


def _optional_process() -> object | None:
    try:
        psutil = importlib.import_module("psutil")
        return psutil.Process()
    except (ImportError, OSError):
        return None


def _rss(process: object | None) -> int | None:
    if process is None:
        return None
    try:
        return int(process.memory_info().rss)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None


def _cuda_allocated(runtime: SmolVLMRuntime) -> int | None:
    try:
        return int(runtime.torch.cuda.memory_allocated())
    except (AttributeError, RuntimeError):
        return None


def _max_optional(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _is_single_json_object(raw_text: str) -> bool:
    try:
        value = json.loads(raw_text.strip())
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(value, dict)
