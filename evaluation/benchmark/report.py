"""Offline benchmark report: video-level metrics for A0/A1/A2, events where supported, paired tests."""
from __future__ import annotations

import statistics

from evaluation.benchmark import events, video_metrics as vm
from evaluation.benchmark.manifest import BenchmarkManifest, assert_disjoint_from_pilot, manifest_digest
from evaluation.benchmark.results import ResultsFile
from evaluation.benchmark.stats import grouped_bootstrap, holm, mcnemar_exact

DEFAULT_RESAMPLES = 5000
DEFAULT_SEED = 20261019
SUBSET_EXCLUSION_PREFIX = "analysis_subset:"
# Label-agnostic paired descriptions: (first, second) configurations compared item by item.
ALERT_PAIRS = (("A1", "A2"), ("A0@0.15", "A2"), ("A0@0.45", "A2"), ("A0@0.15", "A1"), ("A0@0.45", "A1"),
               ("A0@0.15", "A0@0.45"))


def apply_subset(manifest: BenchmarkManifest, spec: dict, split: str = "test"):
    """Documented sensitivity subset of a completed campaign, scored without touching its manifest or results.

    spec: {"subset_id", "reason", "exclude_item_ids": [...],
           optional "selection_rule": {"provenance_flag", "scope": "item" (default) | "subject"}}.
    Excluded items keep both configurations out (an A1/A2 pair is never split). With a provenance flag,
    the listed items must be exactly the evaluable items carrying that flag (scope "item"), or every
    evaluable item of a subject that has a flagged item (scope "subject": subject-disjoint subset).
    Returns the derived manifest and the record written to the report.
    """
    subset_id, reason = str(spec.get("subset_id", "")).strip(), str(spec.get("reason", "")).strip()
    ids = spec.get("exclude_item_ids") or []
    if not subset_id or not reason or not ids:
        raise ValueError("a subset needs subset_id, reason and a non-empty exclude_item_ids")
    if len(ids) != len(set(ids)):
        raise ValueError("exclude_item_ids must be unique")
    evaluable = {item.item_id: item for item in manifest.evaluable(split)}
    unknown = sorted(set(ids) - set(evaluable))
    if unknown:
        raise ValueError("subset exclusions are not evaluable items of this split: " + ", ".join(unknown))
    rule = spec.get("selection_rule") or {}
    flag, scope = rule.get("provenance_flag"), rule.get("scope", "item")
    if scope not in ("item", "subject"):
        raise ValueError("selection_rule.scope must be 'item' or 'subject'")
    if flag is not None:
        flagged = {item_id for item_id, item in evaluable.items() if item.provenance.get(flag) is True}
        if scope == "subject":
            subjects = {evaluable[item_id].group_id for item_id in flagged}
            flagged = {item_id for item_id, item in evaluable.items() if item.group_id in subjects}
        if not flagged or flagged != set(ids):
            raise ValueError(f"exclude_item_ids must be exactly the evaluable items selected by {flag!r} "
                             f"(scope {scope!r})")
    if len(ids) == len(evaluable):
        raise ValueError("a subset cannot exclude every evaluable item")
    marker = SUBSET_EXCLUSION_PREFIX + reason
    derived = manifest.model_copy(update={"items": [
        item.model_copy(update={"excluded": True, "exclusion_reason": marker}) if item.item_id in ids else item
        for item in manifest.items]})
    remaining = derived.evaluable(split)
    return derived, {
        "subset_id": subset_id, "reason": reason, "description": spec.get("description", ""),
        "selection_rule": spec.get("selection_rule"), "spec_file": spec.get("spec_file"), "excluded_item_ids": sorted(ids),
        "excluded_groups": sorted({evaluable[i].group_id for i in ids}),
        "base_evaluable": len(evaluable), "base_groups": len({i.group_id for i in evaluable.values()}),
        "remaining_evaluable": len(remaining), "remaining_groups": len({i.group_id for i in remaining}),
        "groups_shared_with_excluded_items": sorted({evaluable[i].group_id for i in ids}
                                                    & {i.group_id for i in remaining}),
        "derived_manifest_digest": manifest_digest(derived)}


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


MIN_INFORMATIVE_GROUPS = 5


def _guard_interval(result, informative_groups, definition):
    """Grouped percentile intervals are unreliable when few groups carry the signal; say so, never narrow.

    With k informative groups out of G, a resample contains none of them with probability (1 - k/G)^G,
    which is what drives a lower bound to the no-signal value. With no informative group every resample
    gives the same value: a zero-width interval would suggest a precision the data cannot give, so the
    interval is withheld.
    """
    groups = result["groups"]
    result["informative_groups"] = informative_groups
    result["informative_group_definition"] = definition
    result["probability_resample_without_informative_group"] = (
        (1 - informative_groups / groups) ** groups if groups else None)
    if groups and informative_groups == 0:
        result["low"] = result["high"] = None
        result["interval_withheld"] = f"degenerate: no group has {definition}; see the Wilson interval or counts"
    elif informative_groups < MIN_INFORMATIVE_GROUPS:
        result["caution"] = (f"only {informative_groups} group(s) with {definition}: the percentile interval is "
                             "unstable and its bounds must not be read as precise")
    return result


def _alert_rate(rows):
    return sum(r["alert"] for r in rows) / len(rows) if rows else None


def _alert_uncertainty(rows, resamples, seed):
    """Alert rate with a subject-grouped bootstrap interval (videos of one subject are not independent)."""
    completed = [r for r in rows if r["alert"] is not None]
    result = grouped_bootstrap(completed, "group_id", _alert_rate, resamples=resamples, seed=seed)
    alerting = {r["group_id"] for r in completed if r["alert"]}
    if completed and all(r["alert"] for r in completed):  # constant rate: every video alerts
        return _guard_interval(result, 0, "a video without alert")
    return _guard_interval(result, len(alerting), "at least one alert")


