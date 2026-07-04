import logging
import subprocess
from pathlib import Path

from services.export.video_segment_renderer import RenderedVideoChunk
from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


class VideoConcatError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while concatenating video chunks.")


class VideoConcatService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.commands: list[list[str]] = []
        self.stderr: list[str] = []

    def reset_diagnostics(self) -> None:
        self.commands = []
        self.stderr = []

    def concat_chunks(
        self,
        chunks: list[RenderedVideoChunk],
        concat_list_path: str | Path,
        output_path: str | Path,
        progress_callback=None,
    ) -> Path:
        if not chunks:
            raise ValueError("Smart Cutting has no video chunks to concatenate.")
        concat_list_path = Path(concat_list_path)
        output_path = Path(output_path)
        concat_list_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_list_path.write_text(
            "\n".join(_concat_line(chunk.output_path) for chunk in chunks),
            encoding="utf-8",
        )
        self._run_command(self.build_concat_command(concat_list_path, output_path))
        _emit(progress_callback, 100, "Concatenated smart video chunks")
        return output_path

    def build_concat_command(self, concat_list_path: Path, output_path: Path) -> list[str]:
        return [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            str(output_path),
        ]

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running Smart Cutting concat command: %s", command)
        completed = self.command_runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.commands.append(list(command))
        self.stderr.append(completed.stderr or "")
        if completed.returncode != 0:
            raise VideoConcatError(command, completed.returncode, completed.stderr or "")


def _concat_line(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)
