from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.analysis.smolvlm_prompt_ablation import (
    SmolVLMPromptAblationError,
    evaluate_prompt_ablation,
    write_missed_ablation_review_index,
    write_prompt_ablation_csv,
)
from services.analysis.smolvlm_quality_evaluation import (
    SmolVLMQualityEvaluationError,
    load_and_validate_frame_cache,
    load_quality_inputs,
)
from services.analysis.smolvlm_verifier import SmolVLMError, SmolVLMVerifier
from services.analysis.stage1_evaluation import write_json_artifact


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an experimental SmolVLM evidence-map prompt ablation using only "
            "the existing selected-frame cache."
        )
    )
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--preprocessing-scores", required=True, type=Path)
    parser.add_argument("--frame-cache", required=True, type=Path)
    parser.add_argument("--ablation-json-output", required=True, type=Path)
    parser.add_argument("--ablation-csv-output", required=True, type=Path)
    parser.add_argument("--full-json-output", required=True, type=Path)
    parser.add_argument("--missed-review-index", type=Path)
    parser.add_argument("--existing-review-root", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        events, ground_truth, _scores = load_quality_inputs(
            args.events,
            args.ground_truth,
            args.preprocessing_scores,
        )
        manifest = load_and_validate_frame_cache(
            args.frame_cache,
            events,
            event_artifact_path=args.events,
            preprocessing_score_path=args.preprocessing_scores,
        )
        if not manifest.all_references_resolved:
            raise SmolVLMPromptAblationError(
                "The existing selected-frame cache is not fully resolved."
            )
        verifier = SmolVLMVerifier(
            local_files_only=args.local_files_only,
            device="cuda",
        )
        report, full_report = evaluate_prompt_ablation(
            events,
            ground_truth,
            manifest,
            event_artifact_path=args.events,
            ground_truth_path=args.ground_truth,
            frame_cache_root=args.frame_cache,
            verifier=verifier,
            progress_callback=_progress,
        )
        write_json_artifact(report, args.ablation_json_output)
        write_prompt_ablation_csv(report, args.ablation_csv_output)
        write_json_artifact(full_report, args.full_json_output)
        missed_path = None
        if args.missed_review_index and args.existing_review_root:
            missed_path = write_missed_ablation_review_index(
                full_report,
                ground_truth,
                args.missed_review_index,
                existing_review_root=args.existing_review_root,
            )
        _print_report(report, full_report, missed_path)
        return 0
    except (
        OSError,
        ValueError,
        SmolVLMError,
        SmolVLMQualityEvaluationError,
        SmolVLMPromptAblationError,
    ) as exc:
        print(f"SmolVLM prompt ablation failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SmolVLM prompt ablation cancelled.", file=sys.stderr)
        return 130


def _progress(variant: str, completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 10 == 0:
        print(f"{variant}: {completed}/{total}", flush=True)


def _print_report(report: object, full_report: object, missed_path: Path | None) -> None:
    print("\nExperimental SmolVLM evidence-map prompt ablation")
    print(f"Known-silver overlap events: {report.known_silver_event_count}")
    print("variant category_recall unsafe_recall valid unverified CUDA_s collapse")
    for evaluation in report.variants:
        metrics = evaluation.metrics
        print(
            f"{evaluation.definition.variant_id.value} "
            f"{metrics.category_aware_recall:.3f} "
            f"{metrics.known_unsafe_recall:.3f} "
            f"{metrics.effective_pydantic_valid_rate:.3f} "
            f"{metrics.unverified_events} "
            f"{metrics.total_cuda_seconds:.3f} "
            f"{metrics.collapse.most_common_normalized_fraction:.3f}"
        )
    print(f"Best measured variant: {report.best_measured_prompt_variant.value}")
    summary = full_report.summary
    print(
        "Full run detected/no-evidence/unverified: "
        f"{summary.events_with_categories}/"
        f"{summary.events_without_categories}/{summary.unverified_events}"
    )
    print(f"Full-run CUDA seconds: {summary.total_cuda_seconds:.3f}")
    if missed_path:
        print(f"Missed-review index: {missed_path}")


if __name__ == "__main__":
    raise SystemExit(main())
