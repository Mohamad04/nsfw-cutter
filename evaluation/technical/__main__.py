"""python -m evaluation.technical --help; all side effects explicitly gated."""
import argparse
import json
from pathlib import Path

from evaluation.technical import benchmark as b


def main(argv=None):
    parser = argparse.ArgumentParser(description="Technical-only UCF101 benchmark; no NSFW ground truth")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "download", "prepare", "run", "report"):
        p = commands.add_parser(name)
        p.add_argument("manifest", type=Path)
        if name in {"download", "prepare", "run"}:
            op = "inference" if name == "run" else name
            p.add_argument("--allow-" + op, action="store_true")
            p.add_argument("--usage-clearance", type=Path)
        if name in {"download", "prepare", "report"}:
            p.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            p.add_argument("--media-root", type=Path, required=True)
        if name in {"run", "report"}:
            p.add_argument("--campaign", type=Path, required=True)
        if name == "run":
            p.add_argument("--prepared", type=Path, required=True)
            p.add_argument("--retry-incomplete", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = b.proposal(args.manifest)
        if args.command == "validate":
            result = {"valid": True, "clips": len(manifest["clips"]), "media_verified": False,
                      "nsfw_ground_truth": "unknown", "inference_executed": False}
        elif args.command == "download":
            result = str(b.download(manifest, args.output, allow=args.allow_download, clearance=args.usage_clearance))
        elif args.command == "prepare":
            result = str(b.prepare(manifest, args.media_root, args.output, allow=args.allow_prepare, clearance=args.usage_clearance))
        elif args.command == "run":
            result = b.run(manifest, args.prepared, args.campaign, allow=args.allow_inference,
                           clearance=args.usage_clearance, retry_incomplete=args.retry_incomplete)
            destination = args.campaign / ("report_" + b.uuid.uuid4().hex + ".json")
            b.write_new(destination, result)
            print(json.dumps({"report": str(destination), "completed_clips": result["completed_clips"],
                              "selected_clips": result["selected_clips"], "status_counts": result["status_counts"]}))
            return 0 if result["completed_clips"] == result["selected_clips"] else 2
        else:
            with b.campaign_lock(args.campaign):
                result = b.report(manifest, args.campaign)
                b.write_new(args.output, result)
            result = {"report": str(args.output), "completed_clips": result["completed_clips"]}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, b.subprocess.SubprocessError) as exc:
        # Subprocess stdout/stderr or raw model output must not reach console.
        parser.error(f"{type(exc).__name__}: technical benchmark stopped; inspect local provenance")


if __name__ == "__main__":
    raise SystemExit(main())
