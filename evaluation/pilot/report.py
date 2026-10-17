"""Score explicitly selected, saved attempts without loading any model."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from evaluation.pilot.manifest import canonical_digest, file_digest
from evaluation.pilot.metrics import CATEGORIES, THRESHOLDS, aggregate, evaluate_clip
from evaluation.pilot.runner import write_new
from services.analysis.contracts import AnalysisRecord


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_v1(path):
    data = read_json(path)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError(f"Unsupported artifact schema_version: {path}")
    return data


def score_attempts(manifest, attempts):
    manifest.require_ready()
    clips = {clip.clip_id: clip for clip in manifest.clips}
    expected_digest = canonical_digest(manifest.model_dump(mode="json"))
    selected, rows, seen, configurations, environments = [], [], set(), set(), set()
    for directory in sorted(map(Path, attempts)):
        attempt = read_v1(directory / "attempt.json")
        clip_id = attempt["clip_id"]
        if clip_id not in clips or clip_id in seen:
            raise ValueError("Select exactly one attempt per known clip; compare configurations in separate reports")
        seen.add(clip_id)
        if (attempt["manifest_sha256"] != expected_digest or
                canonical_digest(read_json(directory / "manifest.json")) != expected_digest):
            raise ValueError(f"{clip_id}: manifest/annotation identity mismatch")
        configurations.add(attempt["configuration_sha256"])
        config = read_v1(directory / "config.json")
        effective = {k: v for k, v in config.items() if k not in ("schema_version", "origin")}
        if canonical_digest(effective) != attempt["configuration_sha256"]:
            raise ValueError(f"{clip_id}: configuration digest mismatch")
        if (directory / "environment.json").is_file():
            environment = read_v1(directory / "environment.json")
            environments.add(canonical_digest({k: environment.get(k) for k in (
                "git_commit", "source_sha256", "dependencies", "hardware", "ffmpeg_version", "runtime_environment")}))
        if not (directory / "summary.json").is_file():
            selected.append({"clip_id": clip_id, "split": clips[clip_id].split,
                             "attempt_id": attempt["attempt_id"], "status": "interrupted_unknown",
                             "quality_available": False})
            continue
        summary = read_v1(directory / "summary.json")
        if summary["attempt_id"] != attempt["attempt_id"] or summary["clip_id"] != clip_id:
            raise ValueError(f"{clip_id}: summary identity mismatch")
        if summary["status"] not in ("completed", "partial", "failed", "cancelled"):
            raise ValueError(f"{clip_id}: invalid terminal status")
        selected.append({**summary, "split": clips[clip_id].split, "quality_available": False})
        record_path = directory / "record.json"
        if not summary["record_available"]:
            continue
        if not (directory / "environment.json").is_file():
            raise ValueError(f"{clip_id}: missing environment provenance")
        if not record_path.is_file():
            raise ValueError(f"{clip_id}: summary declares a missing record")
        if file_digest(record_path) != summary["record_sha256"]:
            raise ValueError(f"{clip_id}: record digest mismatch")
        record = AnalysisRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
        clip = clips[clip_id]
        if record.status.value == "running":
            raise ValueError(f"{clip_id}: nonterminal analysis record")
        if summary["status"] != record.status.value and summary.get("error_type") is None:
            raise ValueError(f"{clip_id}: record/summary status mismatch")
        # Terminal preflight failures can legitimately lack a media summary/hash.
        if record.media is None:
            continue
        if record.video_fingerprint != f"sha256:{clip.sha256}":
            raise ValueError(f"{clip_id}: record/file identity mismatch")
        if record.settings != config["settings"]:
            raise ValueError(f"{clip_id}: returned record/settings mismatch")
        if not math.isclose(record.media.duration_seconds, clip.duration_seconds, rel_tol=0, abs_tol=1e-6):
            raise ValueError(f"{clip_id}: duration differs from annotation; resolve before scoring")
        selected[-1]["quality_available"] = True
        selected[-1]["record_status"] = record.status.value
        predictions = [s.model_dump(mode="json") for s in record.suggestions]
        for category in (None, *CATEGORIES):
            rows.append({**evaluate_clip(clip, predictions, category), "split": clip.split,
                         "attempt_id": attempt["attempt_id"], "status": summary["status"]})
    if len(configurations) > 1 or len(environments) > 1:
        raise ValueError("Mixed configuration/code/dependencies/hardware: generate separate reports")
    groups = []
    for split in ("tuning", "test"):
        for category in ("binary", *CATEGORIES):
            for population in ("completed_only", "all_available_records"):
                subset = [r for r in rows if r["split"] == split and r["category"] == category
                          and (population != "completed_only" or r["status"] == "completed")]
                groups.append({"split": split, "category": category, "population": population,
                               **aggregate(subset)})
    reliability = {}
    for split in ("tuning", "test"):
        subset = [r for r in selected if r["split"] == split]
        observed = [r for r in subset if "reliability" in r]
        batch_totals = {}
        for key in ("planned_batches", "unprocessed_batches", "unfinished_batches", "completed_batches",
                    "failed_batches", "cancelled_batches", "invalid_responses", "repaired_responses"):
            known = [r["reliability"][key] for r in observed if r["reliability"][key] is not None]
            batch_totals[key] = {"observed_total": sum(known) if known else None,
                                 "observed_attempts": len(known), "unknown_attempts": len(subset) - len(known)}
        reliability[split] = {"selected_attempts": len(subset),
                             **{s: sum(r["status"] == s for r in subset) for s in (
                                 "completed", "partial", "failed", "cancelled", "interrupted_unknown")},
                             "quality_unavailable": sum(not r["quality_available"] for r in subset),
                             "batches": batch_totals}
    return {"schema_version": 1, "manifest_sha256": expected_digest, "primary_iou": 0.5,
            "binary_uncertain_policy": "include all pre-review suggestions as alerts",
            "unselected_clip_ids": sorted(clips.keys() - seen),
            "reliability": reliability, "attempts": selected, "clips": rows, "aggregates": groups}


def save_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "metrics.json", report)
    # Tidy numeric rows, no excerpts/reasons. Nested matching details remain JSON.
    for filename, entries in (("clips.csv", report["clips"]), ("aggregates.csv", report["aggregates"])):
        flattened = []
        for entry in entries:
            base = {k: v for k, v in entry.items() if not isinstance(v, (dict, list))}
            for threshold in THRESHOLDS:
                values = entry["event_metrics"][f"{threshold:.2f}"]
                flattened.append({**base, "iou_threshold": threshold,
                                  **{k: v for k, v in values.items() if k != "matches"}})
        if flattened:
            with (output / filename).open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(flattened[0]))
                writer.writeheader()
                writer.writerows(flattened)
