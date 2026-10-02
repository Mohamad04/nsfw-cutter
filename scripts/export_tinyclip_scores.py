from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.tinyclip_score_export import (
    TinyCLIPScoreArtifactError,
    export_tinyclip_scores,
)
from services.analysis.tinyclip_semantic import (
    ExperimentalPromptBank,
    TinyCLIPSemanticError,
)


def build_argument_parser() -> argparse.ArgumentParser:
    defaults = PreprocessingConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Run experimental CPU TinyCLIP once and export raw semantic similarities."
        )
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--prompt-bank", type=Path, required=True)
    parser.add_argument("--batch-size", type=_positive_int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-video-fingerprint", action="store_true")
    parser.add_argument(
        "--sampling-gap",
        type=_positive_float,
        default=defaults.max_sampling_gap_seconds,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        prompt_payload = json.loads(args.prompt_bank.read_text(encoding="utf-8"))
        prompt_bank = ExperimentalPromptBank.model_validate(prompt_payload)
        artifact, output_path = export_tinyclip_scores(
            args.video,
            args.output,
            batch_size=args.batch_size,
            prompt_bank=prompt_bank,
            config=PreprocessingConfig(
                max_sampling_gap_seconds=args.sampling_gap
            ),
            local_files_only=args.local_files_only,
            include_video_fingerprint=not args.no_video_fingerprint,
        )
    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
        ValidationError,
        TinyCLIPScoreArtifactError,
        TinyCLIPSemanticError,
        ValueError,
    ) as exc:
        print(f"Experimental TinyCLIP export failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Experimental TinyCLIP export cancelled.", file=sys.stderr)
        return 130

    print("Experimental TinyCLIP raw-score export complete")
    print(f"  Video:           {artifact.video.filename}")
    print(f"  Representatives: {len(artifact.samples)}")
    print(f"  Prompt bank:     {artifact.prompt_bank.bank_id}")
    print(f"  Model revision:  {artifact.model.revision}")
    print(f"  Output:          {output_path}")
    print("  Production use:  NOT LICENSE-CLEARED")
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


if __name__ == "__main__":
    raise SystemExit(main())
