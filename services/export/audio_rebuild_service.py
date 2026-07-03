import logging
import subprocess
from pathlib import Path

from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


class AudioRebuildError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while rebuilding audio.")


class AudioRebuildService:
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

    def rebuild_audio(
        self,
        input_path: str | Path,
        kept_ranges: list[tuple[float, float]],
        output_path: str | Path,
        progress_callback=None,
    ) -> Path:
        if not kept_ranges:
            raise ValueError("Smart Cutting has no kept audio ranges to rebuild.")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_command(self.build_audio_command(Path(input_path), kept_ranges, output_path))
        _emit(progress_callback, 100, "Rebuilt smart cut audio")
        return output_path

    def build_audio_command(
        self,
        input_path: Path,
        kept_ranges: list[tuple[float, float]],
        output_path: Path,
    ) -> list[str]:
        filter_graph, output_label = self.build_filter_graph(kept_ranges)
        return [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
            "-filter_complex",
            filter_graph,
            "-map",
            output_label,
            "-vn",
            "-sn",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]

    def build_filter_graph(self, kept_ranges: list[tuple[float, float]]) -> tuple[str, str]:
        parts = []
        labels = []
        for index, (start_seconds, end_seconds) in enumerate(kept_ranges):
            label = f"a{index}"
            parts.append(
                (
                    f"[0:a:0]atrim=start={start_seconds:.3f}:end={end_seconds:.3f},"
                    f"asetpts=PTS-STARTPTS[{label}]"
                )
            )
            labels.append(f"[{label}]")
        if len(labels) == 1:
            return parts[0].replace("[a0]", "[a]"), "[a]"
        parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[a]")
        return ";".join(parts), "[a]"

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running Smart Cutting audio command: %s", command)
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
            raise AudioRebuildError(command, completed.returncode, completed.stderr or "")


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)
