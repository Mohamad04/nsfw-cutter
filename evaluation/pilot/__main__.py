"""python -m evaluation.pilot --help"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.pilot.manifest import Manifest, load_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="NSFW-Cutter reproducible pilot; no inference by default")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Print JSON Schema without opening media")
    validate = commands.add_parser("validate-only", help="Validate JSON only; no media/model/cache access")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--allow-draft", action="store_true", help="Check structure but permit incomplete templates")
    run = commands.add_parser("run", help="Explicit opt-in to real LOCAL inference, one clip per process")
    run.add_argument("manifest", type=Path)
    run.add_argument("--clip", required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--app-settings", type=Path)
    run.add_argument("--overrides", type=Path, help="JSON object of AnalysisSettings overrides")
    run.add_argument("--allow-inference", action="store_true")
    score = commands.add_parser("score", help="Offline metrics from explicitly selected attempts")
    score.add_argument("manifest", type=Path)
    score.add_argument("--attempts", nargs="+", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            print(json.dumps(Manifest.model_json_schema(), indent=2))
            return 0
        manifest = load_manifest(args.manifest, allow_draft=getattr(args, "allow_draft", False))
        if args.command == "validate-only":
            ready = all(clip.exhaustive for clip in manifest.clips)
            print(json.dumps({"valid_structure": True, "annotation_ready": ready,
                              "clip_count": len(manifest.clips), "synthetic": manifest.synthetic,
                              "media_identity_verified": False, "inference_executed": False}))
            return 0
        if args.command == "run":
            if not args.allow_inference:
                raise ValueError("run requires --allow-inference; use validate-only for offline preparation")
            if manifest.synthetic:
                raise ValueError("Synthetic manifests are for tests only, not real inference")
            clip = next((c for c in manifest.clips if c.clip_id == args.clip), None)
            if clip is None:
                raise ValueError(f"Unknown clip_id: {args.clip}")
            from evaluation.pilot.runner import offline_environment, resolve_settings, run_attempt
            overrides = json.loads(args.overrides.read_text(encoding="utf-8-sig")) if args.overrides else None
            if overrides is not None and not isinstance(overrides, dict):
                raise ValueError("Overrides must be a JSON object")
            with offline_environment():
                settings, origin = resolve_settings(args.app_settings, overrides)
                directory, summary = run_attempt(manifest, args.manifest, clip, settings, args.output,
                                                 settings_origin=origin)
            print(json.dumps({"attempt_directory": str(directory), **summary}, indent=2))
            return 0 if summary["status"] == "completed" else 2
        from evaluation.pilot.report import save_report, score_attempts
        report = score_attempts(manifest, args.attempts)
        save_report(report, args.output)
        print(f"Offline report: {args.output}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
