"""Packet-level index of the first video stream, used to make stream-copy cuts verifiable.

Stream copy cannot cut inside a GOP, and FFmpeg's ``-to``/``-t`` stop on decoding timestamps:
with B-frames the keyframe that opens the next GOP (and the P-frame after it) are still copied
because their DTS precede their PTS. The helpers below decide, from the real packet order,
whether a time range can be copied without carrying any frame from outside it, how many
packets such a copy must contain, and which packet hashes the copied chunk must reproduce.

Time semantics are half-open: a frame belongs to [start, end) iff start <= pts < end.
"""

import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from services.infrastructure.ffmpeg.runner import FFmpegService

TIME_EPSILON_SECONDS = 1e-6
PACKET_HASH_ALGORITHM = "murmur3"


@dataclass(frozen=True)
class VideoPacket:
    pts_seconds: float
    keyframe: bool
    data_hash: str


class VideoPacketIndexError(RuntimeError):
    pass


class VideoPacketIndexService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        probe_runner=None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.probe_runner = probe_runner or subprocess.run

    def probe(self, media_path: str | Path, stream: str = "v:0") -> list[VideoPacket]:
        """Return a stream's packets (first video stream by default) in decoding order.

        PTS are relative to the container start time, the timeline used by ``-ss`` and by the player.
        """
        command = [
            str(self.ffmpeg_service.ffprobe_path),
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_data_hash",
            PACKET_HASH_ALGORITHM,
            "-show_entries",
            "format=start_time:packet=pts_time,flags,data_hash",
            "-of",
            "csv=p=0",
            str(media_path),
        ]
        completed = self.probe_runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise VideoPacketIndexError(f"Could not read packet timestamps: {(completed.stderr or '').strip()[-300:]}")
        return parse_packet_csv(completed.stdout or "")


def parse_packet_csv(text: str) -> list[VideoPacket]:
    rows = []
    start_time = 0.0
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 1 and fields[0]:
            start_time = _float_or_none(fields[0]) or 0.0
            continue
        if len(fields) < 3:
            continue
        pts = _float_or_none(fields[0])
        if pts is None:
            raise VideoPacketIndexError("A video packet has no presentation timestamp; exact cutting cannot be verified.")
        rows.append((pts, "K" in fields[1], fields[2]))
    if not rows:
        raise VideoPacketIndexError("The source has no readable video packets.")
    return [VideoPacket(round(pts - start_time, 6), keyframe, data_hash) for pts, keyframe, data_hash in rows]


def packets_in_range(packets: list[VideoPacket], start_seconds: float, end_seconds: float) -> list[VideoPacket]:
    """Packets whose PTS lies in [start, end), in decoding order."""
    return [packet for packet in packets if _in_range(packet.pts_seconds, start_seconds, end_seconds)]


def is_clean_cut_point(packets: list[VideoPacket], seconds: float) -> bool:
    """True when decoding order splits exactly at ``seconds`` on a keyframe.

    Every packet presented before ``seconds`` must be decoded before every packet presented at or
    after it, and the first packet at or after it (in decoding order) must be a keyframe. Only then
    can a stream copy start or stop at ``seconds`` without carrying a frame across the boundary.
    """
    before = [position for position, packet in enumerate(packets) if packet.pts_seconds < seconds - TIME_EPSILON_SECONDS]
    after = [position for position, packet in enumerate(packets) if packet.pts_seconds >= seconds - TIME_EPSILON_SECONDS]
    if not after:
        return True
    if before and max(before) > min(after):
        return False
    return packets[min(after)].keyframe


def copyable_range(packets: list[VideoPacket], start_seconds: float, end_seconds: float) -> list[VideoPacket] | None:
    """Packets a stream copy of [start, end) must contain, or None if no exact stream copy exists."""
    if not is_clean_cut_point(packets, start_seconds) or not is_clean_cut_point(packets, end_seconds):
        return None
    selected = packets_in_range(packets, start_seconds, end_seconds)
    return selected or None


def first_frame_at_or_after(packets: list[VideoPacket], seconds: float) -> float | None:
    return min(
        (packet.pts_seconds for packet in packets if packet.pts_seconds >= seconds - TIME_EPSILON_SECONDS),
        default=None,
    )


def nearest_keyframes(packets: list[VideoPacket], seconds: float) -> tuple[float | None, float | None]:
    keyframes = sorted(packet.pts_seconds for packet in packets if packet.keyframe)
    previous = max((value for value in keyframes if value <= seconds + TIME_EPSILON_SECONDS), default=None)
    following = min((value for value in keyframes if value >= seconds - TIME_EPSILON_SECONDS), default=None)
    return previous, following


def hashes(packets: list[VideoPacket]) -> list[str]:
    return [packet.data_hash for packet in packets]


def frame_signature(packets: list[VideoPacket]) -> list[str]:
    """Hashes of non-key packets plus keyframe positions.

    Concatenating chunks whose codec extradata differs (stream copy next to re-encoded chunks) makes
    FFmpeg repeat the parameter sets in-band on keyframes, which changes those packets' bytes but not
    the pictures. Keyframes are therefore compared by position only; any reordering, loss or extra
    frame still changes the surrounding non-key hashes.
    """
    return ["keyframe" if packet.keyframe else packet.data_hash for packet in packets]


def source_position(packets: list[VideoPacket], packet: VideoPacket) -> float | None:
    """PTS of the first source packet with the same data, used to explain verification failures."""
    return next((candidate.pts_seconds for candidate in packets if candidate.data_hash == packet.data_hash), None)


def _in_range(pts: float, start_seconds: float, end_seconds: float) -> bool:
    return start_seconds - TIME_EPSILON_SECONDS <= pts < end_seconds - TIME_EPSILON_SECONDS


def _float_or_none(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def kept_frame_durations(packets: list[VideoPacket], kept_intervals: list[tuple[float, float]]) -> list[float]:
    """How long each kept source frame is shown, in presentation order (its distance to the next source frame)."""
    times = sorted(packet.pts_seconds for packet in packets)
    gaps = sorted(later - earlier for earlier, later in pairwise(times))
    nominal = gaps[len(gaps) // 2] if gaps else 0.0
    durations = []
    for position, pts in enumerate(times):
        if any(_in_range(pts, start, end) for start, end in kept_intervals):
            following = times[position + 1] if position + 1 < len(times) else pts + nominal
            durations.append(following - pts)
    return durations


def timeline_mismatch(packets: list[VideoPacket], expected_durations: list[float], tolerance: float) -> str | None:
    """None when consecutive output frames are spaced exactly as the kept source frames were shown."""
    times = sorted(packet.pts_seconds for packet in packets)
    if len(times) != len(expected_durations):
        return f"{len(times)} frames instead of {len(expected_durations)}"
    for position, (earlier, later) in enumerate(pairwise(times)):
        if abs((later - earlier) - expected_durations[position]) > tolerance:
            return (
                f"frame {position} at {earlier:.3f}s is shown for {(later - earlier) * 1000:.1f} ms "
                f"instead of {expected_durations[position] * 1000:.1f} ms"
            )
    return None
