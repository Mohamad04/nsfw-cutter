from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from services.analysis.cancellation import CancellationToken
from services.analysis.chunking import owning_chunk_index, plan_processing_chunks
from services.analysis.frame_extraction import (
    ExtractedFrame,
    FFmpegHybridFrameExtractor,
)
from services.analysis.frame_filtering import SequentialFrameFilter
from services.analysis.preprocessing_contracts import (
    MICROSECONDS_PER_SECOND,
    FrameDisposition,
    FrameSample,
    PreprocessingConfig,
    PreprocessingResult,
    PreprocessingStatistics,
    SampleReason,
)
from services.analysis.preprocessing_instrumentation import (
    PreprocessingInstrumentation,
    SampleObservation,
)
from services.export.media_probe_service import MediaProbeService
from services.infrastructure.ffmpeg.runner import FFmpegService

ChunkProgressCallback = Callable[[int, int], None]
RepresentativeFrameCallback = Callable[[ExtractedFrame, FrameSample, CancellationToken], None]


@runtime_checkable
class FinalizableRepresentativeFrameCallback(Protocol):
    """Representative consumer with an explicit end-of-stream flush hook."""

    def __call__(
        self,
        frame: ExtractedFrame,
        sample: FrameSample,
        cancellation: CancellationToken,
    ) -> None: ...

    def flush(self, cancellation: CancellationToken) -> None: ...


@dataclass
class _MutableStatistics:
    chunks_processed: int = 0
    temporal_samples: int = 0
    scene_samples: int = 0
    samples_considered: int = 0
    black_frames_removed: int = 0
    duplicates_removed: int = 0
    static_frames_suppressed: int = 0
    representative_frames: int = 0


