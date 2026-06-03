from pathlib import Path

from services.infrastructure.ffmpeg.subtitles import probe_subtitle_streams
from services.media.validation_service import validate_input_video


def get_embedded_subtitle_streams(video_path: str | Path, subtitle_probe=None) -> list[dict]:
    resolved_path = validate_input_video(video_path)
    streams = []
    for stream in (subtitle_probe or probe_subtitle_streams)(resolved_path):
        tags = stream.get("tags") or {}
        streams.append(
            {
                "index": stream.get("index"),
                "codec_name": stream.get("codec_name"),
                "language": tags.get("language"),
                "title": tags.get("title"),
            }
        )
    return streams


def has_embedded_subtitles(video_path: str | Path) -> bool:
    return len(get_embedded_subtitle_streams(video_path)) > 0
