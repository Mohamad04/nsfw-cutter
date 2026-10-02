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

from services.analysis.candidate_clustering_evaluation import (
    CONTEXT_SECONDS,
    MAX_EVENT_DURATIONS_SECONDS,
    MERGE_GAPS_SECONDS,
    CandidateClusteringError,
    build_experimental_events_artifact,
    evaluate_candidate_clustering,
    reconstruct_candidates,
    resolve_experimental_policy,
    write_clustering_csv,
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
            "Offline Stage-1 candidate clustering and VLM-frame planning. It reads "
            "only exported artifacts and does not load media or model runtimes."
        )
    )
    parser.add_argument("--safety-scores", type=Path, required=True)
    parser.add_argument("--semantic-scores", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--prompt-bank", type=Path, required=True)
    parser.add_argument("--union-evaluation", type=Path, required=True)
    parser.add_argument("--robustness-evaluation", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--events-output", type=Path)
    parser.add_argument(
        "--merge-gaps-seconds",
        type=_nonnegative_float,
        nargs="+",
        default=MERGE_GAPS_SECONDS,
    )
    parser.add_argument(
        "--contexts-seconds",
        type=_nonnegative_float,
        nargs="+",
        default=CONTEXT_SECONDS,
    )
    parser.add_argument(
        "--maximum-event-durations-seconds",
        type=_positive_float,
        nargs="+",
        default=MAX_EVENT_DURATIONS_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    config = Stage1UnionEvaluationConfiguration()
    try:
        safety, semantic, ground_truth, prompt_bank, _ = load_union_inputs(
            args.safety_scores,
            args.semantic_scores,
            args.ground_truth,
            args.prompt_bank,
            config,
        )
        policy = resolve_experimental_policy(
            args.union_evaluation,
            args.robustness_evaluation,
        )
        report = evaluate_candidate_clustering(
            safety,
            semantic,
            ground_truth,
            prompt_bank,
            policy,
            config,
            merge_gaps_seconds=args.merge_gaps_seconds,
            contexts_seconds=args.contexts_seconds,
            maximum_event_durations_seconds=args.maximum_event_durations_seconds,
        )
        json_output = write_json_artifact(report, args.json_output)
        csv_output = write_clustering_csv(report, args.csv_output)
        events_output = None
        if args.events_output is not None:
            candidates = reconstruct_candidates(
                safety, semantic, prompt_bank, policy, config
            )
            events = build_experimental_events_artifact(report, candidates)
            if events is not None:
                events_output = write_json_artifact(events, args.events_output)
    except (
        FileNotFoundError,
        OSError,
        Stage1EvaluationDataError,
        Stage1UnionEvaluationError,
        CandidateClusteringError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Offline candidate clustering failed: {exc}", file=sys.stderr)
        return 2
    print(f"Offline candidate clustering: {json_output}")
    print(f"CSV summary: {csv_output}")
    if events_output is not None:
        print(f"Experimental event plan: {events_output}")
    best = report.best_measured_clustering_configuration
    if best is not None:
        print(
            "Best measured clustering: "
            f"events={best.metrics.candidate_events} images={best.metrics.total_vlm_images} "
            f"merge={best.configuration.merge_gap_seconds:g}s "
            f"context={best.configuration.context_seconds:g}s "
            f"max={best.configuration.maximum_event_duration_seconds:g}s"
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


if __name__ == "__main__":
    raise SystemExit(main())
