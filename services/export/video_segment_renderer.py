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
from services.export.video_packet_index import (
    VideoPacket,
    VideoPacketIndexService,
    copyable_range,
    frame_signature,
    hashes,
    packets_in_range,
    source_position,
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
    frame_signature: tuple[str, ...] = ()
    fallback_reason: str | None = None


class VideoSegmentRenderError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__("Smart Cutting failed while rendering video chunks.")


class VideoSegmentVerificationError(RuntimeError):
    pass


class VideoSegmentRenderer:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
        packet_index_service: VideoPacketIndexService | None = None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.packet_index_service = packet_index_service or VideoPacketIndexService(ffmpeg_service=self.ffmpeg_service)
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
        source_packets: list[VideoPacket] | None = None,
    ) -> list[RenderedVideoChunk]:
        """Render the kept plan segments.

        With ``source_packets`` every chunk is rendered frame-exact and verified: a copy chunk must
        contain exactly the source packets presented in [start, end) (compared by data hash), a
        re-encoded chunk exactly as many frames. A copy segment that cannot be stream-copied without
        carrying frames across its boundaries (open GOP, reordered frames) is re-encoded instead and
        reported through ``fallback_reason``.
        """
        chunks_dir = Path(chunks_dir)
        chunks_dir.mkdir(parents=True, exist_ok=True)
        render_segments = [segment for segment in plan.segments if segment.type != DELETE_SEGMENT]
        if not render_segments:
            raise ValueError("Smart Cutting has no kept video chunks to export.")

        chunks = []
        for offset, segment in enumerate(render_segments, start=1):
            output_path = chunks_dir / f"chunk_{offset:04d}_{segment.type}.mp4"
            if source_packets is not None:
                chunk = self._render_verified_chunk(Path(input_path), output_path, offset, segment, source_packets)
                if chunk is not None:
                    chunks.append(chunk)
                _emit(
                    progress_callback,
                    int(offset / len(render_segments) * 100),
                    f"Rendered smart video chunk {offset}/{len(render_segments)}",
                )
                continue
            command = self.build_command(Path(input_path), output_path, segment)
            stderr = self._run_command(command)
            if _ffmpeg_reported_empty_output(stderr):
                logger.warning(
                    "Skipping Smart Cutting video chunk %s because FFmpeg produced no video frames: %s",
                    output_path,
                    segment,
                )
            else:
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
        frame_count: int | None = None,
    ) -> list[str]:
        command = [
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
        ]
        if frame_count is not None:
            # -to stops on decoding timestamps: with B-frames the next GOP's keyframe would be copied too.
            command.extend(["-frames:v", str(frame_count)])
        command.extend(["-avoid_negative_ts", "make_zero", str(output_path)])
        return command

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

    def _render_verified_chunk(
        self,
        input_path: Path,
        output_path: Path,
        offset: int,
        segment: SmartCutPlanSegment,
        source_packets: list[VideoPacket],
    ) -> RenderedVideoChunk | None:
        expected = packets_in_range(source_packets, segment.start_seconds, segment.end_seconds)
        if not expected:
            logger.warning("Skipping Smart Cutting video chunk with no source frames: %s", segment)
            return None

        fallback_reason = None
        decode_start = segment.decode_start_seconds if segment.decode_start_seconds is not None else segment.start_seconds
        if segment.type == COPY_SEGMENT:
            copy_packets = copyable_range(source_packets, segment.start_seconds, segment.end_seconds)
            if copy_packets is not None:
                self._run_command(
                    self.build_copy_command(
                        input_path,
                        output_path,
                        segment.start_seconds,
                        segment.end_seconds,
                        frame_count=len(copy_packets),
                    )
                )
                actual = self.packet_index_service.probe(output_path)
                if hashes(actual) != hashes(copy_packets):
                    first = source_position(source_packets, actual[0]) if actual else None
                    started = f"{first:.3f}s" if first is not None else "an unknown frame"
                    raise VideoSegmentVerificationError(
                        "Smart Cutting stopped: FFmpeg did not stream-copy exactly the source frames of "
                        f"{segment.start_seconds:.3f}s-{segment.end_seconds:.3f}s (the copy started at {started}). "
                        "Nothing was exported."
                    )
                return _chunk(offset, segment, output_path, actual, None)
            fallback_reason = (
                "Stream copy would carry frames across a cut boundary (open GOP or reordered frames); "
                "this segment was re-encoded."
            )
            logger.warning("Smart Cutting re-encodes copy segment %s: %s", segment, fallback_reason)

        self._run_command(
            self.build_reencode_command(
                input_path,
                output_path,
                decode_start,
                segment.start_seconds,
                segment.end_seconds,
            )
        )
        actual = self.packet_index_service.probe(output_path)
        if len(actual) != len(expected):
            raise VideoSegmentVerificationError(
                "Smart Cutting stopped: the re-encoded video chunk "
                f"{segment.start_seconds:.3f}s-{segment.end_seconds:.3f}s has {len(actual)} frames, "
                f"expected {len(expected)}. Nothing was exported."
            )
        return _chunk(offset, segment, output_path, actual, fallback_reason)

    def _run_command(self, command: list[str]) -> str:
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
        return completed.stderr or ""


def _chunk(
    offset: int,
    segment: SmartCutPlanSegment,
    output_path: Path,
    packets: list[VideoPacket],
    fallback_reason: str | None,
) -> RenderedVideoChunk:
    return RenderedVideoChunk(
        index=offset,
        segment_type=segment.type,
        output_path=output_path,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        frame_signature=tuple(frame_signature(packets)),
        fallback_reason=fallback_reason,
    )


def _ffmpeg_reported_empty_output(stderr: str) -> bool:
    return "Output file is empty, nothing was encoded" in stderr


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)
