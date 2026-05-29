import shutil
import sys
from pathlib import Path

from core.paths import get_resource_path


class FFmpegNotFoundError(RuntimeError):
    pass


class FFmpegService:
    def __init__(
        self,
        ffmpeg_path: str | Path | None = None,
        ffprobe_path: str | Path | None = None,
    ):
        self.ffmpeg_path = Path(ffmpeg_path) if ffmpeg_path else self.resolve_ffmpeg()
        self.ffprobe_path = Path(ffprobe_path) if ffprobe_path else self.resolve_ffprobe()

    def resolve_ffmpeg(self) -> Path:
        return self._resolve_binary("ffmpeg")

    def resolve_ffprobe(self) -> Path:
        return self._resolve_binary("ffprobe")

    def _resolve_binary(self, executable: str) -> Path:
        candidates = [
            get_resource_path(f"bin/{executable}.exe"),
            get_resource_path(f"ffmpeg/{executable}.exe"),
            get_resource_path(f"tools/ffmpeg/bin/{executable}.exe"),
            get_resource_path(f"bin/{executable}"),
            get_resource_path(f"ffmpeg/{executable}"),
        ]

        for candidate in candidates:
            if candidate.is_file():
                return candidate

        for binary_name in self._system_binary_names(executable):
            system_binary = shutil.which(binary_name)
            if system_binary:
                return Path(system_binary)

        binary_label = "FFmpeg" if executable == "ffmpeg" else "ffprobe"
        raise FFmpegNotFoundError(
            f"{binary_label} was not found. Please install FFmpeg or bundle {executable}.exe with the app."
        )

    def _system_binary_names(self, executable: str) -> tuple[str, ...]:
        if sys.platform == "win32" and not executable.lower().endswith(".exe"):
            return (f"{executable}.exe", executable)
        return (executable,)
