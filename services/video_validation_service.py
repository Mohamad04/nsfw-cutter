from pathlib import Path


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv"}


def validate_input_video(video_path: str | Path) -> Path:
    path = Path(video_path).expanduser()
    if not path.exists():
        raise ValueError("Selected video file does not exist")
    if not path.is_file():
        raise ValueError("Selected path is not a video file")
    if path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ValueError("Unsupported video format. Use .mp4 or .mkv")
    return path.resolve()
