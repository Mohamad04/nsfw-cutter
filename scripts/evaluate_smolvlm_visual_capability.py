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
    load_and_validate_frame_cache,
    load_quality_inputs,
)
from services.analysis.smolvlm_verifier import SmolVLMError, SmolVLMVerifier
from services.analysis.smolvlm_visual_capability import (
    SmolVLMVisualCapabilityError,
    evaluate_binary_capability,
    evaluate_bitmask_capability,
)
from services.analysis.stage1_evaluation import write_json_artifact


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the cached-frame SmolVLM binary and conditionally gated bitmask "
            "visual-capability ablation."
        )
    )
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--preprocessing-scores", required=True, type=Path)
    parser.add_argument("--frame-cache", required=True, type=Path)
    parser.add_argument("--binary-output", required=True, type=Path)
    parser.add_argument("--bitmask-output", required=True, type=Path)
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
            raise SmolVLMVisualCapabilityError(
                "The existing selected-frame cache is not fully resolved."
            )
        verifier = SmolVLMVerifier(local_files_only=args.local_files_only, device="cuda")
        binary = evaluate_binary_capability(
            events,
            ground_truth,
            manifest,
            event_artifact_path=args.events,
            ground_truth_path=args.ground_truth,
            frame_cache_root=args.frame_cache,
            verifier=verifier,
            progress_callback=_binary_progress,
        )
        write_json_artifact(binary, args.binary_output)
        _print_binary(binary)
        if binary.phase_b_gate.should_run:
            bitmask = evaluate_bitmask_capability(
                events,
                ground_truth,
                manifest,
                binary,
                frame_cache_root=args.frame_cache,
                verifier=verifier,
                progress_callback=_bitmask_progress,
            )
            write_json_artifact(bitmask, args.bitmask_output)
            _print_bitmask(bitmask)
        else:
            print(f"Phase B skipped: {binary.phase_b_gate.reason}")
        return 0
    except (
        OSError,
        ValueError,
        SmolVLMError,
        SmolVLMQualityEvaluationError,
        SmolVLMVisualCapabilityError,
    ) as exc:
        print(f"SmolVLM visual-capability ablation failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SmolVLM visual-capability ablation cancelled.", file=sys.stderr)
        return 130


def _binary_progress(completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 12 == 0:
        print(f"binary: {completed}/{total}", flush=True)


def _bitmask_progress(label: str, completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 10 == 0:
        print(f"bitmask-{label}: {completed}/{total}", flush=True)


def _print_binary(report: object) -> None:
    summary = report.summary
    print("\nSmolVLM binary visual-capability result")
    print(f"Known-silver events: {summary.event_count}")
    print(f"Valid YES/NO: {summary.valid_yes_no_count}/{summary.request_count}")
    print(f"Known-unsafe recall: {summary.known_unsafe_recall:.3f}")
    print(f"Category-aware recall: {summary.category_aware_recall:.3f}")
    print(f"Total request seconds: {summary.latency.total_request_seconds:.3f}")


def _print_bitmask(report: object) -> None:
    summary = report.known_silver_summary
    print("\nSmolVLM six-bit visual-capability result")
    print(f"Valid outputs: {summary.valid_count}/{summary.event_count}")
    print(f"Known-unsafe recall: {summary.known_unsafe_recall:.3f}")
    print(f"Category-aware recall: {summary.category_aware_recall:.3f}")
    print(f"Full run: {'executed' if report.full_events is not None else 'skipped'}")


if __name__ == "__main__":
    raise SystemExit(main())
