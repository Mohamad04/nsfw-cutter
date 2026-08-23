from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_evaluation import Stage1EvaluationDataError
from services.analysis.stage1_safety import Stage1SafetyError
from services.analysis.stage1_score_export import export_stage1_scores


def build_argument_parser() -> argparse.ArgumentParser:
    defaults = PreprocessingConfig()
    parser = argparse.ArgumentParser(
        description="Run CPU Stage 1 once and atomically export timestamped raw probabilities."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--batch-size", type=_positive_int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument(
        "--no-video-fingerprint",
        action="store_true",
        help="Skip the optional content SHA-256 fingerprint",
    )
    parser.add_argument(
        "--sampling-gap",
        type=_positive_float,
        default=defaults.max_sampling_gap_seconds,
    )
    parser.add_argument(
        "--chunk-duration",
        type=_positive_float,
        default=defaults.chunk_duration_seconds,
    )
    parser.add_argument(
        "--chunk-overlap",
        type=_nonnegative_float,
        default=defaults.chunk_overlap_seconds,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        artifact, output_path = export_stage1_scores(
            args.video,
            args.output,
            batch_size=args.batch_size,
            config=PreprocessingConfig(
                max_sampling_gap_seconds=args.sampling_gap,
                chunk_duration_seconds=args.chunk_duration,
                chunk_overlap_seconds=args.chunk_overlap,
            ),
            local_files_only=args.local_files_only,
            include_video_fingerprint=not args.no_video_fingerprint,
        )
    except (
        FileNotFoundError,
        OSError,
        Stage1EvaluationDataError,
        Stage1SafetyError,
        ValidationError,
        ValueError,
    ) as exc:
        print(f"Score export failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Score export cancelled by user.", file=sys.stderr)
        return 130

    print("Stage-1 score export complete")
    print(f"  Video:          {artifact.video.filename}")
    print(f"  Duration:       {artifact.video.duration_us / 1_000_000:.3f} s")
    print(f"  Representatives:{len(artifact.samples):>8}")
    print(f"  Model revision: {artifact.model.revision}")
    print(f"  Output:         {output_path}")
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0.0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
