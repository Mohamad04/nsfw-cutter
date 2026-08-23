from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.stage1_evaluation import (
    Stage1EvaluationConfiguration,
    Stage1EvaluationDataError,
    Stage1EvaluationReport,
    evaluate_thresholds,
    load_ground_truth_artifact,
    load_score_artifact,
    write_json_artifact,
    write_policy_csv,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Stage-1 thresholds offline from scores and manual annotations."
    )
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--nsfw-thresholds", type=_unit_float, nargs="+")
    parser.add_argument("--nsfl-thresholds", type=_unit_float, nargs="+")
    parser.add_argument("--threshold-start", type=_unit_decimal)
    parser.add_argument("--threshold-stop", type=_unit_decimal)
    parser.add_argument("--threshold-step", type=_positive_decimal)
    parser.add_argument("--minimum-recall", type=_unit_float)
    parser.add_argument("--tolerance-seconds", type=_nonnegative_float, default=5.0)
    parser.add_argument("--window-context-seconds", type=_nonnegative_float, default=5.0)
    parser.add_argument("--window-merge-gap-seconds", type=_nonnegative_float, default=2.0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--csv-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        generated_thresholds = _generated_thresholds(args)
        nsfw_thresholds = tuple(args.nsfw_thresholds or generated_thresholds)
        nsfl_thresholds = tuple(args.nsfl_thresholds or generated_thresholds)
        if not nsfw_thresholds or not nsfl_thresholds:
            parser.error(
                "provide both explicit threshold lists or threshold-start/stop/step"
            )
        scores = load_score_artifact(args.scores)
        ground_truth, annotation_source = load_ground_truth_artifact(
            args.ground_truth,
            duration_us=scores.video.duration_us,
            default_video_filename=scores.video.filename,
        )
        report = evaluate_thresholds(
            scores,
            ground_truth,
            Stage1EvaluationConfiguration(
                nsfw_thresholds=nsfw_thresholds,
                nsfl_thresholds=nsfl_thresholds,
                tolerance_seconds=args.tolerance_seconds,
                window_context_seconds=args.window_context_seconds,
                window_merge_gap_seconds=args.window_merge_gap_seconds,
                minimum_recall=args.minimum_recall,
            ),
            annotation_source=annotation_source,
        )
        if args.json_output is not None:
            write_json_artifact(report, args.json_output)
        if args.csv_output is not None:
            write_policy_csv(report, args.csv_output)
    except (
        FileNotFoundError,
        OSError,
        Stage1EvaluationDataError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2

    _print_report(report)
    if args.json_output is not None:
        print(f"\nJSON: {args.json_output.expanduser().resolve()}")
    if args.csv_output is not None:
        print(f"CSV:  {args.csv_output.expanduser().resolve()}")
    return 0


def _generated_thresholds(args: argparse.Namespace) -> tuple[float, ...]:
    supplied = (
        args.threshold_start,
        args.threshold_stop,
        args.threshold_step,
    )
    if all(value is None for value in supplied):
        return ()
    if any(value is None for value in supplied):
        raise ValueError(
            "threshold-start, threshold-stop, and threshold-step must be supplied together"
        )
    start, stop, step = supplied
    if start > stop:
        raise ValueError("threshold start must not exceed threshold stop")
    values = []
    current = start
    while current <= stop:
        values.append(float(current))
        current += step
    return tuple(values)


def _print_report(report: Stage1EvaluationReport) -> None:
    print("Stage-1 Offline Threshold Evaluation")
    print("=" * 36)
    print(f"Video: {report.video.filename}")
    print(f"Representatives: {report.policies[0].total_representative_samples if report.policies else 0}")
    print(f"Ground-truth intervals: {report.ground_truth.total_intervals}")
    print(f"Policies evaluated: {len(report.policies)}")
    print(
        "\nNSFW    NSFL     Recall  Tolerant  Candidates  Rate     "
        "Frame precision  VLM windows  Movie fraction"
    )
    for result in report.policies:
        print(
            f"{result.policy.nsfw_threshold:<7.3f} "
            f"{result.policy.nsfl_threshold:<8.3f} "
            f"{_optional_ratio(result.interval_recall):<7} "
            f"{_optional_ratio(result.tolerant_interval_recall_5s):<9} "
            f"{result.candidate_samples:<11} "
            f"{_optional_ratio(result.candidate_sample_rate):<8} "
            f"{_optional_ratio(result.frame_candidate_precision):<16} "
            f"{result.estimated_vlm_workload.merged_candidate_windows:<12} "
            f"{result.estimated_vlm_workload.movie_fraction:.3f}"
        )
    label = (
        f"exact recall >= {report.configuration.minimum_recall:.3f}"
        if report.configuration.minimum_recall is not None
        else "all policies with available exact recall"
    )
    print(f"\nHigh-recall report view ({label}):")
    if not report.high_recall_policies:
        print("  No measured policy satisfies this report filter.")
    for index, policy in enumerate(report.high_recall_policies, start=1):
        print(
            f"  {index:>3}. NSFW={policy.nsfw_threshold:.3f}, "
            f"NSFL={policy.nsfl_threshold:.3f}, recall={policy.interval_recall:.3f}, "
            f"movie_fraction={policy.estimated_vlm_movie_fraction:.3f}, "
            f"candidate_rate={_optional_ratio(policy.candidate_sample_rate)}"
        )
    print("\nThis ordering is an evaluation report, not a production threshold selection.")


def _optional_ratio(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "N/A"


def _unit_float(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("value must be between zero and one")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def _unit_decimal(value: str) -> Decimal:
    parsed = _decimal(value)
    if not Decimal(0) <= parsed <= Decimal(1):
        raise argparse.ArgumentTypeError("value must be between zero and one")
    return parsed


def _positive_decimal(value: str) -> Decimal:
    parsed = _decimal(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError("value must be decimal") from exc
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("value must be finite")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
