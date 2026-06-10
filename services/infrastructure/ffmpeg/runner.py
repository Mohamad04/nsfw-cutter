from pathlib import Path

from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    find_executable,
    get_ffmpeg_path,
    get_ffprobe_path,
)


__all__ = ["FFmpegNotFoundError", "FFmpegService", "resolve_binary"]


class FFmpegService:
    def __init__(
        self,
        ffmpeg_path: str | Path | None = None,
        ffprobe_path: str | Path | None = None,
    ):
        self.ffmpeg_path = Path(ffmpeg_path) if ffmpeg_path else self.resolve_ffmpeg()
        self.ffprobe_path = Path(ffprobe_path) if ffprobe_path else self.resolve_ffprobe()

    def resolve_ffmpeg(self) -> Path:
        return get_ffmpeg_path()

    def resolve_ffprobe(self) -> Path:
        return get_ffprobe_path()


def resolve_binary(executable: str) -> Path:
    return find_executable(executable)
