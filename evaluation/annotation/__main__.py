"""CLI: python -m evaluation.annotation review|status|export.

review opens (or creates) a local single-reviewer session and the review window; status prints
progress counts only; export writes the reference labels file once every item is locked. Nothing here
reads campaign results or loads a model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluation.annotation.session import Session

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GUIDE = ROOT / "docs" / "nsfw_annotation_guide.md"


def open_or_create(args):
    if (args.session / "session.json").exists():
        return Session(args.session, args.manifest, args.media_root)
    if not getattr(args, "reviewer_id", None):
        raise SystemExit("new session: --reviewer-id is required")
    return Session.create(args.session, args.manifest, args.media_root, reviewer_id=args.reviewer_id,
                          guide_path=args.guide, seed=args.seed)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evaluation.annotation")
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="open the review window (creates the session if needed)")
    status = commands.add_parser("status", help="print progress counts (no labels)")
    export = commands.add_parser("export", help="write the reference labels file (complete review only)")
    for command in (review, status, export):
        command.add_argument("--session", type=Path, required=True, help="local session directory")
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--media-root", type=Path, required=True)
    review.add_argument("--reviewer-id", help="pseudonym (new session only)")
    review.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
    review.add_argument("--seed", type=int, default=1001, help="review order seed (new session only)")
    export.add_argument("--output", type=Path, required=True, help="new labels file; must not exist")
    args = parser.parse_args(argv)

    if args.command == "review":
        from PySide6.QtWidgets import QApplication

        from evaluation.annotation.app import ReviewWindow
        session = open_or_create(args)
        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = ReviewWindow(session)
        window.show()
        return app.exec()
    session = Session(args.session, args.manifest, args.media_root)
    if args.command == "status":
        print(json.dumps({"reviewer_id": session.identity["reviewer_id"], **session.progress(),
                          "next": None}, indent=2))
        return 0
    labels = session.export_labels(args.output)
    print(json.dumps({"output": str(args.output), "items": len(labels["items"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
