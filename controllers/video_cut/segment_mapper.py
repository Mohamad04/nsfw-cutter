from core.time_utils import timecode_to_seconds


def segment_to_payload(index: int, segment: dict) -> dict:
    if not isinstance(segment, dict):
        raise ValueError("Each cut segment must be an object.")

    timing_mode = str(segment.get("timing_mode") or segment.get("timingMode") or "safe").strip().lower()
    requested_start_seconds = segment_seconds(segment, "requested_start_seconds", "requestedStartSeconds")
    requested_end_seconds = segment_seconds(segment, "requested_end_seconds", "requestedEndSeconds")
    if requested_start_seconds is None:
        requested_start_seconds = timecode_to_seconds(segment.get("start", ""))
    if requested_end_seconds is None:
        requested_end_seconds = timecode_to_seconds(segment.get("end", ""))

    if timing_mode == "requested":
        start_seconds = requested_start_seconds
        end_seconds = requested_end_seconds
        if start_seconds is None:
            raise ValueError("Requested cut start is unavailable.")
        if end_seconds is None:
            raise ValueError("Requested cut end is unavailable.")
    else:
        start_seconds = segment_seconds(segment, "safe_start_seconds", "safe_start", "safeStart")
        end_seconds = segment_seconds(segment, "safe_end_seconds", "safe_end", "safeEnd")
        if start_seconds is None:
            raise ValueError("Safe cut start is unavailable. Recompute keyframe alignment before exporting.")
        if end_seconds is None:
            raise ValueError("Safe cut end is unavailable. Recompute keyframe alignment before exporting.")

    return {
        "index": index,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "requested_start_seconds": requested_start_seconds,
        "requested_end_seconds": requested_end_seconds,
        "previous_keyframe_start": segment_seconds(
            segment,
            "previous_keyframe_start",
            "previousKeyframeStart",
        ),
        "next_keyframe_start": segment_seconds(segment, "next_keyframe_start", "nextKeyframeStart"),
        "previous_keyframe_end": segment_seconds(segment, "previous_keyframe_end", "previousKeyframeEnd"),
        "next_keyframe_end": segment_seconds(segment, "next_keyframe_end", "nextKeyframeEnd"),
        "label": str(segment.get("reason") or segment.get("label") or "").strip() or None,
    }


def segment_seconds(segment: dict, *keys: str) -> float | None:
    for key in keys:
        value = segment.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        return timecode_to_seconds(str(value))
    return None
