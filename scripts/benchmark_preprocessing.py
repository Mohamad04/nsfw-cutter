from __future__ import annotations

# The project root must be inserted before application imports when this file is
# executed directly from the scripts directory.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from itertools import product
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.preprocessing_benchmark import (
    BenchmarkCaseResult,
    BenchmarkRunResult,
    BenchmarkSuiteResult,
    run_benchmark_suite,
)
from services.analysis.preprocessing_contracts import PreprocessingConfig


def build_argument_parser() -> argparse.ArgumentParser:
    defaults = PreprocessingConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the production Phase 1 preprocessing pipeline without AI inference."
        )
    )
    parser.add_argument(
        "--video", type=Path, required=True, help="MP4 or MKV input path"
    )
    parser.add_argument(
        "--sampling-gap",
        type=_positive_float,
        default=defaults.max_sampling_gap_seconds,
        help="Maximum temporal safety gap in seconds",
    )
    parser.add_argument(
        "--sampling-gap-matrix",
        type=_positive_float,
        nargs="+",
        help="Run one case for each listed temporal sampling gap",
    )
    parser.add_argument(
        "--chunk-duration",
        type=_positive_float,
        default=defaults.chunk_duration_seconds,
        help="Logical chunk core duration in seconds",
    )
    parser.add_argument(
        "--chunk-duration-matrix",
        type=_positive_float,
        nargs="+",
        help="Run one case for each listed logical chunk duration",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=_nonnegative_float,
        default=defaults.chunk_overlap_seconds,
        help="Total logical chunk overlap/context in seconds",
    )
    parser.add_argument(
        "--target-width",
        type=_positive_int,
        default=defaults.target_width,
        help="Padded inference canvas width",
    )
    parser.add_argument(
        "--target-height",
        type=_positive_int,
        default=defaults.target_height,
        help="Padded inference canvas height",
    )
    parser.add_argument(
        "--runs",
        type=_positive_int,
        default=1,
        help="Number of repeated preprocessing runs per configuration",
    )
    parser.add_argument("--json-output", type=Path, help="Optional JSON result path")
    parser.add_argument(
        "--video-stream-index",
        type=_nonnegative_int,
        default=defaults.selected_video_stream_index,
        help="Global FFmpeg video stream index",
    )
    parser.add_argument(
        "--scene-threshold",
        type=_unit_float,
        default=defaults.scene_threshold,
        help="FFmpeg scene score threshold",
    )
    parser.add_argument(
        "--duplicate-threshold",
        type=_nonnegative_int,
        default=defaults.duplicate_hamming_threshold,
        help="Maximum dHash Hamming distance for a near-match",
    )
    parser.add_argument(
        "--static-suppression-limit",
        type=_positive_float,
        default=defaults.static_suppression_limit_seconds,
        help="Maximum seconds represented by one static representative",
    )
    parser.add_argument(
        "--no-resource-monitor",
        action="store_true",
        help="Disable optional psutil CPU/RSS sampling",
    )
    return parser


def configurations_from_args(
    args: argparse.Namespace,
) -> tuple[PreprocessingConfig, ...]:
    sampling_gaps = _unique(args.sampling_gap_matrix or [args.sampling_gap])
    chunk_durations = _unique(args.chunk_duration_matrix or [args.chunk_duration])
    return tuple(
        PreprocessingConfig(
            chunk_duration_seconds=chunk_duration,
            chunk_overlap_seconds=args.chunk_overlap,
            max_sampling_gap_seconds=sampling_gap,
            selected_video_stream_index=args.video_stream_index,
            scene_threshold=args.scene_threshold,
            target_width=args.target_width,
            target_height=args.target_height,
            duplicate_hamming_threshold=args.duplicate_threshold,
            static_suppression_limit_seconds=args.static_suppression_limit,
        )
        for sampling_gap, chunk_duration in product(sampling_gaps, chunk_durations)
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if (
        args.json_output is not None
        and args.json_output.expanduser().resolve() == args.video.expanduser().resolve()
    ):
        print(
            "Benchmark failed: JSON output must not overwrite the source video",
            file=sys.stderr,
        )
        return 2
    try:
        configurations = configurations_from_args(args)
        suite = run_benchmark_suite(
            args.video,
            configurations,
            runs=args.runs,
            monitor_resources=not args.no_resource_monitor,
        )
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        ValueError,
        ValidationError,
    ) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Benchmark cancelled by user.", file=sys.stderr)
        return 130

    _print_suite(suite)
    if args.json_output is not None:
        try:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                suite.model_dump_json(indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"Unable to write JSON output: {exc}", file=sys.stderr)
            return 2
        print(f"\nJSON: {args.json_output.resolve()}")
    return 0 if suite.valid else 2


