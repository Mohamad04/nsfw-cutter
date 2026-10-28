"""Video-level confusion matrices and ablation decision rules (no model or media imports).

Pre-registered decision rules:
- A1/A2: a completed run alerts when it returns at least one final suggestion of any category,
  including "uncertain" (same convention as the pilot's binary score).
- A0 (Marqo baseline): a video alerts when one coarse-frame Marqo probability is >= tau.
  Conservative fallback scores (probability None) are not model outputs and are ignored, but counted.
  tau is fixed in advance: 0.15 (production candidate gate) and 0.45 (production strong gate).
"""
from __future__ import annotations

from evaluation.benchmark.stats import wilson

A0_THRESHOLDS = (0.15, 0.45)
FAILURE_POLICIES = ("exclude", "worst_case")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def pipeline_alert(result) -> bool | None:
    """None means no usable prediction (failed, cancelled, partial or not run)."""
    if result is None or result.status != "completed":
        return None
    return bool(result.suggestions)


def a0_alert(a2_result, threshold: float) -> tuple[bool | None, int]:
    """Returns (alert, number of fallback scores ignored); derived from the same A2 run."""
    if a2_result is None or a2_result.status != "completed" or not a2_result.marqo_scores:
        return None, 0
    fallbacks = sum(score.probability is None for score in a2_result.marqo_scores)
    return any(s.probability is not None and s.probability >= threshold for s in a2_result.marqo_scores), fallbacks


def confusion(rows: list[dict], failure_policy: str = "exclude"):
    """rows: {"label": positive|negative|uncertain|missing, "alert": bool|None, ...}.

    Uncertain/missing labels are never scored. Failures are excluded and reported, or, under
    worst_case, counted as the wrong decision for their label.
    """
    if failure_policy not in FAILURE_POLICIES:
        raise ValueError("unsupported failure policy")
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    accounting = {"uncertain_label": 0, "missing_label": 0, "failed_positive": 0, "failed_negative": 0}
    for row in rows:
        label, alert = row["label"], row["alert"]
        if label in ("uncertain", "missing"):
            accounting[f"{label}_label"] += 1
            continue
        if alert is None:
            accounting[f"failed_{label}"] += 1
            if failure_policy == "exclude":
                continue
            alert = label == "negative"
        if label == "positive":
            counts["tp" if alert else "fn"] += 1
        else:
            counts["fp" if alert else "tn"] += 1
    return {**counts, **accounting, "failure_policy": failure_policy}


def video_metrics(counts: dict):
    """Classification metrics; valid as population estimates only under complete verification
    (report.py withholds them otherwise). Every proportion names its denominator."""
    tp, fp, fn, tn = (counts[k] for k in ("tp", "fp", "fn", "tn"))
    sensitivity, specificity = ratio(tp, tp + fn), ratio(tn, tn + fp)
    return {
        "positives_scored": tp + fn, "negatives_scored": tn + fp,
        "precision": ratio(tp, tp + fp), "recall": sensitivity, "specificity": specificity,
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "balanced_accuracy": (sensitivity + specificity) / 2
        if sensitivity is not None and specificity is not None else None,
        "accuracy": ratio(tp + tn, tp + tn + fp + fn),
        "precision_ci": wilson(tp, tp + fp), "recall_ci": wilson(tp, tp + fn),
        "specificity_ci": wilson(tn, tn + fp),
        "false_positive_rate_on_verified_negatives_ci": wilson(fp, tn + fp),
        "denominators": {"precision": "alerted videos with a reference label (tp+fp)",
                         "recall": "reference positives (tp+fn)",
                         "specificity_and_false_positive_rate": "reference negatives (tn+fp)"},
    }


def alert_review(rows: list[dict]):
    """Label-agnostic alert rate plus what review has confirmed; valid under any verification design.

    rows also carry "duration_seconds" (or None). The alert rate is NOT a false-positive rate.
    The confirmed false-alert rate is reported only when every alert has a reference label,
    i.e. when review covered all alerts; otherwise it would be a lower bound and is withheld.
    """
    completed = [r for r in rows if r["alert"] is not None]
    alerted = [r for r in completed if r["alert"]]
    by_label = {label: sum(r["label"] == label for r in alerted)
                for label in ("positive", "negative", "uncertain", "missing")}
    all_alerts_reviewed = by_label["missing"] == 0
    seconds = [r.get("duration_seconds") for r in completed]
    hours = sum(seconds) / 3600 if seconds and all(s is not None for s in seconds) else None
    audited = [r for r in completed if r.get("review_basis") == "random_audit"]
    return {
        "completed_runs": len(completed), "failed_or_partial_runs": len(rows) - len(completed),
        "alerted_videos": len(alerted),
        # Denominator: every completed (analyzed) video, labelled or not. Not a false-positive rate.
        "alert_rate_unverified_ci": wilson(len(alerted), len(completed)),
        "alerts_by_reference_label": by_label, "all_alerts_reviewed": all_alerts_reviewed,
        "confirmed_false_alerts": by_label["negative"],
        # Exact count of false alerts over all analyzed videos once every alert is reviewed; it is not
        # a specificity (the denominator includes unreviewed and positive videos).
        "confirmed_false_alerts_per_analyzed_video_ci": wilson(by_label["negative"], len(completed))
        if all_alerts_reviewed else None,
        "confirmed_false_alerts_per_analyzed_hour": by_label["negative"] / hours
        if all_alerts_reviewed and hours else None,
        # Audit findings describe the audited sample only; no population estimate is derived from them.
        "random_audit": {"audited_videos": len(audited),
                         "labels": {label: sum(r["label"] == label for r in audited)
                                    for label in ("positive", "negative", "uncertain")},
                         "positives_found_without_alert": sum(r["label"] == "positive" and not r["alert"]
                                                              for r in audited)},
    }


def f1_of(rows):
    counts = confusion(rows)
    return ratio(2 * counts["tp"], 2 * counts["tp"] + counts["fp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None


def balanced_accuracy_of(rows):
    return video_metrics(confusion(rows))["balanced_accuracy"]


def specificity_of(rows):
    return video_metrics(confusion(rows))["specificity"]