def _paired_alerts(rows_x, rows_y, name_x, name_y, resamples, seed):
    """Item-by-item alert agreement, label-agnostic. Agreement is not accuracy."""
    y_by_item = {r["item_id"]: r for r in rows_y}
    if set(y_by_item) != {r["item_id"] for r in rows_x}:
        raise ValueError(f"{name_x}/{name_y}: configurations do not cover the same items")
    pairs = [{"group_id": x["group_id"], "x": x["alert"], "y": y_by_item[x["item_id"]]["alert"]}
             for x in rows_x]
    usable = [p for p in pairs if p["x"] is not None and p["y"] is not None]

    def difference(sample):
        return (sum(p["y"] for p in sample) - sum(p["x"] for p in sample)) / len(sample) if sample else None
    return {"first": name_x, "second": name_y, "paired_items": len(usable),
            "paired_groups": len({p["group_id"] for p in usable}), "unpaired_items": len(pairs) - len(usable),
            "both": sum(p["x"] and p["y"] for p in usable),
            "first_only": sum(p["x"] and not p["y"] for p in usable),
            "second_only": sum(p["y"] and not p["x"] for p in usable),
            "neither": sum(not p["x"] and not p["y"] for p in usable),
            "alert_rate_difference_second_minus_first": _guard_interval(
                grouped_bootstrap(usable, "group_id", difference, resamples=resamples, seed=seed),
                len({p["group_id"] for p in usable if p["x"] != p["y"]}), "a discordant pair")}


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


def score(manifest: BenchmarkManifest, results: ResultsFile, *, pilot_manifest, split: str = "test",
          resamples: int = DEFAULT_RESAMPLES, seed: int = DEFAULT_SEED, subset: dict | None = None):
    """pilot_manifest (the development/tuning pilot) is mandatory: scoring always re-checks leakage.

    subset (see apply_subset) scores a documented part of the campaign; the results must still belong to
    the full manifest, whose digest is the one reported.
    """
    digest = manifest_digest(manifest)
    disjoint = assert_disjoint_from_pilot(manifest, pilot_manifest)
    results.check_against(manifest, digest)
    subset_record = None
    if subset is not None:
        manifest, subset_record = apply_subset(manifest, subset, split)
    items = manifest.evaluable(split)
    unidentified = sorted(item.item_id for item in items if item.sha256 is None)
    if unidentified:
        raise ValueError("scoring requires the media SHA-256 of every evaluable item (identity and leakage "
                         "checks): " + ", ".join(unidentified[:10]))
    excluded = [i for i in manifest.items if i.split == split and i.excluded]
    rows, fallbacks = _decisions(manifest, results, split)
    labels = [item.video_label for item in items]
    report = {
        "benchmark_id": manifest.benchmark_id, "manifest_digest": digest, "track": manifest.track,
        "split": split, "dataset": manifest.dataset.model_dump(mode="json"),
        "annotation": manifest.annotation.model_dump(mode="json"),
        "environment": results.environment.model_dump(mode="json"),
        "disjoint_from_pilot": disjoint,
        "sample_sizes": {
            "items_in_split": sum(i.split == split for i in manifest.items),
            "excluded": {i.item_id: i.exclusion_reason for i in excluded},
            "excluded_by_reason": {reason: sum(i.exclusion_reason == reason for i in excluded)
                                   for reason in sorted({i.exclusion_reason for i in excluded})},
            "excluded_reference_positives": sum(i.video_label == "positive" for i in excluded),
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
    if subset_record is not None:
        report["subset"] = subset_record
    report["alert_uncertainty"] = {
        "note": "alert rates over completed runs, labels ignored; an alert is not a confirmed detection",
        **{name: _alert_uncertainty(config_rows, resamples, seed) for name, config_rows in rows.items()}}
    report["paired_alert_agreement"] = {
        "note": "label-agnostic agreement between configurations on the same items; agreement is not accuracy",
        **{f"{x}_vs_{y}": _paired_alerts(rows[x], rows[y], x, y, resamples, seed) for x, y in ALERT_PAIRS}}
    if manifest.track == "technical" or not labels.count("positive"):
        report["scope_warning"] = ("No positive reference labels: at most specificity and false-alert rates "
                                   "(both only from human-reviewed negatives) and runtime can be measured. "
                                   "This is not a complete NSFW accuracy evaluation.")
    verification = manifest.verification(split)
    report["verification"] = verification
    report["alert_review"] = {name: vm.alert_review(config_rows) for name, config_rows in rows.items()}
    if not verification["complete"]:
        reason = ("reference labels do not cover every evaluable item (verification by alert review and/or "
                  "random audit is not a random sample): specificity, recall, F1 and paired accuracy tests "
                  "are withheld; see alert_review")
        report["video_level"] = {"withheld": reason}
        report["paired_comparisons"] = {"withheld": reason}
        # Temporal annotations limited to reviewed (e.g. alerted) videos would inherit the same selection.
        report["event_level"] = {"withheld": reason}
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
                                "evaluable_items": len(items),
                                "items_without_exhaustive_temporal_truth": len(items) - len(rows) - len(unusable),
                                "aggregate": events.summarize(rows) if rows else None,
                                "f1_iou_0.50_bootstrap": grouped_bootstrap(rows, "group_id", events.event_f1_of,
                                                                           resamples=resamples, seed=seed)}
        section[config] = per_config
    section["A0"] = {"available": False, "reason": "no validated temporal conversion of Marqo scores"}
    return section