def _print_suite(suite: BenchmarkSuiteResult) -> None:
    print("Preprocessing Benchmark")
    print("-" * 23)
    for case_index, case in enumerate(suite.cases, start=1):
        if len(suite.cases) > 1:
            print(f"\nCase {case_index}/{len(suite.cases)}")
        for run in case.runs:
            _print_run(run, len(case.runs))
        _print_aggregate(case)
    print("\nNotes:")
    for note in suite.notes:
        print(f"  - {note}")


def _print_run(run: BenchmarkRunResult, run_count: int) -> None:
    source = run.source
    config = run.configuration
    timings = run.timings
    counts = run.counts
    volume = run.data_volume
    resources = run.resources
    print(f"\nRun {run.run_index}/{run_count}")
    print("\nVideo:")
    print(f"  File:              {source.filename}")
    print(f"  Container:         {_display(source.container)}")
    print(f"  Duration:          {_format_duration(source.duration_seconds)}")
    print(f"  Video stream:      {source.selected_video_stream_index}")
    print(f"  Codec:             {_display(source.codec)}")
    print(f"  Resolution:        {_resolution(source.width, source.height)}")
    print(f"  Display aspect:    {_display(source.display_aspect_ratio)}")
    print(f"  Nominal FPS:       {_number(source.nominal_fps)}")
    print(
        f"  CFR/VFR estimate:  {source.frame_rate_mode} ({source.frame_rate_evidence})"
    )

    print("\nConfiguration:")
    print(f"  Sampling gap:      {config.sampling_gap_seconds:.3f} s")
    print(f"  Chunk duration:    {config.chunk_duration_seconds:.3f} s")
    print(f"  Chunk overlap:     {config.chunk_overlap_seconds:.3f} s")
    print(f"  Canvas:            {config.target_width}x{config.target_height}")
    print(f"  Execution:         {config.physical_execution_mode}")
    print(f"  Scene threshold:   {config.scene_threshold:.3f}")
    print(
        "  Black filter:      "
        f"pixel <= {config.black_pixel_luma_threshold}, "
        f"ratio >= {config.black_frame_ratio_threshold:.4f}, "
        f"mean <= {config.black_mean_luma_threshold:.2f}"
    )
    print(
        "  Duplicate filter: "
        f"{config.perceptual_hash_algorithm} v{config.perceptual_hash_version}, "
        f"Hamming <= {config.duplicate_hamming_threshold}"
    )
    print(f"  Static limit:      {config.static_suppression_limit_seconds:.3f} s")

    print("\nPerformance:")
    print(
        "  Wall time:         "
        f"{_format_duration(timings.total_preprocessing_wall_seconds)}"
    )
    print(f"  Throughput:        {run.media_throughput:.3f}x")
    print(f"  Realtime factor:   {run.realtime_factor:.6f}")

    print("\nTiming detail:")
    print(f"  Media probe:       {timings.media_probe_seconds:.6f} s")
    print(f"  Popen calls:       {timings.process_popen_seconds:.6f} s")
    print(
        f"  First-RGB latency: {timings.startup_seek_to_first_rgb_seconds:.6f} s total"
    )
    print(
        "  FFmpeg lifetime:   "
        f"{timings.ffmpeg_process_lifetime_seconds:.6f} s (overlaps Python)"
    )
    print(f"  Stream wait:       {timings.frame_stream_wait_seconds:.6f} s")
    print(f"  Frame assembly:    {timings.frame_assembly_seconds:.6f} s")
    print(f"  Python filtering:  {timings.python_filter_total_seconds:.6f} s")
    print(f"    frame prep:      {timings.python_frame_preparation_seconds:.6f} s")
    print(f"    black filter:    {timings.black_filtering_seconds:.6f} s")
    print(f"    perceptual hash: {timings.perceptual_hashing_seconds:.6f} s")
    print(f"    static/dedup:    {timings.duplicate_static_reduction_seconds:.6f} s")
    print(f"  Merge/finalize:    {timings.chunk_merge_finalization_seconds:.6f} s")

    print("\nSamples:")
    print(f"  Chunks:            {counts.chunks}")
    print(f"  FFmpeg launches:   {counts.ffmpeg_process_launches}")
    print(f"  Temporal:          {counts.temporal_samples}")
    print(f"  Scene:             {counts.scene_samples}")
    print(f"  Union:             {counts.union_samples}")
    print(f"  Overlap discarded: {counts.overlap_context_samples_discarded}")
    print(f"  Black removed:     {counts.black_frames_removed}")
    print(f"  Near duplicates:   {counts.near_duplicates_removed}")
    print(f"  Static suppressed: {counts.static_frames_suppressed}")
    print(f"  Representatives:   {counts.representatives_retained}")

    print("\nData volume:")
    print(f"  FFmpeg RGB:        {_format_bytes(volume.raw_rgb_bytes_received)}")
    print(
        "  Python RGB:        "
        f"{_format_bytes(volume.approximate_python_rgb_bytes_processed)}"
    )
    print(
        "  Peak stdout queue: "
        f"{_format_bytes(volume.peak_stdout_queue_bytes)} "
        f"({volume.peak_stdout_queue_items} blocks)"
    )

    print("\nResources:")
    if resources.monitoring_available:
        print(
            "  Process-tree CPU:  "
            f"avg {_number(resources.average_process_tree_cpu_percent)}%, "
            f"peak {_number(resources.peak_process_tree_cpu_percent)}%"
        )
        print(
            "  System CPU:        "
            f"avg {_number(resources.average_system_cpu_percent)}%, "
            f"peak {_number(resources.peak_system_cpu_percent)}%"
        )
        print(
            f"  Peak Python RSS:   {_format_optional_bytes(resources.peak_python_rss_bytes)}"
        )
        print(
            f"  Peak FFmpeg RSS:   {_format_optional_bytes(resources.peak_ffmpeg_rss_bytes)}"
        )
    else:
        print(f"  Unavailable:       {resources.unavailable_reason}")

    status = "VALID" if run.correctness.valid else "INVALID"
    print(f"\nCorrectness:         {status}")
    for check in run.correctness.checks:
        marker = "PASS" if check.passed else "FAIL"
        print(f"  [{marker}] {check.name}: {check.detail}")


