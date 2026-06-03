import logging
from pathlib import Path

from services.infrastructure.ffmpeg.subtitles import probe_subtitle_streams
from services.media.validation_service import validate_input_video
from services.subtitles.language_resolver import resolve_language_name


logger = logging.getLogger(__name__)

TEXT_SUBTITLE_CODECS = {
    "subrip",
    "srt",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
}
IMAGE_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "dvb_subtitle",
    "xsub",
}


def get_embedded_subtitle_streams(video_path: str | Path, subtitle_probe=None) -> list[dict]:
    resolved_path = validate_input_video(video_path)
    streams = []
    for stream in (subtitle_probe or probe_subtitle_streams)(resolved_path):
        if stream.get("codec_type") not in (None, "subtitle"):
            continue

        candidate = _embedded_candidate(stream)
        logger.info(
            "[Subtitles] Embedded stream detected: index=%s, codec=%s, language=%s",
            candidate["stream_index"],
            candidate["codec_name"],
            candidate["language_code"],
        )
        streams.append(candidate)
    return streams


def has_embedded_subtitles(video_path: str | Path) -> bool:
    return len(get_embedded_subtitle_streams(video_path)) > 0


def _embedded_candidate(stream: dict) -> dict:
    tags = stream.get("tags") or {}
    codec_name = (stream.get("codec_name") or "").casefold() or None
    kind, is_text_readable, note = _classify_embedded_codec(codec_name)
    language_code = tags.get("language")
    title = tags.get("title")
    handler_name = tags.get("handler_name")
    label = title or handler_name
    candidate = {
        "source": "embedded",
        "kind": kind,
        "is_text_readable": is_text_readable,
        "language_code": language_code,
        "language_name": _language_name(language_code),
        "label": label,
        "stream_index": stream.get("index"),
        "index": stream.get("index"),
        "codec_name": codec_name,
        "codec": codec_name,
        "title": title,
        "handler_name": handler_name,
        "file_path": None,
        "format": None,
        "match_type": None,
        "filename_suffix": None,
    }
    if note is not None:
        candidate["note"] = note
    return candidate


def _classify_embedded_codec(codec_name: str | None) -> tuple[str, bool, str | None]:
    if codec_name in TEXT_SUBTITLE_CODECS:
        return "text", True, None
    if codec_name in IMAGE_SUBTITLE_CODECS:
        return "image", False, "Image-based subtitle; text processing not supported yet"
    return "unknown", False, "Unsupported subtitle codec; text processing not supported yet"


def _language_name(language_code: str | None) -> str | None:
    return resolve_language_name(language_code)
