from pathlib import Path

from core.time_utils import parse_fraction_to_float
from services.infrastructure.ffmpeg.probe import probe_media
from services.media.validation_service import validate_input_video


def _first_stream(raw: dict, codec_type: str) -> dict | None:
    for stream in raw.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return None


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_video_metadata(video_path: str | Path, media_probe=None) -> dict:
    resolved_path = validate_input_video(video_path)
    raw = (media_probe or probe_media)(resolved_path)
    format_data = raw.get("format") or {}
    video_stream = _first_stream(raw, "video") or {}
    audio_stream = _first_stream(raw, "audio") or {}

    video_summary = None
    if video_stream:
        video_summary = {
            "stream_index": _optional_int(video_stream.get("index")),
            "codec_name": video_stream.get("codec_name"),
            "codec_long_name": video_stream.get("codec_long_name"),
            "width": _optional_int(video_stream.get("width")),
            "height": _optional_int(video_stream.get("height")),
            "fps": parse_fraction_to_float(video_stream.get("avg_frame_rate"))
            or parse_fraction_to_float(video_stream.get("r_frame_rate")),
            "pix_fmt": video_stream.get("pix_fmt"),
        }

    audio_summary = None
    if audio_stream:
        audio_summary = {
            "stream_index": _optional_int(audio_stream.get("index")),
            "codec_name": audio_stream.get("codec_name"),
            "codec_long_name": audio_stream.get("codec_long_name"),
            "channels": _optional_int(audio_stream.get("channels")),
            "sample_rate": _optional_int(audio_stream.get("sample_rate")),
        }

    return {
        "path": str(resolved_path),
        "filename": resolved_path.name,
        "stem": resolved_path.stem,
        "extension": resolved_path.suffix.lower(),
        "file_size_bytes": resolved_path.stat().st_size,
        "duration_seconds": _optional_float(format_data.get("duration")),
        "format_name": format_data.get("format_name"),
        "format_long_name": format_data.get("format_long_name"),
        "bit_rate": _optional_int(format_data.get("bit_rate")),
        "video": video_summary,
        "audio": audio_summary,
        "raw_ffprobe": raw,
    }
