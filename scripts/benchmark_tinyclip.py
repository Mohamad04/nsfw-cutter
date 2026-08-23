from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.tinyclip_benchmark import (
    CombinedSafetyTinyCLIPBenchmark,
    TinyCLIPBenchmarkResult,
    run_combined_safety_tinyclip_benchmark,
    run_tinyclip_benchmark,
)
from services.analysis.tinyclip_semantic import (
    EXPERIMENTAL_WEAPONS_DRUGS_PROMPT_BANK,
    ExperimentalPromptBank,
    TinyCLIPSemanticError,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark experimental native-Transformers TinyCLIP on CPU."
    )
    parser.add_argument(
        "--batch-sizes",
        type=_positive_int,
        nargs="+",
        default=[1, 2, 4, 8, 16],
        help="Explicit evaluation matrix; does not establish a production default",
    )
    parser.add_argument("--iterations", type=_positive_int, default=5)
    parser.add_argument("--warmup-runs", type=_nonnegative_int, default=1)
    parser.add_argument("--prompt-bank", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-memory-monitor", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--video",
        type=Path,
        help="Optional movie for a one-decode ONNX-safety + TinyCLIP benchmark",
    )
    parser.add_argument("--safety-batch-size", type=_positive_int)
    parser.add_argument("--tinyclip-batch-size", type=_positive_int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.video is not None and (
        args.safety_batch_size is None or args.tinyclip_batch_size is None
    ):
        print(
            "Combined benchmark requires --safety-batch-size and "
            "--tinyclip-batch-size.",
            file=sys.stderr,
        )
        return 2
    try:
        prompt_bank = EXPERIMENTAL_WEAPONS_DRUGS_PROMPT_BANK
        if args.prompt_bank is not None:
            payload = json.loads(args.prompt_bank.read_text(encoding="utf-8"))
            prompt_bank = ExperimentalPromptBank.model_validate(payload)
        result = run_tinyclip_benchmark(
            prompt_bank,
            args.batch_sizes,
            iterations=args.iterations,
            warmup_runs=args.warmup_runs,
            local_files_only=args.local_files_only,
            monitor_memory=not args.no_memory_monitor,
        )
        combined = None
        if args.video is not None:
            combined = run_combined_safety_tinyclip_benchmark(
                args.video,
                prompt_bank,
                safety_batch_size=args.safety_batch_size,
                tinyclip_batch_size=args.tinyclip_batch_size,
                local_files_only=args.local_files_only,
                monitor_memory=not args.no_memory_monitor,
            )
    except (
        OSError,
        json.JSONDecodeError,
        ValidationError,
        TinyCLIPSemanticError,
        ValueError,
    ) as exc:
        print(f"TinyCLIP benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("TinyCLIP benchmark cancelled.", file=sys.stderr)
        return 130

    _print_result(result, combined)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "isolated": result.model_dump(mode="json"),
            "combined": (
                combined.model_dump(mode="json") if combined is not None else None
            ),
        }
        args.json_output.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON: {args.json_output.resolve()}")
    valid = all(case.successful for case in result.cases)
    if combined is not None:
        valid = valid and not combined.failures
    return 0 if valid else 2


def _print_result(
    result: TinyCLIPBenchmarkResult,
    combined: CombinedSafetyTinyCLIPBenchmark | None,
) -> None:
    print("Experimental TinyCLIP CPU Benchmark")
    print("=" * 36)
    print(f"Model: {result.model.repository_id}@{result.model.revision}")
    print(f"Artifact resolution: {result.artifact_resolution_seconds:.3f} s")
    print(f"Processor setup:     {result.processor_setup_seconds:.3f} s")
    print(f"Weights load:        {result.weights_load_seconds:.3f} s")
    print(f"Runtime validation:  {result.runtime_validation_seconds:.3f} s")
    print(f"Text tokenization:   {result.text_tokenization_seconds:.6f} s")
    print(f"Text embedding:      {result.text_embedding_seconds:.6f} s")
    print("\nBatch results:")
    for case in result.cases:
        if not case.successful:
            print(f"  batch={case.batch_size:<3} FAILED {case.failure}")
            continue
        peak = case.memory.peak_process_tree_rss_delta_bytes
        peak_text = "n/a" if peak is None else f"{peak / (1024 * 1024):.1f} MiB"
        print(
            f"  batch={case.batch_size:<3} "
            f"encoder={case.image_encoder_frames_per_second:>7.2f} frames/s "
            f"end-to-end={case.end_to_end_frames_per_second:>7.2f} frames/s "
            f"latency={case.mean_batch_latency_ms:>8.2f} ms "
            f"peak-delta={peak_text}"
        )
    print("\nProduction use: NOT LICENSE-CLEARED")
    if combined is not None:
        print("\nOne-decode ONNX safety + TinyCLIP:")
        print(f"  media throughput: {combined.media_throughput:.2f}x")
        print(f"  representatives:  {combined.representatives}")
        print(f"  ONNX time:         {combined.onnx_inference_seconds:.3f} s")
        print(
            f"  TinyCLIP encoder:  "
            f"{combined.tinyclip_image_encoder_seconds:.3f} s"
        )
        print(
            f"  batch calls:       safety={combined.safety_batch_count}, "
            f"TinyCLIP={combined.tinyclip_batch_count}"
        )
        print(f"  failures:          {len(combined.failures)}")


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


if __name__ == "__main__":
    raise SystemExit(main())
