from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

from services.analysis.cancellation import CancellationToken
from services.analysis.preprocessing_contracts import (
    MICROSECONDS_PER_SECOND,
    PreprocessingConfig,
    ProcessingChunk,
    SampleReason,
)
from services.analysis.process import CancellableProcessRunner
from services.infrastructure.ffmpeg.runner import FFmpegService

if TYPE_CHECKING:
    from services.analysis.preprocessing_instrumentation import (
        PreprocessingInstrumentation,
    )


_SHOWINFO_CONFIG_PATTERN = re.compile(
    r"\[showinfo@preprocess_sample\s+@[^]]+]\s+config in time_base:\s*(\d+)/(\d+)"
)
_SHOWINFO_FRAME_PATTERN = re.compile(
    r"\[showinfo@preprocess_sample\s+@[^]]+]\s+n:\s*\d+\s+"
    r"pts:\s*(-?\d+)\s+pts_time:([^\s]+).*?\bs:(\d+)x(\d+)"
)
_SCENE_SCORE_PATTERN = re.compile(
    r"\[metadata@preprocess_scene_score\s+@[^]]+]\s+lavfi\.scene_score=([0-9.eE+-]+)"
)


@dataclass(frozen=True)
class ExtractedFrame:
    """Ephemeral RGB frame plus source timing; pixels never enter result contracts."""

    timestamp_us: int
    source_pts: int | None
    source_time_base: str | None
    processing_chunk_index: int
    sample_reasons: frozenset[SampleReason]
    width: int
    height: int
    content_rect: tuple[int, int, int, int]
    scene_score: float | None
    rgb_bytes: bytes


@dataclass(frozen=True)
class _SampleMetadata:
    timestamp_us: int
    source_pts: int
    source_time_base: str | None
    reasons: frozenset[SampleReason]
    content_width: int
    content_height: int
    scene_score: float | None


class FFmpegHybridFrameExtractor:
    """Stream hybrid temporal/scene samples from one FFmpeg decode per work unit."""

    def __init__(
        self,
        *,
        ffmpeg_service: FFmpegService | None = None,
        process_runner: CancellableProcessRunner | None = None,
        instrumentation: PreprocessingInstrumentation | None = None,
    ) -> None:
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.instrumentation = instrumentation
        self.process_runner = process_runner or CancellableProcessRunner(
            instrumentation=instrumentation
        )

    def extract(
        self,
        video_path: str | Path,
        chunk: ProcessingChunk,
        config: PreprocessingConfig,
        cancellation: CancellationToken,
    ) -> Iterator[ExtractedFrame]:
        cancellation.raise_if_cancelled()
        collector = _FFmpegMetadataCollector(config)
        command = self.build_command(video_path, chunk, config)
        frame_size = config.target_width * config.target_height * 3
        raw_buffer = bytearray()

        byte_stream = self.process_runner.stream_stdout(
            command,
            cancellation=cancellation,
            stderr_callback=collector.accept_line,
        )
        byte_iterator = iter(byte_stream)
        try:
            while True:
                wait_started_at = (
                    time.perf_counter() if self.instrumentation is not None else 0.0
                )
                try:
                    block = next(byte_iterator)
                except StopIteration:
                    if self.instrumentation is not None:
                        self.instrumentation.add_duration(
                            "extractor_stream_wait_seconds",
                            time.perf_counter() - wait_started_at,
                        )
                    break
                if self.instrumentation is not None:
                    self.instrumentation.add_duration(
                        "extractor_stream_wait_seconds",
                        time.perf_counter() - wait_started_at,
                    )
                cancellation.raise_if_cancelled()
                assembly_started_at = (
                    time.perf_counter() if self.instrumentation is not None else 0.0
                )
                raw_buffer.extend(block)
                if self.instrumentation is not None:
                    self.instrumentation.add_duration(
                        "frame_assembly_seconds",
                        time.perf_counter() - assembly_started_at,
                    )
                while len(raw_buffer) >= frame_size:
                    assembly_started_at = (
                        time.perf_counter() if self.instrumentation is not None else 0.0
                    )
                    rgb_bytes = bytes(raw_buffer[:frame_size])
                    del raw_buffer[:frame_size]
                    metadata = collector.next_metadata(cancellation)
                    content_rect = _centered_content_rect(
                        config.target_width,
                        config.target_height,
                        metadata.content_width,
                        metadata.content_height,
                    )
                    frame = ExtractedFrame(
                        timestamp_us=metadata.timestamp_us,
                        source_pts=metadata.source_pts,
                        source_time_base=metadata.source_time_base,
                        processing_chunk_index=chunk.index,
                        sample_reasons=metadata.reasons,
                        width=config.target_width,
                        height=config.target_height,
                        content_rect=content_rect,
                        scene_score=metadata.scene_score,
                        rgb_bytes=rgb_bytes,
                    )
                    if self.instrumentation is not None:
                        self.instrumentation.add_duration(
                            "frame_assembly_seconds",
                            time.perf_counter() - assembly_started_at,
                        )
                        self.instrumentation.increment("frames_extracted")
                    yield frame
        finally:
            byte_stream.close()

        if raw_buffer:
            raise RuntimeError("FFmpeg returned an incomplete RGB frame")
        if collector.pending_count:
            raise RuntimeError("FFmpeg frame metadata did not match RGB output")

    def build_command(
        self,
        video_path: str | Path,
        chunk: ProcessingChunk,
        config: PreprocessingConfig,
    ) -> list[str | Path]:
        decode_duration_us = chunk.decode_end_us - chunk.decode_start_us
        filter_graph = _build_filter_graph(config)
        return [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-nostdin",
            "-copyts",
            "-start_at_zero",
            "-ss",
            _format_seconds(chunk.decode_start_us),
            "-t",
            _format_seconds(decode_duration_us),
            "-i",
            Path(video_path),
            "-filter_complex",
            f"[0:{config.selected_video_stream_index}]{filter_graph}[sampled]",
            "-map",
            "[sampled]",
            "-an",
            "-sn",
            "-dn",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]


