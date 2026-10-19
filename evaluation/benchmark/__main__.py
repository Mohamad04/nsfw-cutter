"""CLI: python -m evaluation.benchmark validate|score. Never opens media or imports the AI runtime."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from evaluation.benchmark.manifest import assert_disjoint_from_pilot, load_manifest, manifest_digest
from evaluation.benchmark.report import DEFAULT_RESAMPLES, DEFAULT_SEED, score
from evaluation.benchmark.results import load_results


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evaluation.benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a benchmark manifest (no media access)")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--pilot-manifest", type=Path,
                          help="development pilot manifest whose clips must not reappear in the benchmark")
    scoring = commands.add_parser("score", help="score recorded results against a manifest")
    scoring.add_argument("manifest", type=Path)
    scoring.add_argument("results", type=Path)
    scoring.add_argument("--output", type=Path, required=True, help="new directory; must not exist")
    scoring.add_argument("--split", choices=("tuning", "test"), default="test")
    scoring.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    scoring.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.command == "validate":
        labels = [item.video_label for item in manifest.items]
        disjoint = assert_disjoint_from_pilot(manifest, args.pilot_manifest) if args.pilot_manifest else None
        print(json.dumps({"valid": True, "benchmark_id": manifest.benchmark_id, "track": manifest.track,
                          "manifest_digest": manifest_digest(manifest), "items": len(manifest.items),
                          "excluded": sum(item.excluded for item in manifest.items),
                          "labels": {label: labels.count(label) for label in sorted(set(labels))},
                          "verification": manifest.verification(),
                          "disjoint_from_pilot": disjoint, "media_identity_verified": False}, indent=2))
        return 0

    report = score(manifest, load_results(args.results), split=args.split,
                   resamples=args.resamples, seed=args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (args.output / "per_video.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["per_video"][0]) if report["per_video"] else ["item_id"])
        writer.writeheader()
        writer.writerows(report["per_video"])
    print(json.dumps({"output": str(args.output), "evaluable": report["sample_sizes"]["evaluable"],
                      "scope_warning": report.get("scope_warning")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
