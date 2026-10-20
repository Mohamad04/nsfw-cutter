"""CLI: python -m evaluation.benchmark validate|score|run|collect.

validate/score/collect never open media or import the AI runtime; run requires --allow-inference.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
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
    scoring = commands.add_parser("score", help="score recorded results against a manifest")
    running = commands.add_parser("run", help="run A2/A1 sequentially on the manifest's media (inference)")
    collecting = commands.add_parser("collect", help="build a validated ResultsFile from a campaign")
    for command in (validate, scoring, running, collecting):
        command.add_argument("manifest", type=Path)
        # Mandatory: the anti-leakage check against the tuning pilot cannot be skipped.
        command.add_argument("--pilot-manifest", type=Path, required=True,
                             help="development pilot manifest whose clips must not reappear in the benchmark")
    scoring.add_argument("results", type=Path)
    scoring.add_argument("--output", type=Path, required=True, help="new directory; must not exist")
    scoring.add_argument("--split", choices=("tuning", "test"), default="test")
    scoring.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    scoring.add_argument("--seed", type=int, default=DEFAULT_SEED)
    scoring.add_argument("--subset", type=Path,
                         help="JSON spec (subset_id, reason, exclude_item_ids, optional selection_rule) of a "
                              "documented sensitivity subset; results and manifest are left unchanged")
    scoring.add_argument("--labels", type=Path,
                         help="reference labels file exported by python -m evaluation.annotation, bound to this "
                              "manifest's digest; the manifest and results are left unchanged")
    running.add_argument("--media-root", type=Path, required=True)
    running.add_argument("--campaign", type=Path, required=True)
    running.add_argument("--allow-inference", action="store_true")
    running.add_argument("--retry-incomplete", action="store_true")
    running.add_argument("--attempt-timeout", type=float, default=300.0)
    collecting.add_argument("--campaign", type=Path, required=True)
    collecting.add_argument("--output", type=Path, required=True, help="new ResultsFile path; must not exist")
    args = parser.parse_args(argv)

    if args.command in ("run", "collect"):
        from evaluation.benchmark import runner
        if args.command == "run":
            outcome = runner.run(args.manifest, args.media_root, args.campaign, args.pilot_manifest,
                                 allow_inference=args.allow_inference, retry_incomplete=args.retry_incomplete,
                                 limits=runner.Limits(attempt_timeout_seconds=args.attempt_timeout))
            print(json.dumps(outcome, indent=2, default=str))
            return 0 if outcome.get("stopped_at") is None else 2
        results = runner.collect(args.manifest, args.campaign, args.pilot_manifest, args.output)
        print(json.dumps({"output": str(args.output), "results": len(results.results)}, indent=2))
        return 0

    manifest = load_manifest(args.manifest)
    if args.command == "validate":
        labels = [item.video_label for item in manifest.items]
        disjoint = assert_disjoint_from_pilot(manifest, args.pilot_manifest)
        print(json.dumps({"valid": True, "benchmark_id": manifest.benchmark_id, "track": manifest.track,
                          "manifest_digest": manifest_digest(manifest), "items": len(manifest.items),
                          "excluded": sum(item.excluded for item in manifest.items),
                          "labels": {label: labels.count(label) for label in sorted(set(labels))},
                          "verification": manifest.verification(),
                          "disjoint_from_pilot": disjoint, "media_identity_verified": False}, indent=2))
        return 0

    subset = None
    if args.subset is not None:
        subset = json.loads(args.subset.read_text(encoding="utf-8-sig"))
        subset["spec_file"] = {"path": str(args.subset), "sha256": hashlib.sha256(args.subset.read_bytes()).hexdigest()}
    labels = None
    if args.labels is not None:
        from evaluation.benchmark.labels import load_labels
        labels = load_labels(args.labels)
    report = score(manifest, load_results(args.results), pilot_manifest=args.pilot_manifest, split=args.split,
                   resamples=args.resamples, seed=args.seed, subset=subset, labels=labels)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    with (args.output / "per_video.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report["per_video"][0]) if report["per_video"] else ["item_id"])
        writer.writeheader()
        writer.writerows(report["per_video"])
    print(json.dumps({"output": str(args.output), "evaluable": report["sample_sizes"]["evaluable"],
                      "subset": (report.get("subset") or {}).get("subset_id"),
                      "scope_warning": report.get("scope_warning")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
