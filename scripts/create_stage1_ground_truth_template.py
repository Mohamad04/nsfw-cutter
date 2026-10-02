from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.analysis.stage1_evaluation import (
    Stage1EvaluationDataError,
    create_ground_truth_template,
    load_score_artifact,
    write_json_artifact,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an empty manual-annotation template from Stage-1 score metadata."
    )
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        scores = load_score_artifact(args.scores)
        output_path = write_json_artifact(
            create_ground_truth_template(scores),
            args.output,
        )
    except (OSError, Stage1EvaluationDataError, ValueError) as exc:
        print(f"Template creation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Empty ground-truth template: {output_path}")
    print("No intervals were inferred; add only manually verified annotations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
