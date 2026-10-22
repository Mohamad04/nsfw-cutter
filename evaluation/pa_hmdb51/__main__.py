"""CLI: python -m evaluation.pa_hmdb51 catalog|prepare|run|analyze|score-review.

prepare/analyze/score-review never load a model; run requires --allow-inference and delegates to the
frozen benchmark runner (evaluation.benchmark.runner) with the A2 configuration only, because HMDB51
clips have no audio track and A1 (video-only copy) would repeat A2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PILOT_MANIFEST = Path("artifacts/pilot/manifest.json")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evaluation.pa_hmdb51")
    commands = parser.add_subparsers(dest="command", required=True)

    prep = commands.add_parser("prepare", help="inspect archives, extract, convert, verify, write manifests")
    prep.add_argument("--dataset-dir", type=Path, required=True, help="folder with PrivacyAttributes/ and the .rar files")
    prep.add_argument("--media-root", type=Path, required=True, help="where extracted and converted media go")
    prep.add_argument("--output", type=Path, required=True, help="deliverable directory (tables and manifests)")
    prep.add_argument("--actions", nargs="+", default=["kiss", "dive"])
    prep.add_argument("--scope", choices=("annotated", "all", "pa_nudity2"), default="all")
    prep.add_argument("--action-scope", action="append", default=[], metavar="ACTION=SCOPE",
                      help="per-action scope override, e.g. brush_hair=annotated")
    prep.add_argument("--batch", help="single manifest pa_hmdb51_<batch> instead of the pilot/extension split")
    prep.add_argument("--unrar", type=Path, default=None)

    cat = commands.add_parser("catalog", help="list PA-HMDB51 nudity level-2 videos of every action (no media)")
    cat.add_argument("--dataset-dir", type=Path, required=True)
    cat.add_argument("--output", type=Path, required=True, help="new directory")

    run = commands.add_parser("run", help="run the frozen pipeline (A2) on a prepared manifest")
    run.add_argument("manifest", type=Path)
    run.add_argument("--media-root", type=Path, required=True)
    run.add_argument("--campaign", type=Path, required=True)
    run.add_argument("--pilot-manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    run.add_argument("--allow-inference", action="store_true")
    run.add_argument("--retry-incomplete", action="store_true")
    run.add_argument("--attempt-timeout", type=float, default=300.0)
    run.add_argument("--accept-partial", action="store_true",
                     help="record partial analyses (e.g. no frame sampled on clips under 2.5 s) and continue")
    run.add_argument("--pipeline-version", default=None,
                     help="registered frozen pipeline version (evaluation/benchmark/versions.py); default: baseline")

    analyze = commands.add_parser("analyze", help="build predictions, timings, metrics and the review sheet")
    analyze.add_argument("--run", nargs=2, action="append", metavar=("MANIFEST", "CAMPAIGN"), required=True)
    analyze.add_argument("--prepared", type=Path, required=True, help="output directory of prepare")
    analyze.add_argument("--media-root", type=Path, required=True)
    analyze.add_argument("--pilot-manifest", type=Path, default=DEFAULT_PILOT_MANIFEST)
    analyze.add_argument("--output", type=Path, required=True)

    review = commands.add_parser("score-review", help="score predictions against a completed manual_review.csv")
    review.add_argument("review_csv", type=Path)
    review.add_argument("--analysis", type=Path, required=True,
                        help="output directory of analyze (per_video.csv, predictions.csv, manual_review_key.csv)")
    review.add_argument("--output", type=Path, required=True, help="new JSON file")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        from evaluation.pa_hmdb51.prepare import UNRAR_DEFAULT, prepare
        overrides = dict(item.split("=", 1) for item in args.action_scope)
        summary = prepare(args.dataset_dir, args.media_root, args.output, actions=tuple(args.actions),
                          scope=args.scope, unrar=args.unrar or UNRAR_DEFAULT, action_scopes=overrides,
                          batch=args.batch)
        print(json.dumps({k: summary[k] for k in ("videos_prepared", "videos_excluded", "manifests")}, indent=2))
        return 0
    if args.command == "catalog":
        from evaluation.pa_hmdb51.catalog import catalog
        summary = catalog(args.dataset_dir, args.output)
        print(json.dumps({k: v for k, v in summary.items() if k != "by_action"}, indent=2))
        return 0
    if args.command == "run":
        from evaluation.benchmark import runner
        outcome = runner.run(args.manifest, args.media_root, args.campaign, args.pilot_manifest,
                             allow_inference=args.allow_inference, retry_incomplete=args.retry_incomplete,
                             limits=runner.Limits(attempt_timeout_seconds=args.attempt_timeout), configs=("A2",),
                             accept_partial=args.accept_partial,
                             pipeline_version=args.pipeline_version or runner.DEFAULT_PIPELINE_VERSION)
        print(json.dumps(outcome, indent=2, default=str))
        return 0 if outcome.get("stopped_at") is None else 2
    if args.command == "analyze":
        from evaluation.pa_hmdb51.analyze import analyze as build
        summary = build([(Path(m), Path(c)) for m, c in args.run], prepared=args.prepared,
                        media_root=args.media_root, pilot_manifest=args.pilot_manifest, output=args.output)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    from evaluation.pa_hmdb51.review import score_review
    report = score_review(args.review_csv, args.analysis)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "status": report["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
