"""Reference labels recorded after a campaign, applied to its manifest without changing the campaign.

A ResultsFile is bound to the digest of the manifest it was run with. Human labels arrive later, so they
are kept in a separate labels file bound to that same base digest; scoring applies them in memory and
validates the labelled manifest against the full benchmark contract (manifest.py).
"""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.benchmark.manifest import BenchmarkManifest, manifest_digest

ITEM_FIELDS = ("video_label", "review_basis", "category_labels", "temporal", "excluded", "exclusion_reason")


def load_labels(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def apply_reference_labels(manifest: BenchmarkManifest, labels: dict, split: str = "test"):
    """Labelled manifest (validated) and the provenance record written to the report."""
    if labels.get("kind") != "nsfw_cutter_reference_labels" or labels.get("schema_version") != 1:
        raise ValueError("not a reference labels file")
    if labels["benchmark_id"] != manifest.benchmark_id or labels["base_manifest_digest"] != manifest_digest(manifest):
        raise ValueError("labels were recorded for another manifest version")
    entries = labels["items"]
    evaluable = {item.item_id for item in manifest.evaluable(split)}
    if set(entries) != evaluable:
        raise ValueError("labels must cover exactly the evaluable items of the split")
    data = manifest.model_dump(mode="json")
    for item in data["items"]:
        entry = entries.get(item["item_id"])
        if entry is None:
            continue
        if entry["sha256"] != item["sha256"]:
            raise ValueError(f"{item['item_id']}: labels were recorded for another media file")
        item.update({key: entry[key] for key in ITEM_FIELDS})
        item["provenance"] = {**item["provenance"], "nudity_context": entry.get("nudity_context"),
                              "reference_record_sha256": entry["record"]["sha256"],
                              "reference_reviewers": list(labels.get("reviewers") or [])}
    data["annotation"] = labels["annotation"]
    labelled = BenchmarkManifest.model_validate(data)
    return labelled, {"session_id": labels.get("session_id"), "reviewers": labels.get("reviewers"),
                      "single_reviewer": bool(labels.get("single_reviewer")), "guide_sha256": labels.get("guide_sha256"),
                      "labelled_manifest_digest": manifest_digest(labelled)}
