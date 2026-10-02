from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.analysis.smolvlm22_binary_capability import (
    SmolVLM22BenchmarkError,
    create_smolvlm22_verifier,
    evaluate_binary_capability,
    run_smoke_benchmark,
)
from services.analysis.smolvlm_quality_evaluation import (
    SmolVLMQualityEvaluationError,
    load_and_validate_frame_cache,
    load_quality_inputs,
)
from services.analysis.smolvlm_verifier import SmolVLMError
from services.analysis.stage1_evaluation import write_json_artifact


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated SmolVLM2-2.2B CUDA/BF16 smoke gate and binary "
            "known-silver comparison."
        )
    )
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--preprocessing-scores", required=True, type=Path)
    parser.add_argument("--frame-cache", required=True, type=Path)
    parser.add_argument("--smol500-baseline", required=True, type=Path)
    parser.add_argument("--qwen-baseline", required=True, type=Path)
    parser.add_argument("--smoke-output", required=True, type=Path)
    parser.add_argument("--capability-output", required=True, type=Path)
    parser.add_argument("--comparison-csv", required=True, type=Path)
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
        verifier = create_smolvlm22_verifier(
            local_files_only=args.local_files_only
        )
        smoke = run_smoke_benchmark(
            events,
            ground_truth,
            manifest,
            frame_cache_root=args.frame_cache,
            verifier=verifier,
        )
        write_json_artifact(smoke, args.smoke_output)
        _print_smoke(smoke)
        if not smoke.six_image_gate_passed:
            print(
                "Six-image gate failed; the 144-request capability run was not run.",
                file=sys.stderr,
            )
            return 3
        report = evaluate_binary_capability(
            events,
            ground_truth,
            manifest,
            event_artifact_path=args.events,
            ground_truth_path=args.ground_truth,
            frame_cache_root=args.frame_cache,
            verifier=verifier,
            smoke=smoke,
            smol500_path=args.smol500_baseline,
            qwen_path=args.qwen_baseline,
            progress_callback=_progress,
        )
        write_json_artifact(report, args.capability_output)
        _write_comparison_csv(report, args.comparison_csv)
        _print_capability(report)
        return 0
    except (
        OSError,
        ValueError,
        SmolVLMError,
        SmolVLM22BenchmarkError,
        SmolVLMQualityEvaluationError,
    ) as exc:
        print(f"SmolVLM2-2.2B capability benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SmolVLM2-2.2B capability benchmark cancelled.", file=sys.stderr)
        return 130


def _progress(completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 12 == 0:
        print(f"binary: {completed}/{total}", flush=True)


def _print_smoke(report: object) -> None:
    print("\nSmolVLM2-2.2B smoke benchmark")
    print(f"Model load: {report.model_load_seconds:.3f} s")
    for case in report.cases:
        expansion = case.generation.expansion
        print(
            f"{case.image_count} images: success={case.succeeded}, "
            f"answer={case.parsed_answer.value}, "
            f"visual_blocks={expansion.visual_block_count if expansion else 'n/a'}, "
            f"visual_tokens={expansion.visual_token_count if expansion else 'n/a'}, "
            f"total={case.generation.total_seconds:.3f} s, "
            f"peak_allocated={case.peak_cuda_allocated_bytes}"
        )
    print(f"Six-image gate: {'passed' if report.six_image_gate_passed else 'failed'}")


def _print_capability(report: object) -> None:
    summary = report.summary
    print("\nSmolVLM2-2.2B binary capability result")
    print(f"Valid YES/NO: {summary.valid_yes_no_count}/{summary.request_count}")
    print(f"Known-unsafe recall: {summary.known_unsafe_recall:.3f}")
    print(f"Category-aware recall: {summary.category_aware_recall:.3f}")
    print(
        f"Total request seconds: "
        f"{report.performance.latency.total_request_seconds:.3f}"
    )
    print(f"Peak CUDA allocated: {report.performance.peak_cuda_allocated_bytes}")


def _write_comparison_csv(report: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "metric",
                    "smolvlm2_500m",
                    "qwen3vl_2b",
                    "smolvlm2_2_2b",
                ),
            )
            writer.writeheader()
            for metric, values in report.comparison.metrics.items():
                writer.writerow({"metric": metric, **values})
        temporary.replace(output)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
