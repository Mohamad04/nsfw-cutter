"""Offline single-reviewer annotation session: drafts, locked records, audit trail and label export.

Layout of a session directory (local only, never versioned):
  session.json                   identity: manifest, guide, reviewer, review order (written once)
  drafts/<item>.json             work in progress, replaced atomically on every save
  locked/<item>/v001.json        locked records, never overwritten; a correction is a new version with a reason
  audit.jsonl                    append-only log (session created, media verified, drafts, locks)

The session reads only the benchmark manifest and the media files. It never opens campaign, results or
score directories, so no A0/A1/A2 output can reach the reviewer; it imports no model code.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path

from evaluation.annotation.record import (
    CATEGORIES,
    MEDIA_EXCLUSIONS,
    empty_record,
    validate,
    video_label,
)
from evaluation.benchmark.atomic import write_atomic
from evaluation.benchmark.manifest import load_manifest, manifest_digest
from evaluation.pilot.manifest import file_digest

# The only manifest fields the review interface may see: no provenance (stratum, scene, Charades
# activity hints), no group, no label, no pilot marker.
VISIBLE_FIELDS = ("position", "total", "duration_seconds", "has_audio")


def _now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _replace_atomic(path: Path, value):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class LockedError(PermissionError):
    pass


class Session:
    def __init__(self, directory: Path, manifest_path: Path, media_root: Path):
        self.directory, self.media_root = Path(directory), Path(media_root)
        self.identity = json.loads((self.directory / "session.json").read_text(encoding="utf-8"))
        manifest_path = Path(manifest_path)
        if file_digest(manifest_path) != self.identity["manifest_sha256"]:
            raise ValueError("this session was created for another manifest file")
        self.manifest = load_manifest(manifest_path)
        self._items = {item.item_id: item for item in self.manifest.evaluable(self.identity["split"])}
        if sorted(self._items) != sorted(self.identity["order"]):
            raise ValueError("the manifest's evaluable items differ from the session order")
        self._verified = {}

    # ------------------------------------------------------------------ creation

    @classmethod
    def create(cls, directory: Path, manifest_path: Path, media_root: Path, *, reviewer_id: str, guide_path: Path,
               seed: int, split: str = "test"):
        directory = Path(directory)
        if not reviewer_id.strip() or any(c in reviewer_id for c in "/\\:"):
            raise ValueError("reviewer_id must be a plain pseudonym")
        if directory.exists() and any(directory.iterdir()):
            raise FileExistsError(f"{directory} is not empty; open the existing session instead")
        manifest = load_manifest(manifest_path)
        items = manifest.evaluable(split)
        missing = [i.item_id for i in items if not i.file_name or not i.sha256 or not i.duration_seconds]
        if missing:
            raise ValueError("items without file name, SHA-256 or duration: " + ", ".join(missing[:10]))
        order = [i.item_id for i in items]
        random.Random(seed).shuffle(order)
        directory.mkdir(parents=True, exist_ok=True)
        for sub in ("drafts", "locked"):
            (directory / sub).mkdir()
        guide_path = Path(guide_path)
        write_atomic(directory / "session.json", {
            "schema_version": 1, "session_id": uuid.uuid4().hex, "created_utc": _now(),
            "reviewer_id": reviewer_id.strip(), "single_reviewer": True,
            "manifest_path": str(Path(manifest_path).resolve()), "manifest_sha256": file_digest(Path(manifest_path)),
            "manifest_digest": manifest_digest(manifest), "benchmark_id": manifest.benchmark_id, "split": split,
            "guide_path": str(guide_path), "guide_sha256": file_digest(guide_path),
            "order_seed": seed, "order": order})
        session = cls(directory, manifest_path, media_root)
        session._audit("session_created", None, {"items": len(order), "seed": seed})
        return session

    # ------------------------------------------------------------------ review

    @property
    def order(self):
        return list(self.identity["order"])

    def view(self, item_id: str):
        """What the interface may display about an item (see VISIBLE_FIELDS) plus the local media path."""
        item = self._items[item_id]
        return {"position": self.order.index(item_id) + 1, "total": len(self.order),
                "duration_seconds": item.duration_seconds, "has_audio": bool(item.has_audio),
                "media_path": str((self.media_root / item.file_name).resolve())}

    def verify_media(self, item_id: str) -> bool:
        if item_id not in self._verified:
            item = self._items[item_id]
            path = self.media_root / item.file_name
            ok = path.is_file() and file_digest(path) == item.sha256
            self._verified[item_id] = ok
            self._audit("media_verified" if ok else "media_sha256_mismatch", item_id, {})
        return self._verified[item_id]

    def versions(self, item_id: str):
        folder = self.directory / "locked" / item_id
        return sorted(folder.glob("v*.json")) if folder.is_dir() else []

    def is_locked(self, item_id: str) -> bool:
        return bool(self.versions(item_id))

    def load(self, item_id: str):
        """(record, state): the latest locked version, else the draft, else an empty record."""
        versions = self.versions(item_id)
        if versions:
            return json.loads(versions[-1].read_text(encoding="utf-8"))["record"], "locked"
        draft = self.directory / "drafts" / f"{item_id}.json"
        if draft.exists():
            return json.loads(draft.read_text(encoding="utf-8")), "draft"
        item = self._items[item_id]
        return empty_record(item_id, item.sha256, item.duration_seconds, bool(item.has_audio)), "new"

    def _check_identity(self, record):
        item = self._items.get(record.get("item_id"))
        if item is None or record.get("sha256") != item.sha256:
            raise ValueError("record does not match a manifest item")

    def save_draft(self, record):
        self._check_identity(record)
        if self.is_locked(record["item_id"]):
            raise LockedError(f"{record['item_id']} is locked; record a correction instead")
        _replace_atomic(self.directory / "drafts" / f"{record['item_id']}.json", record)

    def lock(self, record, *, amendment_reason: str = ""):
        """Locks a valid record as a new, never-overwritten version. A second version needs a reason."""
        self._check_identity(record)
        problems = validate(record)
        if problems:
            raise ValueError("; ".join(problems))
        item_id, versions = record["item_id"], self.versions(record["item_id"])
        if versions and not amendment_reason.strip():
            raise LockedError(f"{item_id} is already locked; a correction needs a reason")
        if not versions and amendment_reason.strip():
            raise ValueError("an amendment reason only applies to an already locked record")
        media_exclusion = video_label(record) == "excluded" and record["exclusion_reason"] in MEDIA_EXCLUSIONS
        if not versions and not media_exclusion and not self.verify_media(item_id):
            raise ValueError(f"{item_id}: media SHA-256 does not match; record a sha256_mismatch exclusion")
        folder = self.directory / "locked" / item_id
        folder.mkdir(exist_ok=True)
        path = folder / f"v{len(versions) + 1:03d}.json"
        previous = hashlib.sha256(versions[-1].read_bytes()).hexdigest() if versions else None
        write_atomic(path, {"locked_utc": _now(), "reviewer_id": self.identity["reviewer_id"],
                            "session_id": self.identity["session_id"], "guide_sha256": self.identity["guide_sha256"],
                            "version": len(versions) + 1, "amends_sha256": previous,
                            "amendment_reason": amendment_reason.strip(), "video_label": video_label(record),
                            "record": record})
        draft = self.directory / "drafts" / f"{item_id}.json"
        if draft.exists():
            draft.unlink()
        self._audit("amended" if versions else "locked", item_id,
                    {"version": len(versions) + 1, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return path

    def progress(self):
        locked = [i for i in self.order if self.is_locked(i)]
        drafts = [i for i in self.order if not self.is_locked(i) and (self.directory / "drafts" / f"{i}.json").exists()]
        return {"total": len(self.order), "locked": len(locked), "drafts": len(drafts),
                "remaining": len(self.order) - len(locked),
                "next": next((i for i in self.order if not self.is_locked(i)), None)}

    def _audit(self, event, item_id, details):
        line = json.dumps({"utc": _now(), "event": event, "item_id": item_id,
                           "reviewer_id": self.identity["reviewer_id"], **details}, ensure_ascii=False)
        with (self.directory / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    # ------------------------------------------------------------------ export

    def export_labels(self, output: Path):
        """Reference labels for every evaluable item, bound to the base manifest digest (complete review only)."""
        remaining = [i for i in self.order if not self.is_locked(i)]
        if remaining:
            raise ValueError(f"{len(remaining)} item(s) not locked yet: review must be complete before export")
        items = {}
        for item_id in sorted(self.order):
            path = self.versions(item_id)[-1]
            locked = json.loads(path.read_text(encoding="utf-8"))
            items[item_id] = {**to_reference(locked["record"], self.manifest.track),
                              "sha256": self._items[item_id].sha256,
                              "record": {"path": str(path.relative_to(self.directory)), "version": locked["version"],
                                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
        reviewer = self.identity["reviewer_id"]
        labels = {
            "schema_version": 1, "kind": "nsfw_cutter_reference_labels", "benchmark_id": self.manifest.benchmark_id,
            "base_manifest_digest": self.identity["manifest_digest"], "split": self.identity["split"],
            "session_id": self.identity["session_id"], "reviewers": [reviewer], "single_reviewer": True,
            "guide_sha256": self.identity["guide_sha256"],
            "annotation": {"version": f"single-reviewer/{self.identity['session_id'][:12]}",
                           "source": "project_annotators", "guideline": f"docs/nsfw_annotation_guide.md "
                           f"sha256 {self.identity['guide_sha256']}",
                           "notes": f"single reviewer {reviewer}; no inter-annotator reliability; review blind to "
                                    "model outputs inside the tool only"},
            "items": items}
        write_atomic(Path(output), labels)
        self._audit("exported", None, {"output": str(output)})
        return labels


def to_reference(record, track: str):
    """Maps a locked human record onto the benchmark Item fields (uncertain categories become unknown)."""
    label = video_label(record)
    states = record["categories"]
    category_labels = {c: {"present": "present", "absent": "absent"}.get(states[c], "unknown") for c in CATEGORIES}
    excluded, reason, temporal = False, "", None
    if label == "excluded":
        excluded = True
        reason = record["exclusion_reason"].strip() or record["escalation"]
        label = "positive" if any(s == "present" for s in states.values()) else "uncertain"
    else:
        if label == "positive" and track == "technical":
            # Protocol: NSFW discovered in the presumed-negative corpus is excluded and still counted.
            excluded, reason = True, "nsfw_discovered"
        if record["watched_in_full"]:
            events = [e for e in record["events"] if states[e["category"]] == "present"]
            ambiguous = [e for e in record["events"] if states[e["category"]] == "uncertain"]
            temporal = {
                "binary_exhaustive": True,
                "exhaustive_categories": [c for c in CATEGORIES if states[c] in ("present", "absent")],
                "events": [{"event_id": f"{record['item_id']}-e{n}", "start_seconds": float(e["start_seconds"]),
                            "end_seconds": float(e["end_seconds"]), "categories": [e["category"]], "notes": ""}
                           for n, e in enumerate(events, 1)],
                "excluded_intervals": [{"exclusion_id": f"{record['item_id']}-u{n}", "kind": "ambiguous",
                                        "start_seconds": float(e["start_seconds"]),
                                        "end_seconds": float(e["end_seconds"]),
                                        "reason": f"reviewer uncertain: {e['category']}"}
                                       for n, e in enumerate(ambiguous, 1)]}
    return {"video_label": label, "review_basis": "complete", "category_labels": category_labels,
            "temporal": temporal, "excluded": excluded, "exclusion_reason": reason,
            "nudity_context": record["nudity_context"]}
