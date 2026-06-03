import logging
import unicodedata
from pathlib import Path

from services.media.validation_service import validate_input_video
from services.subtitles.language_resolver import resolve_external_language_token


logger = logging.getLogger(__name__)

TEXT_SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}
VOBSUB_EXTENSIONS = {".idx", ".sub"}
SUPPORTED_SUBTITLE_EXTENSIONS = TEXT_SUBTITLE_EXTENSIONS | VOBSUB_EXTENSIONS
SAFE_SUFFIX_SEPARATORS = {".", "-", "_", " "}


def find_matching_external_subtitles(video_path: str | Path) -> list[dict]:
    resolved_path = validate_input_video(video_path)
    matches: list[dict] = []
    consumed_vobsub_stems: set[str] = set()

    try:
        directory_entries = sorted(
            (
                path
                for path in resolved_path.parent.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUBTITLE_EXTENSIONS
            ),
            key=lambda path: _normalized_text(path.name),
        )
    except OSError as exc:
        logger.error(
            "[Subtitles] Unable to read subtitle directory: %s, error=%s",
            resolved_path.parent,
            exc,
        )
        return []

    for subtitle_path in directory_entries:
        extension = subtitle_path.suffix.lower()
        match = _match_external_subtitle(resolved_path.stem, subtitle_path.stem)
        if match is None:
            continue

        vobsub_key = _normalized_text(subtitle_path.stem)
        if extension in VOBSUB_EXTENSIONS and vobsub_key in consumed_vobsub_stems:
            continue

        if extension in TEXT_SUBTITLE_EXTENSIONS:
            candidate = _external_candidate(
                subtitle_path,
                source_format=extension.lstrip("."),
                kind="text",
                is_text_readable=True,
                match_type=match["match_type"],
                filename_suffix=match["filename_suffix"],
            )
        else:
            pair_path = subtitle_path.with_suffix(".sub" if extension == ".idx" else ".idx")
            if not pair_path.is_file():
                pair_path = subtitle_path.with_suffix(".SUB" if extension == ".idx" else ".IDX")

            if pair_path.is_file():
                consumed_vobsub_stems.add(vobsub_key)
                primary_path = subtitle_path.with_suffix(".idx")
                if not primary_path.is_file():
                    primary_path = subtitle_path.with_suffix(".IDX")
                candidate = _external_candidate(
                    primary_path if primary_path.is_file() else subtitle_path,
                    source_format="vobsub",
                    kind="image",
                    is_text_readable=False,
                    match_type=match["match_type"],
                    filename_suffix=match["filename_suffix"],
                    companion_path=str(pair_path.resolve()),
                    note="VobSub subtitle pair; text processing not supported yet",
                )
            else:
                candidate = _external_candidate(
                    subtitle_path,
                    source_format=extension.lstrip("."),
                    kind="unknown",
                    is_text_readable=False,
                    match_type=match["match_type"],
                    filename_suffix=match["filename_suffix"],
                    note="Unsupported external subtitle format",
                )

        logger.info(
            "[Subtitles] External subtitle matched: %s, match=%s",
            subtitle_path,
            candidate["match_type"],
        )
        matches.append(candidate)

    return matches


def _match_external_subtitle(video_stem: str, subtitle_stem: str) -> dict | None:
    normalized_video_stem = _normalized_text(video_stem)
    normalized_subtitle_stem = _normalized_text(subtitle_stem)
    if normalized_subtitle_stem == normalized_video_stem:
        return {"match_type": "exact", "filename_suffix": None}

    if not normalized_subtitle_stem.startswith(normalized_video_stem):
        return None

    normalized_suffix = normalized_subtitle_stem[len(normalized_video_stem):]
    if not normalized_suffix or normalized_suffix[0] not in SAFE_SUFFIX_SEPARATORS:
        return None

    raw_suffix = subtitle_stem[len(video_stem):]
    if raw_suffix and raw_suffix[0] in SAFE_SUFFIX_SEPARATORS:
        raw_suffix = raw_suffix[1:]
    else:
        raw_suffix = normalized_suffix[1:]
    return {
        "match_type": "video_base_with_suffix",
        "filename_suffix": raw_suffix or None,
    }


def _external_candidate(
    subtitle_path: Path,
    *,
    source_format: str,
    kind: str,
    is_text_readable: bool,
    match_type: str,
    filename_suffix: str | None,
    companion_path: str | None = None,
    note: str | None = None,
) -> dict:
    language_code, language_name = _language_from_suffix(filename_suffix)
    resolved_path = subtitle_path.resolve()
    detected_by = "same_stem_sidecar" if match_type == "exact" else "video_base_with_suffix"
    candidate = {
        "source": "external",
        "kind": kind,
        "is_text_readable": is_text_readable,
        "language_code": language_code,
        "language_name": language_name,
        "label": filename_suffix,
        "stream_index": None,
        "codec_name": None,
        "file_path": str(resolved_path),
        "path": str(resolved_path),
        "filename": subtitle_path.name,
        "format": source_format,
        "extension": subtitle_path.suffix.lower(),
        "match_type": match_type,
        "filename_suffix": filename_suffix,
        "detected_by": detected_by,
    }
    if companion_path is not None:
        candidate["companion_path"] = companion_path
    if note is not None:
        candidate["note"] = note
    return candidate


def _language_from_suffix(suffix: str | None) -> tuple[str | None, str | None]:
    if not suffix:
        return None, None

    first_token = suffix.replace("-", ".").replace("_", ".").replace(" ", ".").split(".")[0]
    return resolve_external_language_token(first_token)


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()
