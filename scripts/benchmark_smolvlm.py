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

from services.analysis.smolvlm_benchmark import run_smolvlm_benchmark
from services.analysis.smolvlm_verifier import SmolVLMError


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the isolated experimental SmolVLM2 verifier using only "
            "deterministic in-memory RGB images."
        )
    )
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Explicit device; no automatic placement is used",
    )
    parser.add_argument(
        "--image-counts",
        nargs="+",
        type=_image_count,
        default=[1, 3, 6],
    )
    parser.add_argument(
        "--max-new-tokens",
        nargs="+",
        type=_positive_int,
        default=[32, 64, 96],
    )
    parser.add_argument(
        "--split-modes",
        nargs="+",
        choices=("default", "disabled"),
        default=["default", "disabled"],
        help="Official default image splitting and/or official split-disabled mode",
    )
    parser.add_argument("--warmup-runs", type=_nonnegative_int, default=1)
    parser.add_argument("--iterations", type=_positive_int, default=2)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-memory-monitor", action="store_true")
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    split_modes = tuple(mode == "default" for mode in args.split_modes)
    try:
        report = run_smolvlm_benchmark(
            image_counts=args.image_counts,
            max_new_tokens_values=args.max_new_tokens,
            split_modes=split_modes,
            warmup_runs=args.warmup_runs,
            measured_iterations=args.iterations,
            local_files_only=args.local_files_only,
            device=args.device,
            monitor_memory=not args.no_memory_monitor,
        )
    except (OSError, SmolVLMError, ValueError, RuntimeError) as exc:
        print(f"SmolVLM benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SmolVLM benchmark cancelled.", file=sys.stderr)
        return 130

    _print_report(report)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON: {args.json_output.resolve()}")
    return 0


def _print_report(report: object) -> None:
    print("Experimental SmolVLM2 Isolated Benchmark")
    print("=" * 41)
    print(f"Device:              {report.device}")
    print(f"Artifact resolution: {report.artifact_resolution_seconds:.3f} s")
    print(f"Model load:          {report.model_load_seconds:.3f} s")
    print(
        "Split control:       "
        f"{'available' if report.image_splitting_control_supported else 'unavailable'}"
    )
    print("\nimages split max_tokens blocks visual_tokens input_len gen_s total_s JSON")
    for case in report.cases:
        print(
            f"{case.image_count:>6} "
            f"{'on' if case.image_splitting else 'off':>5} "
            f"{case.max_new_tokens:>10} "
            f"{case.visual_blocks:>6} "
            f"{case.visual_tokens:>13} "
            f"{case.input_sequence_length:>9} "
            f"{case.mean_generation_seconds:>5.2f} "
            f"{case.mean_total_seconds:>7.2f} "
            f"{case.strict_json_successes}/{case.measured_iterations}"
        )
    print("\nExperimental isolated benchmark only; no production policy is selected.")


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


def _image_count(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 6:
        raise argparse.ArgumentTypeError("image count must be between 1 and 6")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
