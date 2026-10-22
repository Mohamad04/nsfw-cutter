"""Scores A2 predictions against a project review recorded in manual_review.csv (no model or media access).

Labels follow docs/nsfw_annotation_guide.md (sections 4-7). What is reported depends on the review design:
  - complete review (every analysed video labelled): video-level TP/FP/FN/TN, precision, recall,
    specificity, F1 with Wilson intervals, per-category video-level confusion, and event-level
    localization metrics at IoU 0.25/0.50/0.75;
  - partial review: only the confirmed-alert review (evaluation.benchmark.video_metrics.alert_review)
    and, when every alert is reviewed, the precision of alerts. Recall, specificity and F1 are withheld,
    because the reviewed subset over-represents alerts and is not a random sample.
Uncertain and excluded labels are never scored as negatives; they are counted. Undefined ratios
(for instance recall without any reference positive) are reported as null, never as 0 or 1.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

from evaluation.benchmark import video_metrics as vm
from evaluation.benchmark.stats import wilson
from evaluation.pilot.manifest import Clip, Event, Exclusion
from evaluation.pilot.metrics import aggregate, evaluate_clip

CATEGORIES = ("nudity", "sexual_activity", "sexual_context")
STATES = ("present", "absent", "uncertain")
LABELS = ("positive", "negative", "uncertain", "excluded")
CONTEXTS = ("", "nonsexual_everyday", "nonsexual_medical", "nonsexual_artistic", "nonsexual_educational",
            "sexual", "unclear")
ESCALATIONS = ("", "age_uncertain", "consent_uncertain", "other_sensitive")
EVENT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*:\s*([a-z_]+)\s*$")


PACKAGE_SEED = "nsfw-cutter/pa-hmdb51/blind-package/v1"


def blind_package(manifest_path: Path, media_root: Path, output: Path, seed: str = PACKAGE_SEED) -> dict:
    """Review package built from a benchmark manifest only: no prediction, score, alert or PA-HMDB51 attribute
    is read. Each video is copied bit for bit under an anonymous name (R001.mkv, ...) so that file names,
    which reveal the HMDB51 action and source, do not prime the reviewer. Order: sha256(seed | item_id).
    """
    import hashlib
    import shutil

    from evaluation.benchmark.manifest import load_manifest, manifest_digest
    from evaluation.pilot.manifest import file_digest

    manifest, output = load_manifest(manifest_path), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "media").mkdir()
    items = sorted(manifest.evaluable(), key=lambda i: hashlib.sha256(f"{seed}|{i.item_id}".encode()).hexdigest())
    sheet, key = [], []
    for index, item in enumerate(items, 1):
        review_id = f"R{index:03d}"
        source = Path(media_root) / item.file_name
        if file_digest(source) != item.sha256:
            raise ValueError(f"{item.item_id}: media does not match the manifest")
        target = output / "media" / f"{review_id}{source.suffix}"
        shutil.copyfile(source, target)
        if file_digest(target) != item.sha256:
            raise ValueError(f"{review_id}: copy differs from the source")
        sheet.append({"review_id": review_id, "review_batch": 1, "file_to_watch": f"media/{target.name}",
                      "duration_seconds": item.duration_seconds})
        key.append({"review_id": review_id, "item_id": item.item_id, "evaluated_sha256": item.sha256,
                    "selection": f"manifest:{manifest.benchmark_id}"})
    columns = ("review_id", "review_batch", "file_to_watch", "duration_seconds", "reviewer_id", "review_date",
               "watched_in_full", "nudity", "nudity_context", "sexual_activity", "sexual_context", "video_label",
               "events", "escalation", "exclusion_reason", "notes")
    for name, rows, fields in (("manual_review.csv", sheet, columns), ("manual_review_key.csv", key, list(key[0]))):
        with (output / name).open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    record = {"benchmark_id": manifest.benchmark_id, "manifest_digest": manifest_digest(manifest), "seed": seed,
              "videos": len(sheet), "prediction_independent": True,
              "empty_sheet_sha256": file_digest(output / "manual_review.csv"),
              "key_sha256": file_digest(output / "manual_review_key.csv")}
    (output / "package.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _read(path: Path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_events(text: str, duration: float):
    events = []
    for part in filter(None, (p.strip() for p in (text or "").split(";"))):
        match = EVENT.match(part)
        if not match or match.group(3) not in CATEGORIES:
            raise ValueError(f"event {part!r}: expected start-end:category with a category in {CATEGORIES}")
        start, end = float(match.group(1)), min(float(match.group(2)), duration)
        if not 0 <= start < end:
            raise ValueError(f"event {part!r}: empty or reversed interval")
        events.append((start, end, match.group(3)))
    return events


def validate_row(row: dict, duration: float) -> list[str]:
    """Consistency rules of guide sections 5-7; returns problems (an empty list is a usable label)."""
    problems = []
    states = {c: row.get(c, "").strip() for c in CATEGORIES}
    label = row.get("video_label", "").strip()
    if label not in LABELS:
        return [f"video_label {label!r} not in {LABELS}"]
    if row.get("escalation", "").strip() not in ESCALATIONS:
        problems.append("unknown escalation")
    if row.get("nudity_context", "").strip() not in CONTEXTS:
        problems.append("unknown nudity_context")
    if label == "excluded":
        if not (row.get("exclusion_reason", "").strip() or row.get("escalation", "").strip()):
            problems.append("excluded without exclusion_reason or escalation")
        return problems
    if any(s not in STATES for s in states.values()):
        problems.append(f"category states must be in {STATES}")
        return problems
    present = [c for c, s in states.items() if s == "present"]
    uncertain = [c for c, s in states.items() if s == "uncertain"]
    full = row.get("watched_in_full", "").strip().lower()
    if full not in ("yes", "no"):
        problems.append("watched_in_full must be yes or no")
    if label == "positive" and not present:
        problems.append("positive without a present category")
    if label != "positive" and present:
        problems.append("a present category requires video_label positive")
    if label == "negative" and (uncertain or full != "yes"):
        problems.append("negative requires every category absent and watched_in_full yes")
    if label == "uncertain" and not uncertain and full == "yes":
        problems.append("uncertain requires an uncertain category or an incomplete viewing")
    try:
        events = parse_events(row.get("events", ""), duration)
    except ValueError as exc:
        return problems + [str(exc)]
    for start, end, category in events:
        if states[category] == "absent":
            problems.append(f"event {start}-{end} uses absent category {category}")
    if label == "negative" and events:
        problems.append("a negative video has no event")
    return problems


def _clip(item_id: str, duration: float, row: dict) -> Clip | None:
    """Exhaustive reference timeline, or None when the viewing was incomplete or a present category has
    no interval (its timing is then unknown). Intervals of uncertain categories are masked as ambiguous."""
    if row["watched_in_full"].strip().lower() != "yes" or row["video_label"] not in ("positive", "negative"):
        return None
    states = {c: row[c].strip() for c in CATEGORIES}
    parsed = parse_events(row.get("events", ""), duration)
    if any(states[c] == "present" and not any(e[2] == c for e in parsed) for c in CATEGORIES):
        return None
    events, masks = [], []
    for index, (start, end, category) in enumerate(parsed):
        if states[category] == "present":
            events.append(Event(event_id=f"e{index}", start_seconds=start, end_seconds=end,
                                categories=[category], notes=""))
        else:
            masks.append(Exclusion(exclusion_id=f"x{index}", start_seconds=start, end_seconds=end,
                                   kind="ambiguous", reason=f"{category} uncertain"))
    return Clip.model_construct(clip_id=item_id, source_video_id=None, file_path=item_id, source_offset_seconds=0.0,
                                split="test", duration_seconds=duration, sha256=None, media_metadata={},
                                annotation_version="manual_review", exhaustive=True, events=events,
                                excluded_intervals=masks)


def score_review(review_csv: Path, analysis_dir: Path, key_csv: Path | None = None) -> dict:
    """key_csv defaults to the analysis' own key; pass a blind package key to score one prediction-independent
    review against the predictions of any analysis of the same videos (e.g. two pipeline versions)."""
    analysis_dir = Path(analysis_dir)
    sheet = {r["review_id"]: r for r in _read(review_csv)}
    key = {r["review_id"]: r for r in _read(key_csv or analysis_dir / "manual_review_key.csv")}
    videos = {r["item_id"]: r for r in _read(analysis_dir / "per_video.csv")}
    predictions = {}
    for p in _read(analysis_dir / "predictions.csv"):
        predictions.setdefault(p["item_id"], []).append(p)
    if set(sheet) != set(key):
        raise ValueError("manual_review.csv does not match manual_review_key.csv (rows added or removed)")

    rows, invalid, excluded, temporal = [], {}, Counter(), []
    for review_id, entry in key.items():
        row, video = sheet[review_id], videos[entry["item_id"]]
        duration = float(video["duration_seconds"])
        alert = {"True": True, "False": False}.get(video["A2_alert"])
        base = {"item_id": entry["item_id"], "group_id": video["group_id"], "alert": alert,
                "duration_seconds": duration, "selection": entry["selection"], "action": video["action"]}
        if not row.get("video_label", "").strip():
            rows.append({**base, "label": "missing", "review_basis": "unreviewed"})
            continue
        problems = validate_row(row, duration)
        if problems:
            invalid[review_id] = problems
            rows.append({**base, "label": "missing", "review_basis": "unreviewed"})
            continue
        if row["video_label"] == "excluded":
            excluded[row.get("escalation") or row.get("exclusion_reason") or "excluded"] += 1
            continue
        basis = {"A2_alert": "alert_triggered", "random_audit": "random_audit"}.get(entry["selection"], "targeted")
        rows.append({**base, "label": row["video_label"], "review_basis": basis,
                     "states": {c: row[c].strip() for c in CATEGORIES}, "row": row})

    reviewed = [r for r in rows if r["label"] != "missing"]
    complete = bool(rows) and len(reviewed) == len(rows)
    alerted = [r for r in rows if r["alert"]]
    report = {"status": "complete_review" if complete else "partial_review",
              "rows": len(key), "reviewed": len(reviewed), "excluded_by_reason": dict(excluded),
              "invalid_rows": invalid, "labels": dict(Counter(r["label"] for r in rows)),
              "review_basis": dict(Counter(r["review_basis"] for r in rows)),
              "single_reviewer": len({sheet[i].get("reviewer_id", "").strip() for i in sheet
                                      if sheet[i].get("video_label", "").strip()}) <= 1,
              "alert_review": vm.alert_review(rows)}
    labelled_alerts = [r for r in alerted if r["label"] in ("positive", "negative")]
    if alerted and all(r["label"] != "missing" for r in alerted):
        positives = sum(r["label"] == "positive" for r in labelled_alerts)
        report["precision_of_alerts_ci"] = wilson(positives, len(labelled_alerts))
        report["precision_of_alerts_note"] = ("every alert reviewed: precision depends only on alerted videos and is "
                                              "valid under partial review; uncertain alerts are not scored")
    if report["single_reviewer"]:
        report["annotation_warning"] = "single reviewer: no inter-annotator agreement; labels are provisional"

    # Category errors on confirmed true alerts (valid under any design: they describe those videos only).
    category_rows = []
    for r in labelled_alerts:
        if r["label"] != "positive":
            continue
        predicted = {p["category"] for p in predictions.get(r["item_id"], [])} - {"uncertain"}
        reference = {c for c, s in r["states"].items() if s == "present"}
        category_rows.append({"item_id": r["item_id"], "predicted": sorted(predicted), "reference": sorted(reference),
                              "exact": predicted == reference, "missing": sorted(reference - predicted),
                              "extra": sorted(predicted - reference),
                              "only_uncertain_predicted": not predicted})
    report["category_errors_on_true_alerts"] = {"videos": len(category_rows),
                                                "exact_category_match": sum(c["exact"] for c in category_rows),
                                                "details": category_rows}

    # Temporal localization on reviewed positive videos with exhaustive intervals (describes those videos only).
    for r in reviewed:
        clip = _clip(r["item_id"], r["duration_seconds"], r["row"])
        if clip is None:
            continue
        preds = [{"id": p["suggestion_id"], "start_seconds": float(p["start_seconds"]),
                  "end_seconds": min(float(p["end_seconds"]), r["duration_seconds"]), "category": p["category"]}
                 for p in predictions.get(r["item_id"], []) if float(p["start_seconds"]) < r["duration_seconds"]]
        temporal.append({"label": r["label"], "binary": evaluate_clip(clip, preds),
                         **{c: evaluate_clip(clip, preds, c) for c in CATEGORIES}})
    positives_timed = [t for t in temporal if t["label"] == "positive"]
    report["localization_on_reviewed_positives"] = (
        {"videos": len(positives_timed), "binary": aggregate([t["binary"] for t in positives_timed]),
         "note": "event matching, coverage and boundary errors on reviewed positive videos with exhaustive "
                 "intervals; describes these videos only"} if positives_timed else {"videos": 0})

    if not complete:
        report["withheld"] = ("recall, specificity, F1 and event-level false-alert rates require a complete review "
                              "of every analysed video (batches 1 and 2); the reviewed subset is not random")
        return report
    report["video_level"] = {policy: {**(counts := vm.confusion(rows, policy)), **vm.video_metrics(counts)}
                             for policy in vm.FAILURE_POLICIES}
    report["video_level_by_action"] = {action: vm.video_metrics(vm.confusion([r for r in rows if r["action"] == action]))
                                       for action in sorted({r["action"] for r in rows})}
    per_category = {}
    for category in CATEGORIES:
        category_rows = []
        for r in rows:
            state = r["states"][category]
            if state == "uncertain" or r["alert"] is None:
                continue
            predicted = any(p["category"] == category for p in predictions.get(r["item_id"], []))
            category_rows.append({"label": "positive" if state == "present" else "negative", "alert": predicted})
        per_category[category] = {**(counts := vm.confusion(category_rows)), **vm.video_metrics(counts)}
    report["classification_by_category"] = per_category
    report["event_level"] = ({"videos": len(temporal),
                              "binary": aggregate([t["binary"] for t in temporal]),
                              **{c: aggregate([t[c] for t in temporal]) for c in CATEGORIES}}
                             if temporal else {"videos": 0})
    if not report["labels"].get("positive"):
        report["scope_warning"] = ("no reference positive: recall and F1 are undefined; only specificity and "
                                   "false alerts are measured, which is not a complete evaluation of the detector")
    return report
