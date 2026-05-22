import json
from pathlib import Path

from core.ffmpeg_runner import ensure_ffprobe_available, run_command
from services.video_validation_service import validate_input_video


def get_embedded_subtitle_streams(video_path: str | Path) -> list[dict]:
    resolved_path = validate_input_video(video_path)
    ensure_ffprobe_available()
    output = run_command(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(resolved_path),
        ]
    )
    raw = json.loads(output)
    streams = []
    for stream in raw.get("streams", []):
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
