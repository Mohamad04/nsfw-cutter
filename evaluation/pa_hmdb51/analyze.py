"""Tables and label-free metrics of PA-HMDB51 campaigns (no model or media access).

Inputs: one or more (manifest, campaign) pairs run by evaluation.benchmark.runner with A2 only, and the
output directory of prepare. Outputs (new directory): results/*.results.json (validated ResultsFiles),
predictions.csv, per_video.csv, timings.csv, metrics.json, manual_review.csv and its unblinding key.

No NSFW accuracy figure is derived here: PA-HMDB51 provides privacy attributes, not NSFW labels. Alert
rates are rates of alerts, not false-positive rates. Associations with PA-HMDB51 attributes are
descriptive. Accuracy is computed only by review.score_review, from completed project labels.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
from collections import Counter
from pathlib import Path

from core.time_intervals import intervals_duration
from evaluation.benchmark import runner
from evaluation.benchmark import video_metrics as vm
from evaluation.benchmark.manifest import load_manifest, manifest_digest
from evaluation.benchmark.report import _guard_interval
from evaluation.benchmark.stats import grouped_bootstrap, wilson
from evaluation.pilot.metrics import intersection, union

RESAMPLES = 5000
SEED = 20261022
AUDIT_SEED = "nsfw-cutter/pa-hmdb51/review/v1"
AUDIT_FRACTION = 0.2
AUDIT_MINIMUM = 30
SCOPE_WARNING = ("PA-HMDB51 annotates privacy attributes, not NSFW categories, and kiss/dive videos are expected to "
                 "be mostly NSFW-negative. Alert rates are not false-positive rates and nothing here measures "
                 "detection accuracy; accuracy requires the project review of manual_review.csv.")
REVIEW_COLUMNS = ("review_id", "review_batch", "file_to_watch", "duration_seconds", "reviewer_id", "review_date",
                  "watched_in_full", "nudity", "nudity_context", "sexual_activity", "sexual_context", "video_label",
                  "events", "escalation", "exclusion_reason", "notes")


def _read_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict], columns=None):
    columns = list(columns or (rows[0] if rows else ["item_id"]))
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _distribution(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0}
    return {"n": len(values), "sum": sum(values), "min": values[0], "median": statistics.median(values),
            "p90": values[min(len(values) - 1, round(0.9 * (len(values) - 1)))], "max": values[-1],
            "mean": sum(values) / len(values)}


def _latest_attempts(campaign: Path):
    attempts = {}
    for (item_id, config), directories in runner._attempts(campaign).items():
        attempts[(item_id, config)] = {"directory": directories[-1], "attempts": len(directories)}
    return attempts


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _pa_nudity2_intervals(mapping_rows):
    intervals = {}
    for row in mapping_rows:
        if row["attribute"] == "nudity" and row["value"] == "2" and row["start_seconds"]:
            intervals.setdefault(row["item_id"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    return intervals


DURATION_BANDS = ((0.0, 2.5, "<2.5 s"), (2.5, 7.5, "2.5-7.5 s"), (7.5, float("inf"), ">=7.5 s"))


def duration_band(seconds: float) -> str:
    """Bands of the frozen Balanced coarse rate (0.2 fps, FFmpeg nearest rounding): 0, 1 and >=2 periodic
    frames (measured on synthetic clips on 2026-10-22: 2.467 s gives 0 frames, 2.5 s gives 1, 7.5 s gives 2)."""
    return next(label for low, high, label in DURATION_BANDS if low <= seconds < high)


def coarse_sampling(journal: Path, duration: float, pa2_intervals):
    """What the Marqo gate actually saw, from the attempt journal (observed, not modelled)."""
    frames = []
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("kind") == "coarse_frames":
                frames = [(f["timestamp_seconds"], f["origin"]) for f in entry["frames"]]
    times = sorted(t for t, _ in frames)
    edges = [0.0, *times, duration]
    return {"coarse_frames": len(frames), "coarse_scene_frames": sum(o == "scene" for _, o in frames),
            "coarse_periodic_frames": sum(o != "scene" for _, o in frames),
            "largest_gap_without_coarse_frame_seconds": round(max(b - a for a, b in zip(edges, edges[1:])), 3),
            "coarse_frame_inside_pa_nudity2": any(a <= t < b for t in times for a, b in pa2_intervals)
            if pa2_intervals else None}


def _alert_block(rows, key):
    """Wilson interval plus source-grouped bootstrap of an alert rate; never a false-positive rate."""
    usable = [r for r in rows if r[key] is not None]
    alerts = sum(r[key] for r in usable)
    informative = len({r["group_id"] for r in usable if r[key]})
    bootstrap = grouped_bootstrap([{"group_id": r["group_id"], "alert": r[key]} for r in usable], "group_id",
                                  lambda sample: sum(s["alert"] for s in sample) / len(sample) if sample else None,
                                  resamples=RESAMPLES, seed=SEED)
    return {"analysed_videos": len(usable), "alerted_videos": alerts, "rate_unverified_ci": wilson(alerts, len(usable)),
            "source_grouped_bootstrap": _guard_interval(bootstrap, informative, "at least one alerted video"),
            "alerted_sources": informative, "note": "alert rate over analysed videos; not a false-positive rate"}


def _by(rows, field, key):
    groups = {}
    for row in rows:
        groups.setdefault(str(row[field]), []).append(row)
    return {name: _alert_block(members, key) for name, members in sorted(groups.items())}


def review_sheet(rows, output: Path):
    """Blind review sheet (no prediction, no PA attribute) in a seeded random order, and its key.

    Batch 1 mixes, indistinguishably for the reviewer: every A2 alert, every A0@0.45 alert, every
    PA-HMDB51 video (attributes known) and a pre-declared seeded random audit of the remaining videos
    (AUDIT_FRACTION, at least AUDIT_MINIMUM). Batch 2 holds the rest; reviewing both makes the review
    complete, the only design under which recall, specificity or F1 can be computed.
    """
    # Partial runs (no usable prediction) are reviewed too: under the worst_case policy a positive video the
    # pipeline could not analyse is a miss. The sheet does not reveal which runs failed.
    completed = [r for r in rows if r["status"] in ("completed", "partial")]
    rank = lambda r: hashlib.sha256(f"{AUDIT_SEED}|{r['item_id']}".encode()).hexdigest()  # noqa: E731
    targeted = {r["item_id"]: reason for r in completed for reason in [
        "A2_alert" if r["A2_alert"] else "A0@0.45_alert" if r["A0@0.45_alert"] else
        "pa_hmdb51_annotated" if r["pa_annotated"] == "True" else ""] if reason}
    remaining = sorted((r for r in completed if r["item_id"] not in targeted), key=rank)
    audit_size = min(len(remaining), max(AUDIT_MINIMUM, round(AUDIT_FRACTION * len(remaining))))
    audit = {r["item_id"] for r in remaining[:audit_size]}
    order = random.Random(AUDIT_SEED)
    batches = {1: [r for r in completed if r["item_id"] in targeted or r["item_id"] in audit],
               2: [r for r in completed if r["item_id"] not in targeted and r["item_id"] not in audit]}
    sheet, key = [], []
    for batch, members in batches.items():
        members = sorted(members, key=lambda r: r["item_id"])
        order.shuffle(members)
        for row in members:
            review_id = f"R{len(sheet) + 1:03d}"
            sheet.append({"review_id": review_id, "review_batch": batch,
                          "file_to_watch": row["original_path"], "duration_seconds": row["duration_seconds"]})
            key.append({"review_id": review_id, "item_id": row["item_id"], "review_batch": batch,
                        "selection": targeted.get(row["item_id"]) or ("random_audit" if row["item_id"] in audit
                                                                      else "complement"),
                        "evaluated_sha256": row["evaluated_sha256"]})
    _write_csv(output / "manual_review.csv", sheet, REVIEW_COLUMNS)
    _write_csv(output / "manual_review_key.csv", key)
    return {"rows": len(sheet), "batch_1": len(batches[1]), "batch_2": len(batches[2]),
            "selection_counts": dict(Counter(k["selection"] for k in key)), "audit_seed": AUDIT_SEED,
            "audit_fraction": AUDIT_FRACTION, "audit_minimum": AUDIT_MINIMUM,
            "blind": "no prediction, score or PA-HMDB51 attribute appears in manual_review.csv; the key maps "
                     "review_id to item_id and must be opened only after review"}


def analyze(runs, *, prepared: Path, media_root: Path, pilot_manifest: Path, output: Path):
    output, prepared, media_root = Path(output), Path(prepared), Path(media_root).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "results").mkdir()
    corpus = {r["item_id"]: r for r in _read_csv(prepared / "dataset_manifest.csv")}
    mapping = _read_csv(prepared / "annotation_mapping.csv")
    nudity2 = _pa_nudity2_intervals(mapping)
    videos, predictions, timings, campaigns, warnings = [], [], [], [], Counter()
    for manifest_path, campaign in runs:
        manifest, campaign = load_manifest(manifest_path), Path(campaign)
        identity = _json(campaign / "campaign.json")
        results = runner.collect(manifest_path, campaign, pilot_manifest,
                                 output / "results" / f"{manifest.benchmark_id}.results.json")
        by_item = {r.item_id: r for r in results.results if r.config == "A2"}
        attempts = _latest_attempts(campaign)
        campaigns.append({"benchmark_id": manifest.benchmark_id, "manifest_digest": manifest_digest(manifest),
                          "campaign": str(campaign), "configs": list(runner.campaign_configs(identity)),
                          **{k: identity[k] for k in ("commit", "frozen_baseline", "configuration_sha256",
                                                      "model_revisions", "gpu", "runtime_sha256", "limits")},
                          "evaluation_code": identity["evaluation_code"]["benchmark_sources_sha256"],
                          "uncommitted_evaluation_changes": identity["evaluation_code"]["uncommitted_evaluation_changes"]})
        for item in manifest.evaluable():
            result, info = by_item.get(item.item_id), corpus[item.item_id]
            attempt = attempts.get((item.item_id, "A2"))
            directory = attempt["directory"] if attempt else None
            record = _json(directory / "record.json") if directory else None
            summary = (_json(directory / "summary.json") if directory else None) or {}
            monitor = (_json(directory / "monitor_summary.json") if directory else None) or {}
            for message in (record or {}).get("warnings", []):
                warnings[message.split(":")[0][:120]] += 1
            suggestions = result.suggestions if result else []
            spans = union([(s.start_seconds, min(s.end_seconds, item.duration_seconds)) for s in suggestions],
                          item.duration_seconds)
            pa2 = union(nudity2.get(item.item_id, []), item.duration_seconds)
            a0 = {t: vm.a0_alert(result, t)[0] for t in vm.A0_THRESHOLDS}
            scores = [s.probability for s in (result.marqo_scores if result else []) if s.probability is not None]
            diagnostics = (record or {}).get("provider_diagnostics") or {}
            metrics = (record or {}).get("metrics") or {}
            row = {"item_id": item.item_id, "action": info["action"], "subset": info["subset"],
                   "group_id": item.group_id, "duration_seconds": item.duration_seconds,
                   "status": result.status if result else "not_run", "error_type": result.error_type if result else "",
                   "attempts": attempt["attempts"] if attempt else 0,
                   "A2_alert": vm.pipeline_alert(result), "A0@0.15_alert": a0[0.15], "A0@0.45_alert": a0[0.45],
                   "suggestions": len(suggestions),
                   "categories": "|".join(sorted({s.category for s in suggestions})),
                   "max_final_confidence": max((s.final_confidence for s in suggestions), default=None),
                   "flagged_seconds": round(intervals_duration(spans), 3),
                   "flagged_fraction": round(intervals_duration(spans) / item.duration_seconds, 4),
                   "marqo_frames": len(scores), "marqo_max_probability": max(scores, default=None),
                   "candidate_windows": len((record or {}).get("candidate_windows", [])),
                   "qwen_batches": metrics.get("total_batches"), "qwen_failed_batches": metrics.get("failed_batches"),
                   "qwen_repaired_batches": metrics.get("repaired_batches"),
                   "qwen_device": diagnostics.get("device_mode"), "qwen_quantization": diagnostics.get("quantization"),
                   "pa_annotated": info["pa_annotated"], "pa_max_nudity": info["pa_max_nudity"],
                   "pa_nudity2_seconds": round(intervals_duration(pa2), 3) if info["pa_annotated"] == "True" else None,
                   # Both are normalized unions, so the pairwise overlap counts no second twice.
                   "predicted_overlap_with_pa_nudity2_seconds": round(intersection(spans, pa2), 3)
                   if info["pa_annotated"] == "True" else None,
                   "pa_relationship_identifiable_frames": info["pa_relationship_identifiable_frames"],
                   "pa_review_flag": info["pa_review_flag"], "original_file_name": info["original_file_name"],
                   "original_path": str(media_root / "originals" / info["action"] / info["original_file_name"]),
                   "evaluated_file": item.file_name, "evaluated_sha256": item.sha256,
                   "warnings": len((record or {}).get("warnings", [])), "errors": len((record or {}).get("errors", [])),
                   "error_messages": " | ".join(e[:160] for e in (record or {}).get("errors", [])),
                   "duration_band": duration_band(item.duration_seconds),
                   **coarse_sampling(directory / "observations.jsonl" if directory else Path("-"),
                                     item.duration_seconds, pa2)}
            videos.append(row)
            for s, full in zip(suggestions, (record or {}).get("suggestions", [])):
                predictions.append({"item_id": item.item_id, "action": info["action"], "subset": info["subset"],
                                    "suggestion_id": s.id, "category": s.category,
                                    "start_seconds": s.start_seconds, "end_seconds": s.end_seconds,
                                    "duration_seconds": round(s.end_seconds - s.start_seconds, 3),
                                    "visual_confidence": full.get("visual_confidence"),
                                    "text_confidence": full.get("text_confidence"),
                                    "final_confidence": s.final_confidence,
                                    "evidence_timestamps": "|".join(map(str, full.get("evidence_timestamps", []))),
                                    "reason": full.get("reason", ""), "review_state": full.get("review_state"),
                                    "video_duration_seconds": item.duration_seconds})
            stages = summary.get("stage_seconds") or {}
            timings.append({"item_id": item.item_id, "action": info["action"], "subset": info["subset"],
                            "status": row["status"], "error_type": row["error_type"],
                            "video_duration_seconds": item.duration_seconds,
                            "pipeline_seconds": summary.get("pipeline_seconds"),
                            "worker_seconds": summary.get("worker_seconds"), "wall_seconds": monitor.get("wall_seconds"),
                            "rtf_wall": (monitor["wall_seconds"] / item.duration_seconds)
                            if monitor.get("wall_seconds") else None,
                            "rtf_pipeline": (summary["pipeline_seconds"] / item.duration_seconds)
                            if summary.get("pipeline_seconds") else None,
                            **{f"stage_{k}_seconds": v for k, v in stages.items()},
                            "peak_process_tree_rss_bytes": monitor.get("process_tree_rss_bytes"),
                            "peak_gpu_memory_mib": monitor.get("gpu_memory_mib"),
                            "peak_gpu_utilization_percent": monitor.get("gpu_utilization_percent"),
                            "cpu_mean_percent": (monitor.get("cpu") or {}).get("mean_percent"),
                            "samples_without_process_tree": (monitor.get("process_tree_monitoring") or {})
                            .get("samples_without_rss"),
                            "qwen_loaded": bool(diagnostics), "qwen_batches": row["qwen_batches"],
                            "whisper_backend": summary.get("whisper_backend"), "start_mode": "cold_process"})
    stage_columns = sorted({k for t in timings for k in t if k.startswith("stage_")})
    timing_columns = [k for k in timings[0] if not k.startswith("stage_")] + stage_columns if timings else None
    for t in timings:
        for column in stage_columns:
            t.setdefault(column, None)
    _write_csv(output / "per_video.csv", videos)
    _write_csv(output / "predictions.csv", predictions, None if predictions else [
        "item_id", "action", "subset", "suggestion_id", "category", "start_seconds", "end_seconds",
        "duration_seconds", "visual_confidence", "text_confidence", "final_confidence", "evidence_timestamps",
        "reason", "review_state", "video_duration_seconds"])
    _write_csv(output / "timings.csv", timings, timing_columns)
    review = review_sheet(videos, output)

    completed = [v for v in videos if v["status"] == "completed"]
    done_timings = [t for t in timings if t["status"] == "completed"]
    duration = sum(v["duration_seconds"] for v in completed)
    pilot = [v for v in completed if v["pa_annotated"] == "True"]
    metrics = {
        "scope_warning": SCOPE_WARNING,
        "campaigns": campaigns,
        "corpus": {"prepared_videos": len(corpus), "excluded_at_preparation": sum(r["excluded"] == "True"
                                                                                 for r in corpus.values()),
                   "in_manifests": len(videos), "by_action": dict(Counter(v["action"] for v in videos)),
                   "by_subset": dict(Counter(v["subset"] for v in videos)),
                   "sources": len({v["group_id"] for v in videos}),
                   "analysed_duration_seconds": duration},
        "technical": {
            "videos_attempted": sum(v["status"] != "not_run" for v in videos),
            "status_counts": dict(Counter(v["status"] for v in videos)),
            "error_types": dict(Counter(v["error_type"] for v in videos if v["error_type"])),
            "videos_with_more_than_one_attempt": sum(v["attempts"] > 1 for v in videos),
            "wall_seconds": _distribution([t["wall_seconds"] for t in done_timings]),
            "pipeline_seconds": _distribution([t["pipeline_seconds"] for t in done_timings]),
            "video_duration_seconds": _distribution([v["duration_seconds"] for v in completed]),
            "pooled_rtf_wall": sum(t["wall_seconds"] for t in done_timings) / duration if duration else None,
            "pooled_rtf_pipeline": sum(t["pipeline_seconds"] for t in done_timings) / duration if duration else None,
            "per_video_rtf_wall": _distribution([t["rtf_wall"] for t in done_timings]),
            "stage_seconds": {c[6:-8]: _distribution([t[c] for t in done_timings]) for c in stage_columns},
            "qwen_loaded_videos": sum(t["qwen_loaded"] for t in done_timings),
            "by_qwen_loaded": {str(flag): {"videos": len(group), "wall_seconds": _distribution(
                [t["wall_seconds"] for t in group])} for flag in (True, False)
                for group in [[t for t in done_timings if t["qwen_loaded"] == flag]]},
            "qwen_batches": {"total": sum(v["qwen_batches"] or 0 for v in completed),
                             "failed": sum(v["qwen_failed_batches"] or 0 for v in completed),
                             "repaired": sum(v["qwen_repaired_batches"] or 0 for v in completed)},
            "qwen_placement": dict(Counter(f"{v['qwen_device']}/{v['qwen_quantization']}" for v in completed
                                           if v["qwen_device"])),
            "peak_process_tree_rss_bytes": _distribution([t["peak_process_tree_rss_bytes"] for t in done_timings]),
            "peak_gpu_memory_mib": _distribution([t["peak_gpu_memory_mib"] for t in done_timings]),
            "attempts_without_process_tree_samples": sum(t["peak_process_tree_rss_bytes"] is None for t in done_timings),
            "whisper_backend": dict(Counter(str(t["whisper_backend"]) for t in timings)),
            "record_warnings": dict(warnings), "record_errors": sum(v["errors"] for v in completed),
            "start_mode": "every attempt is a fresh process with cold models (model loading included)",
        },
        "predictions": {
            "events_predicted": sum(v["suggestions"] for v in completed),
            "events_by_category": dict(Counter(p["category"] for p in predictions)),
            "events_by_action": dict(Counter(p["action"] for p in predictions)),
            "videos_with_events_by_category": dict(Counter(c for v in completed for c in v["categories"].split("|") if c)),
            "event_duration_seconds": _distribution([p["duration_seconds"] for p in predictions]),
            "final_confidence": _distribution([p["final_confidence"] for p in predictions]),
            "flagged_fraction_of_alerted_videos": _distribution([v["flagged_fraction"] for v in completed
                                                                if v["A2_alert"]]),
        },
        "label_free_alerts": {
            "definition": "A2: at least one final suggestion (any category, uncertain included). A0@tau: at least "
                          "one coarse-frame Marqo probability >= tau, from the same A2 run.",
            **{key: {"all": _alert_block(completed, f"{key}_alert"), "by_action": _by(completed, "action", f"{key}_alert"),
                     "by_subset": _by(completed, "subset", f"{key}_alert")}
               for key in ("A2", "A0@0.15", "A0@0.45")},
        },
        "privacy_attribute_comparison": {
            "warning": "Descriptive association between alerts and PA-HMDB51 clothing-exposure levels on the "
                       "PA-HMDB51-annotated videos; PA-HMDB51 nudity is not an NSFW label, so these are neither "
                       "true nor false positives.",
            "videos": len(pilot),
            "alerts_by_pa_max_nudity": {level: {k: sum(bool(v[f"{k}_alert"]) for v in group) for k in
                                                ("A2", "A0@0.15", "A0@0.45")} | {"videos": len(group)}
                                        for level in ("0", "1", "2")
                                        for group in [[v for v in pilot if v["pa_max_nudity"] == level]]},
            "pa_nudity2_seconds": sum(v["pa_nudity2_seconds"] or 0 for v in pilot),
            "predicted_seconds_on_pa_videos": sum(v["flagged_seconds"] for v in pilot),
            "predicted_overlap_with_pa_nudity2_seconds": sum(v["predicted_overlap_with_pa_nudity2_seconds"] or 0
                                                             for v in pilot),
        },
        "sampling_study": {
            "note": "Observed coarse frames of the frozen Balanced profile (0.2 fps + scene changes); the campaign "
                    "parameters are unchanged. Partial runs are technical failures, never negatives.",
            "by_duration_band": {label: {
                "videos": len(group), "status_counts": dict(Counter(v["status"] for v in group)),
                "coarse_frames": _distribution([v["coarse_frames"] for v in group if v["status"] == "completed"]),
                "largest_gap_seconds": _distribution([v["largest_gap_without_coarse_frame_seconds"] for v in group
                                                      if v["status"] == "completed"]),
                "A2_alerts": sum(bool(v["A2_alert"]) for v in group),
                "A0@0.15_alerts": sum(bool(v["A0@0.15_alert"]) for v in group)}
                for _, _, label in DURATION_BANDS for group in [[v for v in videos if v["duration_band"] == label]]},
            "pa_nudity2_videos": {"videos": sum(v["coarse_frame_inside_pa_nudity2"] is not None for v in videos),
                                  "completed": sum(v["coarse_frame_inside_pa_nudity2"] is not None
                                                   and v["status"] == "completed" for v in videos),
                                  "with_a_coarse_frame_inside_level2": sum(bool(v["coarse_frame_inside_pa_nudity2"])
                                                                           for v in videos)},
        },
        "binary_detection": {"status": "withheld", "reason": "no validated NSFW reference labels (PA-HMDB51 has "
                             "none); requires the review of manual_review.csv, then score-review"},
        "per_category": {"status": "withheld", "reason": "PA-HMDB51 has no sexual_activity or sexual_context "
                         "attribute and its nudity scale is not the project nudity category"},
        "temporal_localization": {"status": "withheld", "reason": "requires exhaustive reviewed NSFW intervals; "
                                  "PA-HMDB51 intervals describe clothing exposure, not NSFW events"},
        "manual_review": review,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str),
                                         encoding="utf-8")
    return {"output": str(output), "videos": len(videos), "completed": len(completed),
            "alerts_A2": sum(bool(v["A2_alert"]) for v in completed), "events": metrics["predictions"]["events_predicted"]}
