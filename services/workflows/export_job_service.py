import uuid
from pathlib import Path

from core.time_utils import utc_now_iso


def _new_job_id() -> str:
    timestamp = utc_now_iso().replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
    return f"export_{timestamp}_{uuid.uuid4().hex[:8]}"


def create_export_job_data(input_metadata: dict, subtitle_policy: dict, output_path: str | None = None) -> dict:
    input_path = Path(input_metadata["path"])
    destination = Path(output_path).expanduser() if output_path else input_path.with_name(f"{input_path.stem}_output.mkv")
    if destination.suffix.lower() != ".mkv":
        destination = destination.with_suffix(".mkv")

    video = input_metadata.get("video") or {}
    audio = input_metadata.get("audio") or {}
    duration = input_metadata.get("duration_seconds") or 0.0
    now = utc_now_iso()

    return {
        "job_id": _new_job_id(),
        "job_type": "export",
        "status": "pending",
        "progress": 0,
        "input_video": {
            "path": input_metadata["path"],
            "duration_seconds": input_metadata.get("duration_seconds"),
            "format_name": input_metadata.get("format_name"),
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "fps": video.get("fps"),
        },
        "output": {
            "path": str(destination.resolve()),
            "container": "mkv",
        },
        "export_settings": {
            "mode": "stream_copy",
            "reencode": False,
            "copy_video": True,
            "copy_audio": True,
            "copy_existing_subtitles": True,
        },
        "subtitle_policy": subtitle_policy,
        "segments": {
            "remove_segments": [],
            "safe_segments": [
                {
                    "start": 0.0,
                    "end": float(duration),
                }
            ],
        },
        "result": {
            "output_path": None,
            "error_message": None,
        },
        "created_at": now,
        "updated_at": now,
    }
