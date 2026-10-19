"""Event-level scoring for items with exhaustive temporal annotations, reusing the pilot matcher.

Never applied to video-level-only labels, and never to A0 (no temporal conversion of Marqo
scores has been defined or validated).
"""
from __future__ import annotations

from evaluation.benchmark.manifest import CATEGORIES, Item
from evaluation.pilot.manifest import Clip
from evaluation.pilot.metrics import aggregate, evaluate_clip

PRIMARY_IOU = "0.50"


class TemporalAnnotationsUnavailable(ValueError):
    pass


def _clip(item: Item) -> Clip:
    # The benchmark manifest has already validated these annotations; the pilot scorer only needs
    # the timing fields, so the clip is constructed without re-running pilot identity rules.
    return Clip.model_construct(
        clip_id=item.item_id, source_video_id=item.group_id, file_path=item.file_name or item.item_id,
        source_offset_seconds=0.0, split=item.split, duration_seconds=item.duration_seconds,
        sha256=item.sha256, media_metadata={}, annotation_version="benchmark", exhaustive=True,
        events=item.temporal.events, excluded_intervals=item.temporal.excluded_intervals)


def scorable(item: Item, category: str | None) -> bool:
    temporal = item.temporal
    if temporal is None or not temporal.binary_exhaustive:
        return False
    return category is None or category in temporal.exhaustive_categories


def event_rows(items: list[Item], results: dict, category: str | None = None):
    """results: {item_id: VideoResult or None}. Items whose run is unusable are reported, not scored."""
    if category is not None and category not in CATEGORIES:
        raise ValueError("unsupported category")
    candidates = [item for item in items if scorable(item, category)]
    if not candidates:
        raise TemporalAnnotationsUnavailable(
            "no exhaustive temporal annotation" + (f" for {category}" if category else ""))
    rows, unusable = [], []
    for item in candidates:
        result = results.get(item.item_id)
        if result is None or result.status != "completed":
            unusable.append(item.item_id)
            continue
        predictions = [{"id": s.id, "start_seconds": s.start_seconds,
                        "end_seconds": min(s.end_seconds, item.duration_seconds), "category": s.category}
                       for s in result.suggestions if s.start_seconds < item.duration_seconds]
        row = evaluate_clip(_clip(item), predictions, category)
        row["group_id"] = item.group_id
        rows.append(row)
    return rows, unusable


def summarize(rows: list[dict]):
    total = aggregate(rows)
    for key, metrics in total["event_metrics"].items():
        metrics["false_alert_events_per_hour"] = (
            metrics["fp"] * 3600 / total["evaluated_seconds"] if total["evaluated_seconds"] else None)
    return total


def event_f1_of(rows):
    if not rows:
        return None
    tp, fp, fn = (sum(row["event_metrics"][PRIMARY_IOU][k] for row in rows) for k in ("tp", "fp", "fn"))
    return 2 * tp / (2 * tp + fp + fn) if tp + fn else None
