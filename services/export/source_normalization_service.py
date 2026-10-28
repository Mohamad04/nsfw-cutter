"""Lossless MKV -> MP4 normalization so Smart Cutting can stream-copy MKV H.264 sources exactly.

Why: FFmpeg's input seek (``-ss`` before ``-i``) pulls the target back by about 0.13 s for demuxers
that cannot seek by PTS (Matroska) when a stream has B-frame delay, so a copy chunk requested at a
keyframe starts at the previous keyframe (defect D2). MP4 seeks by PTS, and the existing
frame-exact, hash-verified Smart Cutting pipeline is validated on MP4.

The remux copies the first video stream and the first audio stream bit for bit (no re-encoding).
It is accepted only if every video and audio packet of the normalized file has the same data, in
the same order, and the same position on the source timeline (PTS relative to the container start)
as in the source. Anything else is refused, so the export fails instead of cutting a timeline that
no longer matches what the user marked.
"""

import logging
import subprocess
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from services.export.media_probe_service import MediaInfo
from services.export.video_packet_index import VideoPacket, VideoPacketIndexService
from services.infrastructure.ffmpeg.runner import FFmpegService


logger = logging.getLogger(__name__)

MATROSKA_FORMAT_PREFIX = "matroska"
NORMALIZATION_METHOD = "mkv_to_mp4_stream_copy"
# Matroska stores millisecond timestamps; MP4 recomputes audio timestamps from sample counts.
VIDEO_PTS_TOLERANCE_SECONDS = 0.0005
AUDIO_PTS_TOLERANCE_SECONDS = 0.0011
# Frame spacing may vary by Matroska's 1 ms rounding (e.g. 41/42 ms at 23.976 fps), not more.
CONSTANT_FRAME_RATE_TOLERANCE_SECONDS = 0.0021
INCOMPLETE_FILE_TOLERANCE_SECONDS = 1.0


class SourceNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedSource:
    path: Path
    original_path: Path
    method: str
    video_packets: int
    audio_packets: int
    seconds: float
    bytes: int

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "original_path": str(self.original_path),
            "verified_video_packets": self.video_packets,
            "verified_audio_packets": self.audio_packets,
            "timeline": "identical to the source (PTS relative to container start)",
            "seconds": self.seconds,
            "bytes": self.bytes,
        }


def needs_normalization(media_info: MediaInfo) -> bool:
    return (media_info.format_name or "").casefold().startswith(MATROSKA_FORMAT_PREFIX)


class MkvNormalizationService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
        packet_index_service: VideoPacketIndexService | None = None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.packet_index_service = packet_index_service or VideoPacketIndexService(
            ffmpeg_service=self.ffmpeg_service,
            probe_runner=command_runner,
        )
        self.commands: list[list[str]] = []
        self.stderr: list[str] = []

    def reset_diagnostics(self) -> None:
        self.commands = []
        self.stderr = []

    def normalize(self, input_path: str | Path, output_path: str | Path, media_info: MediaInfo) -> NormalizedSource:
        input_path = Path(input_path)
        output_path = Path(output_path)
        if len(media_info.audio_streams) > 1:
            raise SourceNormalizationError(
                "Smart Cutting supports MKV files with at most one audio track; this file has "
                f"{len(media_info.audio_streams)}. Nothing was exported."
            )
        started = time.perf_counter()
        source_video = self.packet_index_service.probe(input_path, stream="v:0")
        _require_complete_file(source_video, media_info)
        _require_constant_frame_rate(source_video)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(input_path, output_path, has_audio=media_info.has_audio)
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
            raise SourceNormalizationError(
                "Smart Cutting could not prepare this MKV file for exact cutting "
                f"(lossless remux failed: {(completed.stderr or '').strip()[-200:]}). Nothing was exported."
            )

        video_packets = self._verify_stream(source_video, output_path, "v:0", VIDEO_PTS_TOLERANCE_SECONDS, "video")
        audio_packets = 0
        if media_info.has_audio:
            source_audio = self.packet_index_service.probe(input_path, stream="a:0")
            audio_packets = self._verify_stream(source_audio, output_path, "a:0", AUDIO_PTS_TOLERANCE_SECONDS, "audio")
        normalized = NormalizedSource(
            path=output_path,
            original_path=input_path,
            method=NORMALIZATION_METHOD,
            video_packets=video_packets,
            audio_packets=audio_packets,
            seconds=round(time.perf_counter() - started, 3),
            bytes=output_path.stat().st_size,
        )
        logger.info("MKV normalized for Smart Cutting: %s", normalized.to_dict())
        return normalized

    def build_command(self, input_path: Path, output_path: Path, has_audio: bool) -> list[str]:
        command = [
            str(self.ffmpeg_service.ffmpeg_path),
            "-y",
            "-hide_banner",
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
        ]
        if has_audio:
            command.extend(["-map", "0:a:0"])
        command.extend(["-sn", "-dn", "-c", "copy", str(output_path)])
        return command

    def _verify_stream(
        self,
        expected: list[VideoPacket],
        normalized: Path,
        stream: str,
        tolerance: float,
        label: str,
    ) -> int:
        actual = self.packet_index_service.probe(normalized, stream=stream)
        problem = _first_mismatch(expected, actual, tolerance)
        if problem:
            raise SourceNormalizationError(
                f"Smart Cutting could not verify the lossless MKV remux ({label}: {problem}). "
                "Nothing was exported."
            )
        return len(actual)


def _require_complete_file(packets: list[VideoPacket], media_info: MediaInfo) -> None:
    # Packet PTS are relative to the container start; Matroska's declared duration may include that start.
    last_frame = max(packet.pts_seconds for packet in packets)
    try:
        start_time = float((media_info.raw or {}).get("format", {}).get("start_time") or 0.0)
    except (TypeError, ValueError):
        start_time = 0.0
    declared = media_info.duration_seconds - max(0.0, start_time)
    if declared - last_frame > INCOMPLETE_FILE_TOLERANCE_SECONDS:
        raise SourceNormalizationError(
            f"This MKV file appears incomplete or damaged: it declares {declared:.3f}s of media but its "
            f"video stops at {last_frame:.3f}s. Nothing was exported."
        )


def _require_constant_frame_rate(packets: list[VideoPacket]) -> None:
    times = sorted(packet.pts_seconds for packet in packets)
    gaps = [later - earlier for earlier, later in pairwise(times)]
    if gaps and max(gaps) - min(gaps) > CONSTANT_FRAME_RATE_TOLERANCE_SECONDS:
        raise SourceNormalizationError(
            "Smart Cutting does not support variable-frame-rate MKV files yet (frame spacing varies from "
            f"{min(gaps) * 1000:.1f} to {max(gaps) * 1000:.1f} ms). Nothing was exported."
        )


def _first_mismatch(expected: list[VideoPacket], actual: list[VideoPacket], tolerance: float) -> str | None:
    if len(expected) != len(actual):
        return f"{len(actual)} packets instead of {len(expected)}"
    for position, (source, copy) in enumerate(zip(expected, actual, strict=True)):
        if source.data_hash != copy.data_hash:
            return f"packet {position} differs"
        if abs(source.pts_seconds - copy.pts_seconds) > tolerance:
            return f"packet {position} moved from {source.pts_seconds:.4f}s to {copy.pts_seconds:.4f}s"
    return None
