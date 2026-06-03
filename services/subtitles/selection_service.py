from collections import defaultdict
from pathlib import Path


OFF_SUBTITLE_OPTION_ID = "__subtitle_preview_off__"


def attach_candidate_ids(media_path: str, candidates: list[dict]) -> list[dict]:
    return [
        {
            **candidate,
            "candidate_id": subtitle_candidate_id(media_path, candidate, index),
        }
        for index, candidate in enumerate(candidates)
    ]


def subtitle_candidate_id(media_path: str, candidate: dict, index: int = 0) -> str:
    source = candidate.get("source") or "unknown"
    if source == "embedded":
        stream_index = candidate.get("stream_index", candidate.get("index"))
        codec_name = candidate.get("codec_name") or candidate.get("codec") or ""
        return f"embedded:{_stable_path(media_path)}:{stream_index}:{codec_name}"

    if source == "external":
        file_path = candidate.get("file_path") or candidate.get("path") or ""
        return f"external:{_stable_path(file_path)}"

    return f"{source}:{_stable_path(media_path)}:{index}"


def attach_player_subtitle_track_indexes(
    candidates: list[dict],
    player_subtitle_track_count: int,
) -> list[dict]:
    embedded_index = 0
    mapped_candidates = []
    for candidate in candidates:
        mapped_candidate = dict(candidate)
        if candidate.get("source") == "embedded":
            if embedded_index < max(0, int(player_subtitle_track_count)):
                mapped_candidate["player_subtitle_track_index"] = embedded_index
            else:
                mapped_candidate["player_subtitle_track_index"] = None
            embedded_index += 1
        else:
            mapped_candidate["player_subtitle_track_index"] = None
        mapped_candidates.append(mapped_candidate)
    return mapped_candidates


def build_analysis_subtitle_options(
    candidates: list[dict],
    selected_candidate_id: str | None = None,
    *,
    include_off: bool = False,
) -> list[dict]:
    labels = _disambiguated_labels(candidates)
    options = []
    if include_off and candidates:
        options.append(
            {
                "id": OFF_SUBTITLE_OPTION_ID,
                "label": "Off",
                "capabilityLabel": "Disable preview subtitles",
                "enabled": True,
                "selected": selected_candidate_id == OFF_SUBTITLE_OPTION_ID,
                "source": "off",
                "kind": "off",
                "languageCode": None,
                "languageName": None,
                "isTextReadable": False,
            }
        )

    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id") or subtitle_candidate_id("", candidate, index)
        enabled = bool(candidate.get("is_text_readable"))
        option = {
            "id": candidate_id,
            "label": labels[index],
            "capabilityLabel": _capability_label(candidate),
            "enabled": enabled,
            "selected": bool(selected_candidate_id and candidate_id == selected_candidate_id),
            "source": candidate.get("source"),
            "kind": candidate.get("kind"),
            "languageCode": candidate.get("language_code"),
            "languageName": candidate.get("language_name"),
            "isTextReadable": enabled,
        }
        options.append(option)
    return options


def auto_select_analysis_subtitle_id(candidates: list[dict]) -> str | None:
    readable = [candidate for candidate in candidates if candidate.get("is_text_readable")]
    if len(readable) != 1:
        return None
    return readable[0].get("candidate_id")


def find_selectable_candidate(candidates: list[dict], candidate_id: str) -> dict | None:
    for candidate in candidates:
        if candidate.get("candidate_id") == candidate_id and candidate.get("is_text_readable"):
            return dict(candidate)
    return None


def preview_subtitle_track_index_for_selection(
    candidates: list[dict],
    selected_candidate_id: str | None,
) -> int:
    if not selected_candidate_id or selected_candidate_id == OFF_SUBTITLE_OPTION_ID:
        return -1

    for candidate in candidates:
        if candidate.get("candidate_id") != selected_candidate_id:
            continue
        if candidate.get("source") != "embedded":
            return -1
        track_index = candidate.get("player_subtitle_track_index")
        if isinstance(track_index, int):
            return track_index
        return -1
    return -1


def analysis_subtitle_status_text(
    candidates: list[dict],
    selected_candidate_id: str | None,
    *,
    auto_selected: bool = False,
) -> str:
    if not candidates:
        return "Subtitle: Not detected"

    readable_count = sum(1 for candidate in candidates if candidate.get("is_text_readable"))
    if readable_count == 0:
        return "Subtitles found · None text-readable"

    if selected_candidate_id:
        if selected_candidate_id == OFF_SUBTITLE_OPTION_ID:
            return "Analysis subtitle: Off"

        label = _selected_label(candidates, selected_candidate_id)
        if label:
            suffix = " · Auto-selected" if auto_selected else ""
            return f"Analysis subtitle: {label}{suffix}"

    if readable_count == 1:
        return "Analysis subtitle: Select one · 1 available"
    return f"Analysis subtitle: Select one · {readable_count} available"


def _disambiguated_labels(candidates: list[dict]) -> list[str]:
    base_labels = [_base_label(candidate) for candidate in candidates]
    source_labels = [_source_label(candidate) for candidate in candidates]
    grouped_indexes = defaultdict(list)
    for index, base_label in enumerate(base_labels):
        grouped_indexes[base_label].append(index)

    labels = list(base_labels)
    for indexes in grouped_indexes.values():
        if len(indexes) == 1:
            continue

        source_groups = defaultdict(list)
        for index in indexes:
            source_groups[source_labels[index]].append(index)

        for index in indexes:
            source_label = source_labels[index]
            source_indexes = source_groups[source_label]
            if len(source_indexes) == 1:
                labels[index] = f"{base_labels[index]} · {source_label}"
            else:
                labels[index] = f"{base_labels[index]} · {source_label} {source_indexes.index(index) + 1}"
    return labels


def _selected_label(candidates: list[dict], selected_candidate_id: str) -> str | None:
    options = build_analysis_subtitle_options(candidates, selected_candidate_id)
    for option in options:
        if option["id"] == selected_candidate_id:
            return option["label"]
    return None


def _base_label(candidate: dict) -> str:
    return candidate.get("language_name") or "Unknown language"


def _source_label(candidate: dict) -> str:
    source = candidate.get("source")
    if source == "embedded":
        return "Embedded"
    if source == "external":
        return "External"
    return "Detected"


def _capability_label(candidate: dict) -> str:
    if candidate.get("is_text_readable"):
        return "Text"
    if candidate.get("kind") == "image":
        return "Image subtitle · unavailable for analysis"
    return "Unsupported · unavailable for analysis"


def _stable_path(path_value: str | Path) -> str:
    if not path_value:
        return ""
    return str(Path(path_value).expanduser().resolve())
