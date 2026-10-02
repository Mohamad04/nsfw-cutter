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

from services.analysis.semantic_sampling_ablation import (
    DEFAULT_GAPS_SECONDS,
    SemanticSamplingAblationError,
    evaluate_semantic_sampling_ablation,
    write_sampling_ablation_csv,
)
from services.analysis.stage1_evaluation import (
    Stage1EvaluationDataError,
    write_json_artifact,
)
from services.analysis.stage1_union_evaluation import (
    Stage1UnionEvaluationConfiguration,
    Stage1UnionEvaluationError,
    load_union_inputs,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline TinyCLIP timestamp-sampling ablation. Reads only exported JSON "
            "scores and annotations; it does not access a movie or load model runtimes."
        )
    )
    parser.add_argument("--safety-scores", type=Path, required=True)
    parser.add_argument("--semantic-scores", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--prompt-bank", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument(
        "--gaps-seconds", type=_positive_float, nargs="+", default=DEFAULT_GAPS_SECONDS
    )
    parser.add_argument("--threshold-count", type=_threshold_count, default=7)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    config = Stage1UnionEvaluationConfiguration(
        semantic_threshold_count=args.threshold_count,
        tolerance_seconds=args.tolerance_seconds,
        context_seconds=tuple(args.context_seconds),
        merge_gap_seconds=tuple(args.merge_gap_seconds),
    )
    try:
        safety, semantic, ground_truth, prompt_bank, _ = load_union_inputs(
            args.safety_scores,
            args.semantic_scores,
            args.ground_truth,
            args.prompt_bank,
            config,
        )
        report = evaluate_semantic_sampling_ablation(
            safety,
            semantic,
            ground_truth,
            prompt_bank,
            config,
            gaps_seconds=args.gaps_seconds,
        )
        json_output = write_json_artifact(report, args.json_output)
        csv_output = (
            write_sampling_ablation_csv(report, args.csv_output)
            if args.csv_output
            else None
        )
    except (
        FileNotFoundError,
        OSError,
        Stage1EvaluationDataError,
        Stage1UnionEvaluationError,
        SemanticSamplingAblationError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Offline semantic-sampling ablation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Offline semantic-sampling ablation: {json_output}")
    if csv_output is not None:
        print(f"CSV summary: {csv_output}")
    for result in report.results:
        summary = (
            result.smallest_candidate_rate_exact_recall_policy
            or result.best_measured_policy
        )
        print(
            f"{result.mode} gap={result.gap_seconds:g}s retained={result.retained_semantic_samples} "
            f"({result.retained_workload_fraction:.2%}) recall={result.highest_exact_union_recall:.3f} "
            f"candidate_rate={summary.candidate_sample_rate}"
        )
    return 0


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be > 0")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def _threshold_count(value: str) -> int:
    parsed = int(value)
    if not 2 <= parsed <= 64:
        raise argparse.ArgumentTypeError("threshold count must be between 2 and 64")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
