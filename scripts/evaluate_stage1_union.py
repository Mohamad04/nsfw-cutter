from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.analysis.stage1_evaluation import Stage1EvaluationDataError, write_json_artifact
from services.analysis.stage1_union_evaluation import (
    Stage1UnionEvaluationConfiguration,
    Stage1UnionEvaluationError,
    evaluate_union_artifacts,
    load_union_inputs,
    write_union_policy_csv,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate exported ONNX and TinyCLIP scores offline; no movie, model, "
            "FFmpeg, ONNX Runtime, or Torch inference is loaded."
        )
    )
    parser.add_argument("--safety-scores", type=Path, required=True)
    parser.add_argument("--semantic-scores", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--prompt-bank", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--threshold-count", type=_threshold_count, default=7)
    parser.add_argument("--timestamp-tolerance-us", type=_nonnegative_int, default=0)
    parser.add_argument("--tolerance-seconds", type=_nonnegative_float, default=5.0)
    parser.add_argument(
        "--context-seconds",
        type=_nonnegative_float,
        nargs="+",
        default=[0.0, 1.0, 2.0, 5.0],
    )
    parser.add_argument(
        "--merge-gap-seconds",
        type=_nonnegative_float,
        nargs="+",
        default=[0.0, 1.0, 2.0],
    )
    parser.add_argument("--frames-per-region", type=_positive_int, default=6)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    config = Stage1UnionEvaluationConfiguration(
        timestamp_tolerance_us=args.timestamp_tolerance_us,
        semantic_threshold_count=args.threshold_count,
        tolerance_seconds=args.tolerance_seconds,
        context_seconds=tuple(args.context_seconds),
        merge_gap_seconds=tuple(args.merge_gap_seconds),
        frames_per_region=args.frames_per_region,
    )
    try:
        safety, semantic, ground_truth, prompt_bank, _aligned = load_union_inputs(
            args.safety_scores,
            args.semantic_scores,
            args.ground_truth,
            args.prompt_bank,
            config,
        )
        report = evaluate_union_artifacts(
            safety,
            semantic,
            ground_truth,
            prompt_bank,
            config,
        )
        json_output = write_json_artifact(report, args.json_output)
        csv_output = (
            write_union_policy_csv(report, args.csv_output)
            if args.csv_output is not None
            else None
        )
    except (
        FileNotFoundError,
        OSError,
        Stage1EvaluationDataError,
        Stage1UnionEvaluationError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Offline union evaluation failed: {exc}", file=sys.stderr)
        return 2

    _print_summary(report)
    print(f"\nJSON: {json_output}")
    if csv_output is not None:
        print(f"CSV:  {csv_output}")
    return 0


def _print_summary(report) -> None:
    print("Stage-1 ONNX + TinyCLIP Offline Union Evaluation")
    print("=" * 49)
    print(f"Video: {report.video.filename}")
    print(f"Representatives: {report.alignment.aligned_sample_count}")
    print(f"Ground-truth intervals: {report.ground_truth_total_intervals}")
    print(f"Semantic policies: {len(report.semantic_policies)}")
    print(f"Union policies: {len(report.union_policies)}")
    print(f"Highest exact union recall: {report.highest_exact_recall}")
    print(f"Exact-recall=1.0 policies: {len(report.exact_recall_pareto)}")
    if report.exact_recall_pareto:
        best = report.exact_recall_pareto[0]
        print(
            "Best measured evaluation policy: "
            f"ONNX {best.onnx_baseline}, {best.semantic_strategy}, "
            f"candidate rate={best.candidate_sample_rate:.4f}"
        )
    print("Thresholds and prompt bank remain evaluation-only; no production policy was selected.")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _threshold_count(value: str) -> int:
    parsed = _positive_int(value)
    if parsed < 2 or parsed > 64:
        raise argparse.ArgumentTypeError("threshold count must be between 2 and 64")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
