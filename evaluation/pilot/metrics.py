"""Offline interval metrics; no model, cache or media processing imports."""
from __future__ import annotations

import math
from fractions import Fraction

from core.time_intervals import normalize_intervals, intervals_duration
from evaluation.pilot.manifest import Clip

THRESHOLDS = (0.25, 0.50, 0.75)
CATEGORIES = ("nudity", "sexual_activity", "sexual_context")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def union(intervals, duration):
    return normalize_intervals(intervals, duration) if intervals else []


def subtract(intervals, excluded):
    result = []
    for start, end in intervals:
        cursor = start
        for left, right in excluded:
            if right <= cursor or left >= end:
                continue
            if left > cursor:
                result.append((cursor, left))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def intersection(a, b):
    return sum(max(0.0, min(y, v) - max(x, u)) for x, y in a for u, v in b)


def iou(a, b):
    overlap = intersection(a, b)
    return ratio(overlap, intervals_duration(a) + intervals_duration(b) - overlap) or 0.0


def maximum_matching(predictions, truth, threshold):
    """Successive shortest augmenting paths: max cardinality, then max sum IoU.

    Exact rational costs of computed IoUs avoid epsilon tie perturbations. Stable
    sorted IDs, edge order and strict relaxation make equal-cost ties repeatable.
    Bellman-Ford handles reverse residual edges; augmentation continues even when
    a path has positive cost, so cardinality takes precedence over total IoU.
    """
    predictions = sorted(predictions, key=lambda item: item["id"])
    truth = sorted(truth, key=lambda item: item["id"])
    n, m = len(predictions), len(truth)
    sink = n + m + 1
    graph = [[] for _ in range(sink + 1)]

    def edge(u, v, cost):
        forward = [v, len(graph[v]), 1, cost]
        backward = [u, len(graph[u]), 0, -cost]
        graph[u].append(forward)
        graph[v].append(backward)
        return forward

    for p in range(n):
        edge(0, 1 + p, Fraction(0))
    candidates = []
    for p, prediction in enumerate(predictions):
        for g, event in enumerate(truth):
            score = iou(prediction["segments"], event["segments"])
            if score >= threshold:
                link = edge(1 + p, 1 + n + g, -Fraction(score))
                candidates.append((p, g, score, link))
    for g in range(m):
        edge(1 + n + g, sink, Fraction(0))
    while True:
        distances, parents = [None] * len(graph), [None] * len(graph)
        distances[0] = Fraction(0)
        for _ in range(len(graph) - 1):
            changed = False
            for u, edges in enumerate(graph):
                if distances[u] is None:
                    continue
                for index, (v, reverse, capacity, cost) in enumerate(edges):
                    candidate = distances[u] + cost
                    if capacity and (distances[v] is None or candidate < distances[v]):
                        distances[v], parents[v], changed = candidate, (u, index), True
            if not changed:
                break
        if parents[sink] is None:
            break
        v = sink
        while v:
            u, index = parents[v]
            link = graph[u][index]
            link[2] = 0
            graph[v][link[1]][2] = 1
            v = u
    matches = []
    for p, g, score, link in candidates:
        if link[2] == 0:
            prediction, event = predictions[p], truth[g]
            # Boundaries touching a masked region are not observable ground truth.
            start_error = (prediction["start"] - event["start"]
                           if prediction["start_observable"] and event["start_observable"] else None)
            end_error = (prediction["end"] - event["end"]
                         if prediction["end_observable"] and event["end_observable"] else None)
            matches.append({"prediction_id": prediction["id"], "event_id": event["id"],
                            "iou": score, "start_error_seconds": start_error,
                            "end_error_seconds": end_error})
    return matches


def _item(identifier, start, end, exclusions):
    segments = subtract([(start, end)], exclusions)
    return {"id": identifier, "start": start, "end": end, "segments": segments,
            "start_observable": not any(a <= start <= b for a, b in exclusions),
            "end_observable": not any(a <= end <= b for a, b in exclusions)}


