from __future__ import annotations

# The project root must precede application imports for direct script execution.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_benchmark import (
    Stage1ThroughputBenchmarkResult,
    run_stage1_throughput_benchmark,
)
from services.analysis.stage1_safety import Stage1SafetyError


def build_argument_parser() -> argparse.ArgumentParser:
    defaults = PreprocessingConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark CPU Stage-1 ONNX batching in isolation and with movie preprocessing."
        )
    )
    parser.add_argument("--video", type=Path, required=True, help="MP4 or MKV input path")
    parser.add_argument(
        "--batch-sizes",
        type=_positive_int,
        nargs="+",
        required=True,
        help="Explicit batch-size matrix; no production default is implied",
    )
    parser.add_argument(
        "--isolated-iterations",
        type=_positive_int,
        default=10,
        help="Measured ONNX calls per batch size",
    )
    parser.add_argument(
        "--warmup-runs",
        type=_nonnegative_int,
        default=2,
        help="Unmeasured ONNX warm-up calls per isolated case",
    )
    parser.add_argument(
        "--sampling-gap",
        type=_positive_float,
        default=defaults.max_sampling_gap_seconds,
        help="Maximum temporal safety gap in seconds",
    )
    parser.add_argument(
        "--chunk-duration",
        type=_positive_float,
        default=defaults.chunk_duration_seconds,
        help="Logical preprocessing chunk duration in seconds",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=_nonnegative_float,
        default=defaults.chunk_overlap_seconds,
        help="Total preprocessing chunk overlap in seconds",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Require the pinned artifact to already exist in the application cache",
    )
    parser.add_argument(
        "--no-memory-monitor",
        action="store_true",
        help="Disable optional psutil RSS sampling",
    )
    parser.add_argument("--json-output", type=Path, help="Optional JSON result path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if (
        args.json_output is not None
        and args.json_output.expanduser().resolve() == args.video.expanduser().resolve()
    ):
        print("Benchmark failed: JSON output must not overwrite the video", file=sys.stderr)
        return 2
    config = PreprocessingConfig(
        max_sampling_gap_seconds=args.sampling_gap,
        chunk_duration_seconds=args.chunk_duration,
        chunk_overlap_seconds=args.chunk_overlap,
    )
    try:
        result = run_stage1_throughput_benchmark(
            args.video,
            args.batch_sizes,
            config=config,
            isolated_iterations=args.isolated_iterations,
            warmup_runs=args.warmup_runs,
            monitor_memory=not args.no_memory_monitor,
            local_files_only=args.local_files_only,
        )
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        Stage1SafetyError,
        ValueError,
        ValidationError,
    ) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Benchmark cancelled by user.", file=sys.stderr)
        return 130

    _print_result(result)
    if args.json_output is not None:
        try:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"Unable to write JSON output: {exc}", file=sys.stderr)
            return 2
        print(f"\nJSON: {args.json_output.resolve()}")
    return 0 if result.valid else 2


def _print_result(result: Stage1ThroughputBenchmarkResult) -> None:
    print("Stage-1 CPU Throughput Benchmark")
    print("=" * 32)
    print(f"Model: {result.model.repository_id}@{result.model.revision}")
    print(f"SHA-256: {result.model.artifact_sha256}")
    print(
        f"Runtime: ONNX Runtime {result.model.onnxruntime_version}; "
        f"providers={list(result.model.execution_providers)}"
    )
    print("\nIsolated session.run (prebuilt tensors):")
    for case in result.isolated_inference:
        print(
            f"  batch={case.batch_size:<4} "
            f"frames/s={case.frames_per_onnx_second:>9.2f} "
            f"call={case.mean_onnx_call_milliseconds:>8.3f} ms "
            f"frame={case.mean_onnx_frame_milliseconds:>8.3f} ms "
            f"peak-delta={_format_optional_bytes(case.memory.peak_process_tree_rss_delta_bytes)}"
        )
    print("\nPreprocessing + Stage 1:")
    for case in result.preprocessing_plus_stage1:
        status = "VALID" if case.valid else "INVALID"
        print(
            f"  batch={case.batch_size:<4} "
            f"media={case.media_throughput:>7.2f}x "
            f"representatives/s={case.representative_frames_per_second:>8.2f} "
            f"batches={case.inference_batch_count:<4} "
            f"full={case.full_batch_count:<4} "
            f"partial={case.partial_batch_count:<2} "
            f"occupancy={case.average_batch_occupancy:>6.1%} "
            f"final={case.final_batch_size!s:<4} "
            f"peak-delta={_format_optional_bytes(case.memory.peak_process_tree_rss_delta_bytes)} "
            f"{status}"
        )
    print("\nNotes:")
    for note in result.notes:
        print(f"  - {note}")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _format_optional_bytes(value: int | None) -> str:
    if value is None:
        return "unavailable"
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024.0 or unit == "GiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
