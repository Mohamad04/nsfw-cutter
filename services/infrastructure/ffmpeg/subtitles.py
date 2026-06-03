from pathlib import Path

from services.infrastructure.ffmpeg.probe import run_json_probe
from services.infrastructure.ffmpeg.runner import FFmpegService, resolve_binary


def probe_subtitle_streams(
    media_path: str | Path,
    ffmpeg_service: FFmpegService | None = None,
    probe_runner=None,
) -> list[dict]:
    ffprobe_path = ffmpeg_service.ffprobe_path if ffmpeg_service else resolve_binary("ffprobe")
    command = [
        str(ffprobe_path),
        "-v",
        "quiet",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=language,title",
        "-of",
        "json",
        str(media_path),
    ]
    return run_json_probe(command, probe_runner).get("streams", [])
