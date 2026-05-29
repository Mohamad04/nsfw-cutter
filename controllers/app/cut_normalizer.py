KEYFRAME_CUT_FIELDS = (
    "safe_start",
    "safeStart",
    "safe_end",
    "safeEnd",
    "previous_keyframe_start",
    "previousKeyframeStart",
    "next_keyframe_start",
    "nextKeyframeStart",
    "previous_keyframe_end",
    "previousKeyframeEnd",
    "next_keyframe_end",
    "nextKeyframeEnd",
    "extra_before",
    "extraBefore",
    "extra_after",
    "extraAfter",
)


def normalize_cut(cut: dict) -> dict:
    if not isinstance(cut, dict):
        raise ValueError("Each cut must be a JSON object")

    start = str(cut.get("start", "")).strip()
    end = str(cut.get("end", "")).strip()
    if parse_hh_mm_ss_to_seconds(start) >= parse_hh_mm_ss_to_seconds(end):
        raise ValueError("Each cut must have start before end")

    normalized = {
        "start": start,
        "end": end,
        "reason": str(cut.get("reason") or "Manual cut"),
        "tags": str(cut.get("tags") or "manual"),
        "source": str(cut.get("source") or "Manual"),
        "score": str(cut.get("score") or "--"),
    }
    if has_keyframe_cut_fields(cut):
        safe_start = str(cut.get("safe_start") or cut.get("safeStart") or start).strip()
        safe_end = str(cut.get("safe_end") or cut.get("safeEnd") or end).strip()
        normalized.update(
            {
                "safeStart": safe_start,
                "safeEnd": safe_end,
                "previousKeyframeStart": str(
                    cut.get("previous_keyframe_start") or cut.get("previousKeyframeStart") or safe_start
                ),
                "nextKeyframeStart": str(
                    cut.get("next_keyframe_start") or cut.get("nextKeyframeStart") or start
                ),
                "previousKeyframeEnd": str(
                    cut.get("previous_keyframe_end") or cut.get("previousKeyframeEnd") or end
                ),
                "nextKeyframeEnd": str(
                    cut.get("next_keyframe_end") or cut.get("nextKeyframeEnd") or safe_end
                ),
                "extraBefore": str(cut.get("extraBefore") or cut.get("extra_before") or "0.0s"),
                "extraAfter": str(cut.get("extraAfter") or cut.get("extra_after") or "0.0s"),
            }
        )
    _copy_optional_number(cut, normalized, "requested_start_seconds", "requestedStartSeconds")
    _copy_optional_number(cut, normalized, "requested_end_seconds", "requestedEndSeconds")
    _copy_optional_number(cut, normalized, "safe_start_seconds", "safeStartSeconds")
    _copy_optional_number(cut, normalized, "safe_end_seconds", "safeEndSeconds")
    return normalized


def parse_hh_mm_ss_to_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Cut times must use HH:MM:SS")

    try:
        hours, minutes, seconds = [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Cut times must use HH:MM:SS") from exc

    if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59:
        raise ValueError("Cut times must use HH:MM:SS")

    return hours * 3600 + minutes * 60 + seconds


def has_keyframe_cut_fields(cut: dict) -> bool:
    return any(key in cut for key in KEYFRAME_CUT_FIELDS)


def _copy_optional_number(source: dict, target: dict, snake_key: str, camel_key: str) -> None:
    value = source.get(snake_key)
    if value in (None, ""):
        value = source.get(camel_key)
    if value in (None, ""):
        return
    target[camel_key] = float(value)
