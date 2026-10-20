"""Human NSFW annotation record (guide docs/nsfw_annotation_guide.md v2) and its validation rules.

Pure Python, no Qt, no model, no media access. Every semantic value comes from the reviewer; the only
derived value is the video label, a deterministic function of the reviewer's choices (guide section 5).
"""
from __future__ import annotations

from itertools import pairwise

from evaluation.annotation.coverage import (
    TIMING_TOLERANCE_SECONDS,
    fully_played,
    unplayed_seconds,
)

CATEGORIES = ("nudity", "sexual_activity", "sexual_context")
CATEGORY_STATES = ("absent", "present", "uncertain")
NUDITY_CONTEXTS = ("nonsexual_everyday", "nonsexual_medical", "nonsexual_artistic", "nonsexual_educational",
                   "sexual", "unclear")
ESCALATIONS = ("none", "age_uncertain", "consent_uncertain", "other_sensitive")
MEDIA_EXCLUSIONS = ("unreadable_media", "sha256_mismatch")
MIN_GAP_SECONDS = 2.0


def empty_record(item_id: str, sha256: str, duration_seconds: float, has_audio: bool):
    return {"schema_version": 1, "item_id": item_id, "sha256": sha256, "duration_seconds": duration_seconds,
            "has_audio": has_audio, "categories": {c: None for c in CATEGORIES}, "nudity_context": None,
            "events": [], "watched_in_full": False, "played_intervals": [], "playback_coverage": 0.0,
            "audio_listened": False, "escalation": "none", "exclusion_reason": "", "notes": "",
            "seconds_spent": 0.0}


def video_label(record) -> str | None:
    """Guide section 5. None while the categories needed for a decision are not all chosen."""
    if record["escalation"] != "none" or record["exclusion_reason"].strip():
        return "excluded"
    states = record["categories"]
    if any(s == "present" for s in states.values()):
        return "positive"
    if any(s is None for s in states.values()):
        return None
    if any(s == "uncertain" for s in states.values()):
        return "uncertain"
    return "negative" if _fully_reviewed(record) else "uncertain"


def fully_played_record(record) -> bool:
    """Coverage is recomputed from the played intervals, never taken from a stored percentage."""
    return fully_played(record["played_intervals"], record["duration_seconds"])


def _fully_reviewed(record) -> bool:
    # Negative needs explicit human confirmations (viewing, and listening when there is audio) on top of
    # a measured complete playback; nothing here is ever assumed.
    return (record["watched_in_full"] is True and fully_played_record(record)
            and (record["audio_listened"] is True or not record["has_audio"]))


def validate(record) -> list[str]:
    """Problems that prevent locking (empty list: the record can be locked)."""
    problems = []
    states, label = record["categories"], video_label(record)
    if record["escalation"] not in ESCALATIONS:
        problems.append("unknown escalation")
    excluded = label == "excluded"
    if record["escalation"] != "none" and not record["exclusion_reason"].strip():
        problems.append("an escalation needs an exclusion reason (the escalation type is acceptable)")
    if not excluded:
        for category in CATEGORIES:
            if states[category] not in CATEGORY_STATES:
                problems.append(f"{category}: choose absent, present or uncertain")
    elif any(s is not None and s not in CATEGORY_STATES for s in states.values()):
        problems.append("invalid category state")
    if states["nudity"] in ("present", "uncertain"):
        if not excluded and record["nudity_context"] not in NUDITY_CONTEXTS:
            problems.append("nudity present or uncertain: choose a nudity_context")
    elif record["nudity_context"] is not None:
        problems.append("nudity_context only applies when nudity is present or uncertain")
    if record["nudity_context"] is not None and record["nudity_context"] not in NUDITY_CONTEXTS:
        problems.append("unknown nudity_context")
    if record["watched_in_full"] and not fully_played_record(record):
        problems.append(f"watched_in_full requires the whole video to have been played "
                        f"({unplayed_seconds(record['played_intervals'], record['duration_seconds']):.1f} s "
                        f"unplayed; tolerance {TIMING_TOLERANCE_SECONDS:g} s)")
    problems += _event_problems(record, excluded)
    if label == "uncertain" and all(s == "absent" for s in states.values()) and not record["notes"].strip():
        # Guide section 5: an incompletely watched video is uncertain, never negative; say why.
        problems.append("all categories absent without a complete viewing (and listening): the video is "
                        "uncertain; explain why in the notes, or watch it in full")
    return problems


def _event_problems(record, excluded):
    problems, states, duration = [], record["categories"], record["duration_seconds"]
    by_category = {}
    for n, event in enumerate(record["events"], 1):
        category, start, end = event.get("category"), event.get("start_seconds"), event.get("end_seconds")
        if category not in CATEGORIES:
            problems.append(f"interval {n}: unknown category")
            continue
        if states[category] not in ("present", "uncertain"):
            problems.append(f"interval {n}: {category} is not present or uncertain")
        if not (isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= start < end <= duration):
            problems.append(f"interval {n}: need 0 <= start < end <= {duration:.3f} s")
            continue
        by_category.setdefault(category, []).append((start, end))
    for category, intervals in by_category.items():
        intervals.sort()
        for (_, end), (start, _) in pairwise(intervals):
            if start - end < MIN_GAP_SECONDS:
                problems.append(f"{category}: intervals closer than {MIN_GAP_SECONDS:g} s must be merged")
    if not excluded:
        for category in CATEGORIES:
            if states[category] in ("present", "uncertain") and category not in by_category:
                problems.append(f"{category} is {states[category]}: record at least one interval")
    return problems
