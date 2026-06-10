from pathlib import Path

from services.infrastructure.ffmpeg.probe import run_json_probe
from services.infrastructure.ffmpeg.paths import get_ffprobe_path
from services.infrastructure.ffmpeg.runner import FFmpegService


def probe_subtitle_streams(
    media_path: str | Path,
    ffmpeg_service: FFmpegService | None = None,
    probe_runner=None,
) -> list[dict]:
    ffprobe_path = ffmpeg_service.ffprobe_path if ffmpeg_service else get_ffprobe_path()
    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name,codec_type:stream_tags=language,title,handler_name",
        "-of",
        "json",
        str(media_path),
    ]
    return run_json_probe(command, probe_runner).get("streams", [])
