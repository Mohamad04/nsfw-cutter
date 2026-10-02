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

from services.analysis.qwen3vl_binary_capability import (
    Qwen3VLError,
    Qwen3VLProvider,
    evaluate_binary_capability,
    run_smoke_benchmark,
)
from services.analysis.smolvlm_quality_evaluation import (
    SmolVLMQualityEvaluationError,
    load_and_validate_frame_cache,
    load_quality_inputs,
)
from services.analysis.stage1_evaluation import write_json_artifact


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated Qwen3-VL-2B CUDA/BF16 smoke gate and binary "
            "known-silver capability comparison."
        )
    )
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--preprocessing-scores", required=True, type=Path)
    parser.add_argument("--frame-cache", required=True, type=Path)
    parser.add_argument("--smol-baseline", required=True, type=Path)
    parser.add_argument("--smoke-output", required=True, type=Path)
    parser.add_argument("--capability-output", required=True, type=Path)
    parser.add_argument("--comparison-csv", type=Path)
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
        provider = Qwen3VLProvider(local_files_only=args.local_files_only)
        smoke = run_smoke_benchmark(
            events,
            ground_truth,
            manifest,
            frame_cache_root=args.frame_cache,
            provider=provider,
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
            provider=provider,
            smoke=smoke,
            smol_baseline_path=args.smol_baseline,
            progress_callback=_progress,
        )
        write_json_artifact(report, args.capability_output)
        if args.comparison_csv is not None:
            _write_comparison_csv(report, args.comparison_csv)
        _print_capability(report)
        return 0
    except (
        OSError,
        ValueError,
        Qwen3VLError,
        SmolVLMQualityEvaluationError,
    ) as exc:
        print(f"Qwen3-VL capability benchmark failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Qwen3-VL capability benchmark cancelled.", file=sys.stderr)
        return 130


def _progress(completed: int, total: int) -> None:
    if completed == 1 or completed == total or completed % 12 == 0:
        print(f"binary: {completed}/{total}", flush=True)


def _print_smoke(report: object) -> None:
    print("\nQwen3-VL smoke benchmark")
    print(f"Model load: {report.model_load_seconds:.3f} s")
    for case in report.cases:
        metrics = case.generation.processor_metrics
        visual_tokens = metrics.total_visual_tokens if metrics else "unavailable"
        print(
            f"{case.image_count} images: success={case.succeeded}, "
            f"answer={case.parsed_answer.value}, visual_tokens={visual_tokens}, "
            f"total={case.generation.total_seconds:.3f} s, "
            f"peak_allocated={case.generation.peak_cuda_allocated_bytes}"
        )
    print(f"Six-image gate: {'passed' if report.six_image_gate_passed else 'failed'}")


def _print_capability(report: object) -> None:
    summary = report.summary
    print("\nQwen3-VL binary capability result")
    print(f"Valid YES/NO: {summary.valid_yes_no_count}/{summary.request_count}")
    print(f"Known-unsafe recall: {summary.known_unsafe_recall:.3f}")
    print(f"Category-aware recall: {summary.category_aware_recall:.3f}")
    print(f"Total request seconds: {summary.latency.total_request_seconds:.3f}")
    print(f"Peak CUDA allocated: {summary.peak_cuda_allocated_bytes}")


def _write_comparison_csv(report: object, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("metric", "smolvlm2_500m", "qwen3vl_2b"),
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
