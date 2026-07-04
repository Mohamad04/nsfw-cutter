import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.time_utils import seconds_to_ffmpeg_time
from services.export.smart_cut_planner import (
    COPY_SEGMENT,
    DELETE_SEGMENT,
    REENCODE_SEGMENT,
    SmartCutPlan,
    SmartCutPlanSegment,
)
from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderedVideoChunk:
    index: int
    segment_type: str
    output_path: Path
    start_seconds: float
    end_seconds: float


class VideoSegmentRenderError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while rendering video chunks.")


class VideoSegmentRenderer:
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

    def render_plan(
        self,
        input_path: str | Path,
        plan: SmartCutPlan,
        chunks_dir: str | Path,
        progress_callback=None,
    ) -> list[RenderedVideoChunk]:
        chunks_dir = Path(chunks_dir)
        chunks_dir.mkdir(parents=True, exist_ok=True)
        render_segments = [segment for segment in plan.segments if segment.type != DELETE_SEGMENT]
        if not render_segments:
            raise ValueError("Smart Cutting has no kept video chunks to export.")

        chunks = []
        for offset, segment in enumerate(render_segments, start=1):
            output_path = chunks_dir / f"chunk_{offset:04d}_{segment.type}.mp4"
            command = self.build_command(Path(input_path), output_path, segment)
            self._run_command(command)
            chunks.append(
                RenderedVideoChunk(
                    index=offset,
                    segment_type=segment.type,
                    output_path=output_path,
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                )
            )
            _emit(
                progress_callback,
                int(offset / len(render_segments) * 100),
                f"Rendered smart video chunk {offset}/{len(render_segments)}",
            )
        return chunks

    def build_command(
        self,
        input_path: Path,
        output_path: Path,
        segment: SmartCutPlanSegment,
    ) -> list[str]:
        if segment.type == COPY_SEGMENT:
            return self.build_copy_command(input_path, output_path, segment.start_seconds, segment.end_seconds)
        if segment.type == REENCODE_SEGMENT:
            return self.build_reencode_command(
                input_path,
                output_path,
                segment.decode_start_seconds if segment.decode_start_seconds is not None else segment.start_seconds,
                segment.start_seconds,
                segment.end_seconds,
            )
        raise ValueError(f"Unsupported smart cut video segment type: {segment.type}")

    def build_copy_command(
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
            "-to",
            seconds_to_ffmpeg_time(end_seconds),
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-c:v",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(output_path),
        ]

    def build_reencode_command(
        self,
        input_path: Path,
        output_path: Path,
        decode_start_seconds: float,
        output_start_seconds: float,
        output_end_seconds: float,
    ) -> list[str]:
        trim_start = max(0.0, output_start_seconds - decode_start_seconds)
        trim_end = max(trim_start, output_end_seconds - decode_start_seconds)
        return [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-ss",
            seconds_to_ffmpeg_time(decode_start_seconds),
            "-i",
            str(input_path),
            "-filter_complex",
            (
                f"[0:v]trim=start={trim_start:.3f}:end={trim_end:.3f},"
                "setpts=PTS-STARTPTS[v]"
            ),
            "-map",
            "[v]",
            "-an",
            "-sn",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

    def _run_command(self, command: list[str]) -> None:
        logger.info("Running Smart Cutting video command: %s", command)
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
            raise VideoSegmentRenderError(command, completed.returncode, completed.stderr or "")


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)
