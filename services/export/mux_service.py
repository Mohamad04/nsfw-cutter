import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubtitleMuxInput:
    path: Path
    language_code: str | None = None
    title: str | None = None
    format: str | None = None


@dataclass(frozen=True)
class MuxResult:
    output_path: Path
    muxed_subtitle_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MuxError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while muxing the final output.")


class MuxService:
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

    def mux(
        self,
        video_path: str | Path,
        audio_path: str | Path | None,
        subtitle_inputs: list[SubtitleMuxInput],
        output_path: str | Path,
        progress_callback=None,
    ) -> MuxResult:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_mux_command(Path(video_path), Path(audio_path) if audio_path else None, subtitle_inputs, output_path)
        self._run_command(command)
        _emit(progress_callback, 100, "Muxed smart cut output")
        return MuxResult(
            output_path=output_path,
            muxed_subtitle_paths=[subtitle.path for subtitle in subtitle_inputs],
        )

    def build_mux_command(
        self,
        video_path: Path,
        audio_path: Path | None,
        subtitle_inputs: list[SubtitleMuxInput],
        output_path: Path,
    ) -> list[str]:
        command = [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
        ]
        input_index = 1
        audio_input_index = None
        if audio_path is not None:
            command.extend(["-i", str(audio_path)])
            audio_input_index = input_index
            input_index += 1

        subtitle_input_indices = []
        for subtitle in subtitle_inputs:
            command.extend(["-i", str(subtitle.path)])
            subtitle_input_indices.append(input_index)
            input_index += 1

        command.extend(["-map", "0:v:0"])
        if audio_input_index is not None:
            command.extend(["-map", f"{audio_input_index}:a:0"])
        for subtitle_input_index in subtitle_input_indices:
            command.extend(["-map", f"{subtitle_input_index}:0"])

        command.extend(["-c:v", "copy"])
        if audio_input_index is not None:
            command.extend(["-c:a", "copy"])
        if subtitle_inputs:
            command.extend(["-c:s", _subtitle_codec_for_output(output_path)])

        subtitle_stream_index = 0
        for subtitle in subtitle_inputs:
            if subtitle.language_code:
                command.extend([f"-metadata:s:s:{subtitle_stream_index}", f"language={subtitle.language_code}"])
            if subtitle.title:
                command.extend([f"-metadata:s:s:{subtitle_stream_index}", f"title={subtitle.title}"])
            subtitle_stream_index += 1

        command.append(str(output_path))
        return command

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running Smart Cutting mux command: %s", command)
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
            raise MuxError(command, completed.returncode, completed.stderr or "")


def _subtitle_codec_for_output(output_path: Path) -> str:
    if output_path.suffix.lower() in {".mp4", ".m4v", ".mov"}:
        return "mov_text"
    return "copy"


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)