class _FFmpegMetadataCollector:
    def __init__(self, config: PreprocessingConfig) -> None:
        self._condition = threading.Condition()
        self._frames: deque[_SampleMetadata] = deque()
        self._source_time_base: Fraction | None = None
        self._pending_scene_score: float | None = None
        self._last_temporal_bucket: int | None = None
        self._scene_threshold = config.scene_threshold
        self._temporal_cadence_us = max(1, config.max_sampling_gap_us // 2)

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._frames)

    def accept_line(self, line: str) -> None:
        config_match = _SHOWINFO_CONFIG_PATTERN.search(line)
        if config_match is not None:
            numerator = int(config_match.group(1))
            denominator = int(config_match.group(2))
            if numerator > 0 and denominator > 0:
                with self._condition:
                    self._source_time_base = Fraction(numerator, denominator)
            return

        score_match = _SCENE_SCORE_PATTERN.search(line)
        if score_match is not None:
            with self._condition:
                self._pending_scene_score = float(score_match.group(1))
            return

        frame_match = _SHOWINFO_FRAME_PATTERN.search(line)
        if frame_match is None:
            return

        source_pts = int(frame_match.group(1))
        pts_time = frame_match.group(2)
        content_width = int(frame_match.group(3))
        content_height = int(frame_match.group(4))
        with self._condition:
            timestamp_us = _timestamp_us(source_pts, pts_time, self._source_time_base)
            scene_score = self._pending_scene_score
            self._pending_scene_score = None
            temporal_bucket = timestamp_us // self._temporal_cadence_us
            reasons: set[SampleReason] = set()
            if temporal_bucket != self._last_temporal_bucket:
                reasons.add(SampleReason.TEMPORAL_SAFETY)
                self._last_temporal_bucket = temporal_bucket
            if scene_score is not None and scene_score > self._scene_threshold:
                reasons.add(SampleReason.SCENE_TRANSITION)
            if not reasons:
                # The union select emitted this frame, so missing score metadata can
                # only mean it came from the scene branch of the expression.
                reasons.add(SampleReason.SCENE_TRANSITION)
            source_time_base = (
                f"{self._source_time_base.numerator}/{self._source_time_base.denominator}"
                if self._source_time_base is not None
                else None
            )
            self._frames.append(
                _SampleMetadata(
                    timestamp_us=max(0, timestamp_us),
                    source_pts=source_pts,
                    source_time_base=source_time_base,
                    reasons=frozenset(reasons),
                    content_width=content_width,
                    content_height=content_height,
                    scene_score=scene_score,
                )
            )
            self._condition.notify()

    def next_metadata(self, cancellation: CancellationToken) -> _SampleMetadata:
        deadline = time.monotonic() + 10.0
        with self._condition:
            while not self._frames:
                cancellation.raise_if_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise RuntimeError("Timed out waiting for FFmpeg frame metadata")
                self._condition.wait(timeout=min(0.05, remaining))
            return self._frames.popleft()


def _build_filter_graph(config: PreprocessingConfig) -> str:
    # Sampling at half the configured maximum gives enough headroom for the first
    # real VFR frame after a bucket boundary. If the source itself has a gap larger
    # than the configured maximum, no decoder can synthesize missing source images.
    temporal_cadence = config.max_sampling_gap_seconds / 2.0
    temporal_expression = (
        "isnan(prev_t)+"
        f"gt(floor(t/{temporal_cadence:.9f})\\,floor(prev_t/{temporal_cadence:.9f}))"
    )
    scene_expression = f"gt(scene\\,{config.scene_threshold:.9f})"
    select_expression = f"select='{temporal_expression}+{scene_expression}'"
    return ",".join(
        (
            "scale="
            f"w={config.target_width}:h={config.target_height}:"
            "force_original_aspect_ratio=decrease:flags=bilinear:reset_sar=1",
            select_expression,
            "metadata@preprocess_scene_score=mode=print:key=lavfi.scene_score",
            "showinfo@preprocess_sample",
            "settb=1/1000000",
            f"pad={config.target_width}:{config.target_height}:(ow-iw)/2:(oh-ih)/2:black",
            "format=rgb24",
        )
    )


def _timestamp_us(
    source_pts: int,
    pts_time: str,
    source_time_base: Fraction | None,
) -> int:
    if source_time_base is not None:
        value = Fraction(source_pts) * source_time_base * MICROSECONDS_PER_SECOND
        return _round_fraction(value)
    value = Decimal(pts_time) * MICROSECONDS_PER_SECOND
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _round_fraction(value: Fraction) -> int:
    if value >= 0:
        return (value.numerator * 2 + value.denominator) // (2 * value.denominator)
    positive = -value
    return -((positive.numerator * 2 + positive.denominator) // (2 * positive.denominator))


def _centered_content_rect(
    canvas_width: int,
    canvas_height: int,
    content_width: int,
    content_height: int,
) -> tuple[int, int, int, int]:
    if not (0 < content_width <= canvas_width and 0 < content_height <= canvas_height):
        raise RuntimeError("FFmpeg reported invalid scaled frame dimensions")
    return (
        (canvas_width - content_width) // 2,
        (canvas_height - content_height) // 2,
        content_width,
        content_height,
    )


def _format_seconds(value_us: int) -> str:
    return f"{value_us / MICROSECONDS_PER_SECOND:.6f}"
