"""Offline benchmark report: video-level metrics for A0/A1/A2, events where supported, paired tests."""
from __future__ import annotations

import statistics

from evaluation.benchmark import events, video_metrics as vm
from evaluation.benchmark.manifest import BenchmarkManifest, manifest_digest
from evaluation.benchmark.results import ResultsFile
from evaluation.benchmark.stats import grouped_bootstrap, holm, mcnemar_exact

DEFAULT_RESAMPLES = 5000
DEFAULT_SEED = 20261019


def _decisions(manifest: BenchmarkManifest, results: ResultsFile, split: str):
    by_key = {(r.item_id, r.config): r for r in results.results}
    rows, fallback_scores = {}, {}
    for item in manifest.evaluable(split):
        a1, a2 = by_key.get((item.item_id, "A1")), by_key.get((item.item_id, "A2"))
        base = {"item_id": item.item_id, "group_id": item.group_id, "label": item.video_label,
                "review_basis": item.review_basis, "duration_seconds": item.duration_seconds}
        rows.setdefault("A1", []).append({**base, "alert": vm.pipeline_alert(a1)})
        rows.setdefault("A2", []).append({**base, "alert": vm.pipeline_alert(a2)})
        for tau in vm.A0_THRESHOLDS:
            alert, fallbacks = vm.a0_alert(a2, tau)
            rows.setdefault(f"A0@{tau:.2f}", []).append({**base, "alert": alert})
            fallback_scores[f"A0@{tau:.2f}"] = fallback_scores.get(f"A0@{tau:.2f}", 0) + fallbacks
    return rows, fallback_scores


def _video_section(rows, resamples, seed):
    section = {}
    for policy in vm.FAILURE_POLICIES:
        counts = vm.confusion(rows, policy)
        section[policy] = {"counts": counts, "metrics": vm.video_metrics(counts)}
    scored = [r for r in rows if r["alert"] is not None and r["label"] in ("positive", "negative")]
    section["bootstrap"] = {
        "f1": grouped_bootstrap(scored, "group_id", vm.f1_of, resamples=resamples, seed=seed),
        "balanced_accuracy": grouped_bootstrap(scored, "group_id", vm.balanced_accuracy_of,
                                               resamples=resamples, seed=seed),
        "specificity": grouped_bootstrap(scored, "group_id", vm.specificity_of, resamples=resamples, seed=seed),
    }
    return section


def _paired(rows_x, rows_y, name_x, name_y, resamples, seed):
    """Items scored by both configurations with a known label; b = only x correct, c = only y correct."""
    y_by_item = {r["item_id"]: r for r in rows_y}
    pairs = []
    for x in rows_x:
        y = y_by_item[x["item_id"]]
        if x["label"] in ("positive", "negative") and x["alert"] is not None and y["alert"] is not None:
            truth = x["label"] == "positive"
            pairs.append({"item_id": x["item_id"], "group_id": x["group_id"], "label": x["label"],
                          "x": x["alert"], "y": y["alert"], "x_correct": x["alert"] == truth,
                          "y_correct": y["alert"] == truth})

    def delta(metric):
        def statistic(sample):
            first = metric([{"label": p["label"], "alert": p["x"]} for p in sample])
            second = metric([{"label": p["label"], "alert": p["y"]} for p in sample])
            return None if first is None or second is None else second - first
        return statistic

    b = sum(p["x_correct"] and not p["y_correct"] for p in pairs)
    c = sum(p["y_correct"] and not p["x_correct"] for p in pairs)
    return {"first": name_x, "second": name_y, "paired_items": len(pairs),
            "paired_groups": len({p["group_id"] for p in pairs}),
            "mcnemar": mcnemar_exact(b, c),
            "delta_f1_second_minus_first": grouped_bootstrap(pairs, "group_id", delta(vm.f1_of),
                                                             resamples=resamples, seed=seed),
            "delta_balanced_accuracy_second_minus_first": grouped_bootstrap(
                pairs, "group_id", delta(vm.balanced_accuracy_of), resamples=resamples, seed=seed)}


def _runtime(results: ResultsFile, manifest: BenchmarkManifest, split: str):
    durations = {i.item_id: i.duration_seconds for i in manifest.evaluable(split)}
    summary = {}
    for config in ("A1", "A2"):
        for mode in ("cold_process", "warm_process"):
            runs = [r for r in results.results if r.config == config and r.item_id in durations
                    and r.start_mode == mode and r.status == "completed" and r.pipeline_seconds is not None]
            if not runs:
                continue
            seconds = sorted(r.pipeline_seconds for r in runs)
            video = [durations[r.item_id] for r in runs if durations[r.item_id]]
            peaks_rss = [r.peak_process_rss_bytes for r in runs if r.peak_process_rss_bytes is not None]
            peaks_gpu = [r.peak_gpu_memory_mib for r in runs if r.peak_gpu_memory_mib is not None]
            quartiles = statistics.quantiles(seconds, n=4) if len(seconds) > 1 else [seconds[0]] * 3
            summary[f"{config}/{mode}"] = {
                "runs": len(runs), "median_pipeline_seconds": statistics.median(seconds),
                "iqr_pipeline_seconds": [quartiles[0], quartiles[2]],
                # Pooled RTF: total compute over total media, not a mean of per-video ratios.
                "pooled_rtf": sum(r.pipeline_seconds for r in runs if durations[r.item_id]) / sum(video)
                if len(video) == len(runs) and sum(video) else None,
                "max_peak_process_rss_bytes": max(peaks_rss) if peaks_rss else None,
                "max_peak_gpu_memory_mib": max(peaks_gpu) if peaks_gpu else None,
                "os_file_cache": sorted({r.os_file_cache for r in runs})}
    return summary


