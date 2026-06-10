import json
import subprocess
from pathlib import Path

from services.infrastructure.ffmpeg.paths import get_ffprobe_path
from services.infrastructure.ffmpeg.runner import FFmpegService


def probe_media(
    media_path: str | Path,
    ffmpeg_service: FFmpegService | None = None,
    probe_runner=None,
) -> dict:
    ffprobe_path = ffmpeg_service.ffprobe_path if ffmpeg_service else get_ffprobe_path()
    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]
    return run_json_probe(command, probe_runner)


def extract_keyframes(
    input_path: str | Path,
    ffmpeg_service: FFmpegService | None = None,
    probe_runner=None,
) -> list[float]:
    ffprobe_path = ffmpeg_service.ffprobe_path if ffmpeg_service else get_ffprobe_path()
    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-skip_frame",
        "nokey",
        "-show_entries",
        "frame=best_effort_timestamp_time",
        "-of",
        "json",
        str(input_path),
    ]
    payload = run_json_probe(command, probe_runner)
    keyframes = []
    for frame in payload.get("frames", []):
        value = frame.get("best_effort_timestamp_time")
        if value in (None, ""):
            continue
        keyframes.append(round(float(value), 3))
    return sorted(set(keyframes))


def run_json_probe(command: list[str], probe_runner=None) -> dict:
    runner = probe_runner or subprocess.run
    completed = runner(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Unable to read media data with ffprobe.")
    return json.loads(completed.stdout or "{}")
