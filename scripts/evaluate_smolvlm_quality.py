from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.analysis.smolvlm_quality_evaluation import (
    SmolVLMQualityEvaluationError,
    cleanup_evaluation_frame_cache,
    evaluate_real_candidate_quality,
    load_and_validate_frame_cache,
    load_quality_inputs,
    reconstruct_selected_frames,
    write_missed_interval_review,
    write_quality_csv,
)
from services.analysis.smolvlm_verifier import SmolVLMError, SmolVLMVerifier
from services.analysis.stage1_evaluation import write_json_artifact


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct exact selected representative frames once, then run the "
            "experimental SmolVLM real candidate-event quality evaluation."
        )
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--preprocessing-scores", required=True, type=Path)
    parser.add_argument("--frame-cache", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument("--missed-review-output", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument(
        "--reuse-frame-cache",
        action="store_true",
        help="Validate and reuse the existing ignored lossless frame cache",
    )
    parser.add_argument(
        "--reconstruct-only",
        action="store_true",
        help="Build and validate the frame cache without loading the VLM",
    )
    parser.add_argument(
        "--skip-default-splitting-comparison",
        action="store_true",
    )
    parser.add_argument(
        "--cleanup-frame-cache",
        action="store_true",
        help="Remove the recognized evaluation frame cache after all outputs are written",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        events, ground_truth, scores = load_quality_inputs(
            args.events,
            args.ground_truth,
            args.preprocessing_scores,
        )
        if args.reuse_frame_cache:
            manifest = load_and_validate_frame_cache(
                args.frame_cache,
                events,
                event_artifact_path=args.events,
                preprocessing_score_path=args.preprocessing_scores,
            )
        else:
            manifest = reconstruct_selected_frames(
                args.video,
                events,
                scores,
                event_artifact_path=args.events,
                preprocessing_score_path=args.preprocessing_scores,
                cache_root=args.frame_cache,
            )
        _print_reconstruction(manifest)
        if not manifest.all_references_resolved:
            print(
                "Exact selected-frame reconstruction is incomplete; VLM evaluation "
                "will not start.",
                file=sys.stderr,
            )
            return 3
        if args.reconstruct_only:
            return 0

        verifier = SmolVLMVerifier(
            local_files_only=args.local_files_only,
            device=args.device,
        )
        report = evaluate_real_candidate_quality(
            events,
            ground_truth,
            manifest,
            event_artifact_path=args.events,
            ground_truth_path=args.ground_truth,
            frame_cache_root=args.frame_cache,
            verifier=verifier,
            image_splitting=False,
            max_new_tokens=64,
            retry_truncation=True,
            run_default_comparison=not args.skip_default_splitting_comparison,
            progress_callback=_print_progress,
        )
        write_json_artifact(report, args.json_output)
        if args.csv_output is not None:
            write_quality_csv(report, args.csv_output)
        review_path = None
        if args.missed_review_output is not None:
            review_path = write_missed_interval_review(
                report,
                frame_cache_root=args.frame_cache,
                output_dir=args.missed_review_output,
            )
        _print_report(report, args.json_output, args.csv_output, review_path)
        if args.cleanup_frame_cache:
            cleanup_evaluation_frame_cache(args.frame_cache)
            print(f"Removed evaluation frame cache: {args.frame_cache.resolve()}")
        return 0
    except (OSError, ValueError, SmolVLMError, SmolVLMQualityEvaluationError) as exc:
        print(f"SmolVLM quality evaluation failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SmolVLM quality evaluation cancelled.", file=sys.stderr)
        return 130


def _print_reconstruction(manifest: object) -> None:
    print("Experimental selected-frame reconstruction")
    print(f"Representatives observed: {manifest.representatives_observed}")
    print(
        "Selected references:     "
        f"{len(manifest.entries)}/{manifest.expected_frame_reference_count}"
    )
    print(f"Unresolved references:   {len(manifest.unresolved)}")


def _print_progress(completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 10 == 0:
        print(f"Verified events: {completed}/{total}", flush=True)


def _print_report(
    report: object,
    json_path: Path,
    csv_path: Path | None,
    review_path: Path | None,
) -> None:
    summary = report.summary
    print("\nExperimental SmolVLM real candidate quality")
    print(f"Events/images:          {summary.total_events}/{summary.total_selected_images}")
    print(
        "Statuses unsafe/safe/unverified: "
        f"{summary.verified_unsafe}/{summary.verified_safe}/{summary.unverified}"
    )
    print(f"Strict JSON rate:       {summary.syntactic_json_rate:.3%}")
    print(f"Pydantic-valid rate:    {summary.pydantic_valid_rate:.3%}")
    print(
        "Silver unsafe recall:   "
        f"{summary.exact_unsafe_detected_intervals}/"
        f"{len(report.silver_intervals)} ({summary.exact_unsafe_recall:.3%})"
    )
    print(
        "Category-aware recall:  "
        f"{summary.exact_category_detected_intervals}/"
        f"{len(report.silver_intervals)} "
        f"({summary.exact_category_aware_recall:.3%})"
    )
    print(f"Verifier wall time:      {summary.sequential_verifier_wall_seconds:.3f} s")
    print(f"JSON: {json_path.resolve()}")
    if csv_path is not None:
        print(f"CSV:  {csv_path.resolve()}")
    if review_path is not None:
        print(f"Missed review: {review_path}")


if __name__ == "__main__":
    raise SystemExit(main())