def score(manifest: BenchmarkManifest, results: ResultsFile, *, split: str = "test",
          resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED):
    digest = manifest_digest(manifest)
    results.check_against(manifest, digest)
    items = manifest.evaluable(split)
    rows, fallbacks = _decisions(manifest, results, split)
    labels = [item.video_label for item in items]
    report = {
        "benchmark_id": manifest.benchmark_id, "manifest_digest": digest, "track": manifest.track,
        "split": split, "dataset": manifest.dataset.model_dump(mode="json"),
        "annotation": manifest.annotation.model_dump(mode="json"),
        "environment": results.environment.model_dump(mode="json"),
        "sample_sizes": {
            "items_in_split": sum(i.split == split for i in manifest.items),
            "excluded": {i.item_id: i.exclusion_reason for i in manifest.items if i.split == split and i.excluded},
            "evaluable": len(items), "groups": len({i.group_id for i in items}),
            **{label: labels.count(label) for label in ("positive", "negative", "uncertain", "missing")}},
        "decision_rules": {"pipeline": "alert when a completed run returns at least one final suggestion",
                           "a0": "alert when a coarse-frame Marqo probability >= tau; fallback scores ignored",
                           "a0_fallback_scores_ignored": fallbacks},
        "video_level": {name: _video_section(config_rows, resamples, seed) for name, config_rows in rows.items()},
        "runtime": _runtime(results, manifest, split),
        "per_video": [{"item_id": r["item_id"], "group_id": r["group_id"], "label": r["label"],
                       **{name: next(x["alert"] for x in rows[name] if x["item_id"] == r["item_id"])
                          for name in rows}} for r in rows["A2"]],
    }
    if manifest.track == "technical" or not labels.count("positive"):
        report["scope_warning"] = ("No positive reference labels: only specificity, false-alert rates and "
                                   "runtime are measured. This is not a complete NSFW accuracy evaluation.")
    verification = manifest.verification(split)
    report["verification"] = verification
    report["alert_review"] = {name: vm.alert_review(config_rows) for name, config_rows in rows.items()}
    if not verification["complete"]:
        reason = ("reference labels do not cover every evaluable item (verification by alert review and/or "
                  "random audit is not a random sample): specificity, recall, F1 and paired accuracy tests "
                  "are withheld; see alert_review")
        report["video_level"] = {"withheld": reason}
        report["paired_comparisons"] = {"withheld": reason}
        report["event_level"] = _event_section(items, results, resamples, seed)
        return report
    comparisons = [("A1", "A2")] + [(f"A0@{tau:.2f}", target) for tau in vm.A0_THRESHOLDS for target in ("A1", "A2")]
    paired = {f"{x}_vs_{y}": _paired(rows[x], rows[y], x, y, resamples, seed) for x, y in comparisons}
    adjusted = holm({name: value["mcnemar"]["p_value"] for name, value in paired.items()})
    for name, value in paired.items():
        value["mcnemar"]["p_value_holm"] = adjusted[name]
    report["paired_comparisons"] = paired
    report["event_level"] = _event_section(items, results, resamples, seed)
    return report


def _event_section(items, results, resamples, seed):
    section = {}
    by_key = {(r.item_id, r.config): r for r in results.results}
    for config in ("A1", "A2"):
        per_config = {}
        for category in (None, "nudity", "sexual_activity", "sexual_context"):
            name = category or "binary"
            try:
                rows, unusable = events.event_rows(items, {i.item_id: by_key.get((i.item_id, config)) for i in items},
                                                   category)
            except events.TemporalAnnotationsUnavailable as exc:
                per_config[name] = {"available": False, "reason": str(exc)}
                continue
            per_config[name] = {"available": True, "scored_items": len(rows), "unusable_runs": unusable,
                                "aggregate": events.summarize(rows) if rows else None,
                                "f1_iou_0.50_bootstrap": grouped_bootstrap(rows, "group_id", events.event_f1_of,
                                                                           resamples=resamples, seed=seed)}
        section[config] = per_config
    section["A0"] = {"available": False, "reason": "no validated temporal conversion of Marqo scores"}
    return section