def _counts(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn, "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn), "f1": ratio(2 * tp, 2 * tp + fp + fn)}


def evaluate_clip(clip: Clip, predictions: list[dict], category: str | None = None):
    """Binary GT merges only overlapping/touching target events before masking.

    Per-category GT retains annotation identities. Predictions NEVER merge for
    event scoring. Mask fragments remain a single matching vertex/identity.
    """
    if not clip.exhaustive or clip.duration_seconds is None:
        raise ValueError("Metrics require exhaustive annotations and known duration")
    if category is not None and category not in CATEGORIES:
        raise ValueError("Unsupported target category")
    duration = clip.duration_seconds
    exclusions = union([(x.start_seconds, x.end_seconds) for x in clip.excluded_intervals], duration)
    ids = set()
    for p in predictions:
        start, end = p["start_seconds"], p["end_seconds"]
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (float, int)) or not isinstance(end, (float, int))
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start < end <= duration):
            raise ValueError(f"Invalid prediction interval: {p.get('id')}")
        if not p.get("id") or p["id"] in ids:
            raise ValueError("Prediction IDs must be nonempty and unique")
        if p.get("category") not in (*CATEGORIES, "uncertain"):
            raise ValueError("Unsupported prediction category")
        ids.add(p["id"])
    pred = [_item(p["id"], p["start_seconds"], p["end_seconds"], exclusions)
            for p in predictions if category is None or p["category"] == category]
    events = [e for e in clip.events if category is None or category in e.categories]
    if category is None:
        # IDs name the original constituent events, not the mask's fragments.
        groups = []
        for event in sorted(events, key=lambda e: (e.start_seconds, e.end_seconds, e.event_id)):
            if groups and event.start_seconds <= groups[-1][1]:
                groups[-1][1] = max(groups[-1][1], event.end_seconds)
                groups[-1][2].append(event.event_id)
            else:
                groups.append([event.start_seconds, event.end_seconds, [event.event_id]])
        truth = [_item("+".join(sorted(ids)), a, b, exclusions) for a, b, ids in groups]
    else:
        truth = [_item(e.event_id, e.start_seconds, e.end_seconds, exclusions) for e in events]
    ignored_pred = [p["id"] for p in pred if not p["segments"]]
    ignored_gt = [g["id"] for g in truth if not g["segments"]]
    pred = [p for p in pred if p["segments"]]
    truth = [g for g in truth if g["segments"]]
    predicted_time = union([s for p in pred for s in p["segments"]], duration)
    target_time = union([s for g in truth for s in g["segments"]], duration)
    target_seconds, predicted_seconds = map(intervals_duration, (target_time, predicted_time))
    covered = intersection(target_time, predicted_time)
    evaluated = duration - intervals_duration(exclusions)
    results = {}
    for threshold in THRESHOLDS:
        matches = maximum_matching(pred, truth, threshold)
        counts = _counts(len(matches), len(pred) - len(matches), len(truth) - len(matches))
        results[f"{threshold:.2f}"] = {
            **counts, "matches": matches,
            "false_alerts_per_minute": ratio(counts["fp"] * 60, evaluated),
            "negative_only_false_alerts_per_minute": (
                ratio(counts["fp"] * 60, evaluated) if not target_seconds else None),
        }
    return {"clip_id": clip.clip_id, "category": category or "binary",
            "event_metrics": results, "ignored_prediction_ids": ignored_pred,
            "ignored_event_ids": ignored_gt, "evaluated_seconds": evaluated,
            "target_seconds": target_seconds, "predicted_seconds": predicted_seconds,
            "covered_target_seconds": covered,
            "target_coverage": ratio(covered, target_seconds),
            "temporal_precision": ratio(covered, predicted_seconds),
            "missed_target_seconds": target_seconds - covered,
            "excess_ordinary_seconds": predicted_seconds - covered}


def aggregate(rows):
    """Micro totals, never an unweighted mean of clip percentages."""
    total = {key: sum(row[key] for row in rows) for key in (
        "evaluated_seconds", "target_seconds", "predicted_seconds", "covered_target_seconds",
        "missed_target_seconds", "excess_ordinary_seconds")}
    total["clip_count"] = len(rows)
    total["target_coverage"] = ratio(total["covered_target_seconds"], total["target_seconds"])
    total["temporal_precision"] = ratio(total["covered_target_seconds"], total["predicted_seconds"])
    total["event_metrics"] = {}
    for threshold in THRESHOLDS:
        key = f"{threshold:.2f}"
        counts = _counts(*(sum(row["event_metrics"][key][field] for row in rows)
                           for field in ("tp", "fp", "fn")))
        negative = [r for r in rows if not r["target_seconds"]]
        matches = [m for row in rows for m in row["event_metrics"][key]["matches"]]
        errors = {}
        for side in ("start", "end"):
            values = [m[f"{side}_error_seconds"] for m in matches
                      if m[f"{side}_error_seconds"] is not None]
            errors[f"{side}_boundary_count"] = len(values)
            errors[f"{side}_bias_seconds"] = ratio(sum(values), len(values))
            errors[f"{side}_mae_seconds"] = ratio(sum(abs(v) for v in values), len(values))
        total["event_metrics"][key] = {
            **counts, **errors,
            "false_alerts_per_minute": ratio(counts["fp"] * 60, total["evaluated_seconds"]),
            "negative_only_false_alerts_per_minute": ratio(
                sum(r["event_metrics"][key]["fp"] for r in negative) * 60,
                sum(r["evaluated_seconds"] for r in negative)),
        }
    return total
