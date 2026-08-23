from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image, ImageStat

from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    PreprocessingConfig,
    SampleReason,
)

if TYPE_CHECKING:
    from services.analysis.preprocessing_instrumentation import (
        PreprocessingInstrumentation,
    )


_COLOR_DISTANCE_THRESHOLD = 12.0
_OVERLAP_TIMESTAMP_TOLERANCE_US = 50_000


@dataclass(frozen=True)
class _RepresentativeFeatures:
    timestamp_us: int
    processing_chunk_index: int
    global_hash: int
    regional_hashes: tuple[int, ...]
    mean_rgb: tuple[float, float, float]
    regional_mean_rgb: tuple[tuple[float, float, float], ...]


class SequentialFrameFilter:
    """Conservative, stateful frame reduction for a globally ordered stream."""

    def __init__(
        self,
        config: PreprocessingConfig,
        instrumentation: PreprocessingInstrumentation | None = None,
    ) -> None:
        self.config = config
        self.instrumentation = instrumentation
        self._last_representative: _RepresentativeFeatures | None = None

    def process(self, frame: ExtractedFrame, owning_chunk_index: int) -> FrameSample:
        process_started_at = (
            time.perf_counter() if self.instrumentation is not None else 0.0
        )
        if self.instrumentation is not None:
            self.instrumentation.increment(
                "python_rgb_bytes_processed",
                len(frame.rgb_bytes),
            )

        stage_started_at = time.perf_counter() if self.instrumentation is not None else 0.0
        content = _content_image(frame)
        self._record_duration("frame_preparation_seconds", stage_started_at)

        stage_started_at = time.perf_counter() if self.instrumentation is not None else 0.0
        black_fraction, mean_luma = _black_features(
            content,
            self.config.black_pixel_luma_threshold,
        )
        mean_rgb = tuple(float(value) for value in ImageStat.Stat(content).mean[:3])
        is_black = (
            black_fraction >= self.config.black_frame_ratio_threshold
            and mean_luma <= self.config.black_mean_luma_threshold
        )
        self._record_duration("black_filter_seconds", stage_started_at)
        if is_black:
            # A black gap is a content boundary. Do not allow an earlier image to
            # suppress a visually identical image that reappears after the gap.
            self._last_representative = None
            stage_started_at = (
                time.perf_counter() if self.instrumentation is not None else 0.0
            )
            sample = _sample(
                frame,
                owning_chunk_index,
                disposition=FrameDisposition.BLACK,
                black_fraction=black_fraction,
                mean_luma=mean_luma,
                mean_rgb=mean_rgb,
            )
            self._record_duration("result_materialization_seconds", stage_started_at)
            self._record_duration("python_filter_total_seconds", process_started_at)
            return sample

        stage_started_at = time.perf_counter() if self.instrumentation is not None else 0.0
        global_hash = _dhash(content)
        regions = _spatial_regions(content)
        regional_hashes = tuple(_dhash(region) for region in regions)
        regional_mean_rgb = tuple(
            tuple(float(value) for value in ImageStat.Stat(region).mean[:3])
            for region in regions
        )
        self._record_duration("perceptual_hash_seconds", stage_started_at)

        stage_started_at = time.perf_counter() if self.instrumentation is not None else 0.0
        previous = self._last_representative
        scene_boundary = SampleReason.SCENE_TRANSITION in frame.sample_reasons
        disposition = FrameDisposition.REPRESENTATIVE
        duplicate_of_timestamp_us: int | None = None

        if previous is not None:
            same_visual = _features_match(
                global_hash,
                regional_hashes,
                mean_rgb,
                regional_mean_rgb,
                previous,
                self.config.duplicate_hamming_threshold,
            )
            if same_visual:
                timestamp_delta_us = frame.timestamp_us - previous.timestamp_us
                is_overlap_duplicate = (
                    frame.processing_chunk_index != previous.processing_chunk_index
                    and abs(timestamp_delta_us) <= _OVERLAP_TIMESTAMP_TOLERANCE_US
                )
                if is_overlap_duplicate:
                    disposition = FrameDisposition.NEAR_DUPLICATE
                    duplicate_of_timestamp_us = previous.timestamp_us
                elif (
                    not scene_boundary
                    and 0 <= timestamp_delta_us < self.config.static_suppression_limit_us
                ):
                    disposition = FrameDisposition.STATIC_SUPPRESSED
                    duplicate_of_timestamp_us = previous.timestamp_us

        if disposition is FrameDisposition.REPRESENTATIVE:
            self._last_representative = _RepresentativeFeatures(
                timestamp_us=frame.timestamp_us,
                processing_chunk_index=frame.processing_chunk_index,
                global_hash=global_hash,
                regional_hashes=regional_hashes,
                mean_rgb=mean_rgb,
                regional_mean_rgb=regional_mean_rgb,
            )
        self._record_duration(
            "duplicate_static_reduction_seconds",
            stage_started_at,
        )

        stage_started_at = time.perf_counter() if self.instrumentation is not None else 0.0
        sample = _sample(
            frame,
            owning_chunk_index,
            disposition=disposition,
            black_fraction=black_fraction,
            mean_luma=mean_luma,
            mean_rgb=mean_rgb,
            global_hash=global_hash,
            regional_hashes=regional_hashes,
            regional_mean_rgb=regional_mean_rgb,
            duplicate_of_timestamp_us=duplicate_of_timestamp_us,
        )
        self._record_duration("result_materialization_seconds", stage_started_at)
        self._record_duration("python_filter_total_seconds", process_started_at)
        return sample

    def finish(self) -> tuple[FrameSample, ...]:
        """Explicit EOF hook; representatives are retained eagerly, so none are pending."""
        return ()

    def _record_duration(self, name: str, started_at: float) -> None:
        if self.instrumentation is not None:
            self.instrumentation.add_duration(name, time.perf_counter() - started_at)


