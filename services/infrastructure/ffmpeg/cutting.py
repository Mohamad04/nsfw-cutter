import json
import logging
import subprocess
from pathlib import Path

from core.time_utils import duration_seconds, seconds_to_ffmpeg_time
from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


class VideoCutError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(
            "Video export failed. This workflow uses FFmpeg stream copy and the source streams must support it."
        )


class FFmpegCuttingService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
        probe_runner=None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.probe_runner = probe_runner or subprocess.run
        self.commands: list[list[str]] = []
        self.stderr: list[str] = []

    def reset_diagnostics(self) -> None:
        self.commands = []
        self.stderr = []

    def export_interval(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_command(
            self.build_cut_command(input_path, output_path, start_seconds, end_seconds)
        )
        return output_path

    def concat_stream_copy_segments(
        self,
        temporary_segments: list[Path],
        output_path: Path,
    ) -> None:
        concat_list_path = temporary_segments[0].parent / "concat_list.txt"
        concat_list_path.write_text(
            "\n".join(_concat_line(path) for path in temporary_segments),
            encoding="utf-8",
        )
        self._run_command(self.build_concat_command(concat_list_path, output_path))

    def build_cut_command(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> list[str]:
        return [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-ss",
            seconds_to_ffmpeg_time(start_seconds),
            "-i",
            str(input_path),
            "-t",
            seconds_to_ffmpeg_time(duration_seconds(start_seconds, end_seconds)),
            "-map",
            "0",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]

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
            "0",
            "-c",
            "copy",
            str(output_path),
        ]

    def probe_media(self, media_path: str | Path) -> dict:
        command = [
            str(self.ffmpeg_service.ffprobe_path),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ]
        logger.info("Running ffprobe command: %s", command)
        completed = self.probe_runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise VideoCutError(command, completed.returncode, completed.stderr)

        raw = json.loads(completed.stdout or "{}")
        format_data = raw.get("format") or {}
        duration_value = format_data.get("duration")
        duration = float(duration_value) if duration_value not in (None, "") else None
        return {
            "duration_seconds": duration,
            "has_audio": any(
                stream.get("codec_type") == "audio" for stream in raw.get("streams", [])
            ),
            "raw_ffprobe": raw,
        }

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running FFmpeg command: %s", command)
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
        logger.info("FFmpeg return code: %s", completed.returncode)
        if completed.stderr:
            logger.info("FFmpeg stderr: %s", completed.stderr)
        if completed.returncode != 0:
            logger.error("FFmpeg export failed: %s", completed.stderr)
            raise VideoCutError(command, completed.returncode, completed.stderr)


def _concat_line(path: Path) -> str:
    escaped_path = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped_path}'"