def _print_aggregate(case: BenchmarkCaseResult) -> None:
    aggregate = case.aggregate
    if aggregate.run_count <= 1:
        return
    print("\nRepeated-run summary:")
    print(f"  Valid/invalid:     {aggregate.valid_runs}/{aggregate.invalid_runs}")
    print(
        f"  Median wall:       {_format_optional_duration(aggregate.median_wall_seconds)}"
    )
    print(
        f"  Minimum wall:      {_format_optional_duration(aggregate.minimum_wall_seconds)}"
    )
    print(
        f"  Maximum wall:      {_format_optional_duration(aggregate.maximum_wall_seconds)}"
    )
    print(f"  Median throughput: {_number(aggregate.median_media_throughput)}x")
    print(f"  Caveat:            {aggregate.repeated_run_caveat}")


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


def _unit_float(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return parsed


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


def _unique(values: list[float]) -> tuple[float, ...]:
    return tuple(dict.fromkeys(values))


def _display(value: object | None) -> str:
    return str(value) if value not in (None, "") else "unknown"


def _number(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "unavailable"


def _resolution(width: int | None, height: int | None) -> str:
    return f"{width}x{height}" if width and height else "unknown"


def _format_duration(seconds: float) -> str:
    total_milliseconds = round(seconds * 1_000)
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _format_optional_duration(seconds: float | None) -> str:
    return _format_duration(seconds) if seconds is not None else "unavailable"


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    unit = units[0]
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            break
        amount /= 1024.0
    return f"{amount:.2f} {unit} ({value} bytes)"


def _format_optional_bytes(value: int | None) -> str:
    return _format_bytes(value) if value is not None else "unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