class MoviePreprocessingService:
    """Sequential orchestration for prompt-independent visual preprocessing."""

    def __init__(
        self,
        *,
        ffmpeg_service: FFmpegService | None = None,
        media_probe_service: MediaProbeService | None = None,
        frame_extractor: FFmpegHybridFrameExtractor | None = None,
        instrumentation: PreprocessingInstrumentation | None = None,
    ) -> None:
        self.instrumentation = instrumentation
        self.media_probe_service = media_probe_service or MediaProbeService(
            ffmpeg_service=ffmpeg_service
        )
        self.frame_extractor = frame_extractor or FFmpegHybridFrameExtractor(
            ffmpeg_service=ffmpeg_service,
            instrumentation=instrumentation,
        )

    def preprocess(
        self,
        video_path: str | Path,
        *,
        config: PreprocessingConfig | None = None,
        cancellation: CancellationToken | None = None,
        progress_callback: ChunkProgressCallback | None = None,
        representative_callback: RepresentativeFrameCallback | None = None,
    ) -> PreprocessingResult:
        resolved_config = config or PreprocessingConfig()
        cancellation_token = cancellation or CancellationToken()
        cancellation_token.raise_if_cancelled()
        started_at = time.perf_counter()

        probe_started_at = (
            time.perf_counter() if self.instrumentation is not None else 0.0
        )
        try:
            media_info = self.media_probe_service.probe(video_path)
        finally:
            if self.instrumentation is not None:
                self.instrumentation.add_duration(
                    "media_probe_seconds",
                    time.perf_counter() - probe_started_at,
                )
        cancellation_token.raise_if_cancelled()
        _require_selected_video_stream(media_info, resolved_config.selected_video_stream_index)
        movie_duration_us = round(media_info.duration_seconds * MICROSECONDS_PER_SECOND)
        chunks = plan_processing_chunks(movie_duration_us, resolved_config)

        reducer = SequentialFrameFilter(
            resolved_config,
            instrumentation=self.instrumentation,
        )
        counters = _MutableStatistics()
        representatives: list[FrameSample] = []

        for chunk in chunks:
            cancellation_token.raise_if_cancelled()
            for frame in self.frame_extractor.extract(
                video_path,
                chunk,
                resolved_config,
                cancellation_token,
            ):
                cancellation_token.raise_if_cancelled()
                merge_started_at = (
                    time.perf_counter() if self.instrumentation is not None else 0.0
                )
                owner = owning_chunk_index(chunks, frame.timestamp_us)
                if owner != chunk.index:
                    # Decode overlap provides context to FFmpeg but never competes
                    # with the core owner for final emission.
                    if self.instrumentation is not None:
                        self.instrumentation.increment(
                            "overlap_samples_discarded_by_ownership"
                        )
                        self.instrumentation.add_duration(
                            "chunk_merge_finalization_seconds",
                            time.perf_counter() - merge_started_at,
                        )
                    continue
                counters.samples_considered += 1
                if SampleReason.TEMPORAL_SAFETY in frame.sample_reasons:
                    counters.temporal_samples += 1
                if SampleReason.SCENE_TRANSITION in frame.sample_reasons:
                    counters.scene_samples += 1
                if self.instrumentation is not None:
                    self.instrumentation.add_duration(
                        "chunk_merge_finalization_seconds",
                        time.perf_counter() - merge_started_at,
                    )

                sample = reducer.process(frame, owning_chunk_index=owner)
                merge_started_at = (
                    time.perf_counter() if self.instrumentation is not None else 0.0
                )
                if sample.disposition is FrameDisposition.BLACK:
                    counters.black_frames_removed += 1
                elif sample.disposition is FrameDisposition.NEAR_DUPLICATE:
                    counters.duplicates_removed += 1
                elif sample.disposition is FrameDisposition.STATIC_SUPPRESSED:
                    counters.static_frames_suppressed += 1
                else:
                    representatives.append(sample)
                    counters.representative_frames += 1
                    if representative_callback is not None:
                        representative_callback(frame, sample, cancellation_token)
                if self.instrumentation is not None:
                    self.instrumentation.record_sample(
                        SampleObservation(
                            timestamp_us=sample.timestamp_us,
                            owning_chunk_index=sample.owning_chunk_index,
                            sample_reasons=sample.sample_reasons,
                            disposition=sample.disposition,
                            duplicate_of_timestamp_us=sample.duplicate_of_timestamp_us,
                        )
                    )
                    self.instrumentation.add_duration(
                        "chunk_merge_finalization_seconds",
                        time.perf_counter() - merge_started_at,
                    )

            merge_started_at = (
                time.perf_counter() if self.instrumentation is not None else 0.0
            )
            flushed = reducer.finish()
            representatives.extend(flushed)
            counters.representative_frames += len(flushed)
            counters.chunks_processed += 1
            if progress_callback is not None:
                progress_callback(counters.chunks_processed, len(chunks))
            if self.instrumentation is not None:
                self.instrumentation.add_duration(
                    "chunk_merge_finalization_seconds",
                    time.perf_counter() - merge_started_at,
                )

        if isinstance(representative_callback, FinalizableRepresentativeFrameCallback):
            cancellation_token.raise_if_cancelled()
            representative_callback.flush(cancellation_token)
            cancellation_token.raise_if_cancelled()

        elapsed_seconds = time.perf_counter() - started_at
        duration_seconds = movie_duration_us / MICROSECONDS_PER_SECOND
        throughput = duration_seconds / elapsed_seconds if elapsed_seconds > 0.0 else 0.0
        if self.instrumentation is not None:
            self.instrumentation.add_duration(
                "total_preprocessing_wall_seconds",
                elapsed_seconds,
            )
        statistics = PreprocessingStatistics(
            movie_duration_us=movie_duration_us,
            preprocessing_wall_seconds=elapsed_seconds,
            chunks_processed=counters.chunks_processed,
            temporal_samples=counters.temporal_samples,
            scene_samples=counters.scene_samples,
            samples_considered=counters.samples_considered,
            black_frames_removed=counters.black_frames_removed,
            duplicates_removed=counters.duplicates_removed,
            static_frames_suppressed=counters.static_frames_suppressed,
            representative_frames=counters.representative_frames,
            media_throughput=throughput,
        )
        return PreprocessingResult(
            config=resolved_config,
            chunks=chunks,
            representative_frames=tuple(representatives),
            statistics=statistics,
        )


def _require_selected_video_stream(media_info, selected_stream_index: int) -> None:
    if not any(stream.index == selected_stream_index for stream in media_info.video_streams):
        available = ", ".join(str(stream.index) for stream in media_info.video_streams) or "none"
        raise ValueError(
            f"Video stream {selected_stream_index} is unavailable; available indexes: {available}"
        )