def _sample(
    frame: ExtractedFrame,
    owning_chunk_index: int,
    *,
    disposition: FrameDisposition,
    black_fraction: float,
    mean_luma: float,
    mean_rgb: tuple[float, float, float],
    global_hash: int | None = None,
    regional_hashes: tuple[int, ...] = (),
    regional_mean_rgb: tuple[tuple[float, float, float], ...] = (),
    duplicate_of_timestamp_us: int | None = None,
) -> FrameSample:
    return FrameSample(
        timestamp_us=frame.timestamp_us,
        source_pts=frame.source_pts,
        source_time_base=frame.source_time_base,
        owning_chunk_index=owning_chunk_index,
        sample_reasons=frame.sample_reasons,
        width=frame.width,
        height=frame.height,
        content_rect=frame.content_rect,
        scene_score=frame.scene_score,
        black_fraction=black_fraction,
        mean_luma=mean_luma,
        content_mean_rgb=mean_rgb,
        perceptual_hash=_hash_hex(global_hash) if global_hash is not None else None,
        regional_hashes=tuple(_hash_hex(value) for value in regional_hashes),
        regional_mean_rgb=regional_mean_rgb,
        disposition=disposition,
        duplicate_of_timestamp_us=duplicate_of_timestamp_us,
    )


def _content_image(frame: ExtractedFrame) -> Image.Image:
    expected_size = frame.width * frame.height * 3
    if len(frame.rgb_bytes) != expected_size:
        raise ValueError("RGB frame byte count does not match its dimensions")
    canvas = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb_bytes)
    left, top, width, height = frame.content_rect
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise ValueError("content rectangle is invalid")
    if left + width > frame.width or top + height > frame.height:
        raise ValueError("content rectangle exceeds the RGB frame")
    return canvas.crop((left, top, left + width, top + height))


def _black_features(image: Image.Image, pixel_threshold: int) -> tuple[float, float]:
    grayscale = image.convert("L")
    histogram = grayscale.histogram()
    pixel_count = max(1, image.width * image.height)
    black_pixels = sum(histogram[: pixel_threshold + 1])
    mean_luma = sum(index * count for index, count in enumerate(histogram)) / pixel_count
    return black_pixels / pixel_count, mean_luma


def _dhash(image: Image.Image) -> int:
    grayscale = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = grayscale.tobytes()
    result = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            result = (result << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return result


def _spatial_regions(image: Image.Image) -> tuple[Image.Image, ...]:
    width, height = image.size
    if width < 2 or height < 2:
        return (image, image, image, image, image)
    half_width = max(1, width // 2)
    half_height = max(1, height // 2)
    quarter_width = width // 4
    quarter_height = height // 4
    return (
        image.crop((0, 0, half_width, half_height)),
        image.crop((half_width, 0, width, half_height)),
        image.crop((0, half_height, half_width, height)),
        image.crop((half_width, half_height, width, height)),
        image.crop(
            (
                quarter_width,
                quarter_height,
                max(quarter_width + 1, width - quarter_width),
                max(quarter_height + 1, height - quarter_height),
            )
        ),
    )


def _features_match(
    global_hash: int,
    regional_hashes: tuple[int, ...],
    mean_rgb: tuple[float, float, float],
    regional_mean_rgb: tuple[tuple[float, float, float], ...],
    previous: _RepresentativeFeatures,
    threshold: int,
) -> bool:
    if _hamming_distance(global_hash, previous.global_hash) > threshold:
        return False
    if len(regional_hashes) != len(previous.regional_hashes):
        return False
    if any(
        _hamming_distance(current, prior) > threshold
        for current, prior in zip(regional_hashes, previous.regional_hashes, strict=True)
    ):
        return False
    if max(
        abs(current - prior) for current, prior in zip(mean_rgb, previous.mean_rgb, strict=True)
    ) > _COLOR_DISTANCE_THRESHOLD:
        return False
    if len(regional_mean_rgb) != len(previous.regional_mean_rgb):
        return False
    return all(
        max(
            abs(current - prior)
            for current, prior in zip(current_region, prior_region, strict=True)
        )
        <= _COLOR_DISTANCE_THRESHOLD
        for current_region, prior_region in zip(
            regional_mean_rgb,
            previous.regional_mean_rgb,
            strict=True,
        )
    )


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _hash_hex(value: int) -> str:
    return f"{value:016x}"
