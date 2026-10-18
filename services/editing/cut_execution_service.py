import logging
import uuid
from pathlib import Path

from core.paths import get_cuts_cache_dir
from core.time_intervals import intervals_duration, invert_removed_intervals, normalize_intervals
from core.time_utils import duration_seconds, seconds_to_ffmpeg_time
from schemas.video_cut_schema import (
    CutExportMode,
    CutSegmentResult,
    VideoCutRequest,
    VideoCutResult,
)
from services.export.video_packet_index import (
    VideoPacket,
    VideoPacketIndexError,
    copyable_range,
    frame_signature,
    hashes,
    is_clean_cut_point,
    nearest_keyframes,
    packets_in_range,
)
from services.infrastructure.ffmpeg.cutting import FFmpegCuttingService


logger = logging.getLogger(__name__)


class CutExecutionService:
    def __init__(
        self,
        ffmpeg_service=None,
        command_runner=None,
        probe_runner=None,
        metadata_probe=None,
        cache_dir=None,
        cutting_service: FFmpegCuttingService | None = None,
        packet_probe=None,
    ):
        self.cutting_service = cutting_service or FFmpegCuttingService(
            ffmpeg_service=ffmpeg_service,
            command_runner=command_runner,
            probe_runner=probe_runner,
        )
        self.metadata_probe = metadata_probe or self.cutting_service.probe_media
        self.packet_probe = packet_probe or self.cutting_service.probe_video_packets
        self.cache_dir = Path(cache_dir) if cache_dir else get_cuts_cache_dir()

    def export_segments(self, request: VideoCutRequest, progress_callback=None) -> VideoCutResult:
        request = VideoCutRequest.model_validate(request)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        self.cutting_service.reset_diagnostics()

        input_metadata = self.metadata_probe(request.input_path)
        input_duration = _required_duration(input_metadata, request.input_path)
        logger.info("Video export input file: %s", request.input_path)
        logger.info("Video export mode: %s cut mode: %s", request.export_mode, request.cut_mode)
        logger.info("Video export input duration: %.3f", input_duration)
        logger.info("Video export selected intervals: %s", _segment_intervals(request))

        if _mode_value(request.export_mode) == CutExportMode.REMOVE_INTERVALS.value:
            result = self.remove_selected_intervals(
                request,
                input_duration,
                progress_callback=progress_callback,
            )
        elif _mode_value(request.export_mode) == CutExportMode.EXPORT_CLIPS_MERGED.value:
            result = self.export_selected_clips_merged(
                request,
                input_duration,
                progress_callback=progress_callback,
            )
        else:
            result = self.export_selected_clips(
                request,
                input_duration,
                progress_callback=progress_callback,
            )

        logger.info("Video export output files: %s", result.output_paths)
        logger.info(
            "Video export expected duration: %s actual duration: %s difference: %s",
            result.expected_output_duration_seconds,
            result.actual_output_duration_seconds,
            result.duration_difference_seconds,
        )
        if result.duration_warning:
            logger.warning("Video export duration warning: %s", result.duration_warning)
        return result

    def export_selected_clips(
        self,
        request: VideoCutRequest,
        input_duration: float,
        progress_callback=None,
    ) -> VideoCutResult:
        segment_results = []
        output_paths = []

        for offset, segment in enumerate(request.segments, start=1):
            output_path = make_unique_path(
                request.output_dir
                / _clip_output_name(request.input_path, segment.index, segment.start_seconds, segment.end_seconds)
            )
            self.cutting_service.export_interval(
                request.input_path,
                output_path,
                segment.start_seconds,
                segment.end_seconds,
            )
            output_paths.append(output_path)
            segment_results.append(_segment_result(segment, output_path))
            _emit_progress(
                progress_callback,
                int(offset / len(request.segments) * 100),
                f"Exported selected clip {offset}",
            )

        expected_duration = sum(segment.duration_seconds for segment in segment_results)
        return self._result_with_duration_validation(
            request,
            output_paths,
            segment_results,
            input_duration,
            expected_duration,
            normalized_intervals=_segment_intervals(request),
        )

    def export_selected_clips_merged(
        self,
        request: VideoCutRequest,
        input_duration: float,
        progress_callback=None,
    ) -> VideoCutResult:
        selected_intervals = _segment_intervals(request)
        merged_name = request.merged_output_name or f"{request.input_path.stem}_selected_clips_merged{request.input_path.suffix}"
        merged_path = make_unique_path(request.output_dir / Path(merged_name).name)

        temporary_segments = self._export_temporary_ranges(
            request.input_path,
            selected_intervals,
            cache_prefix="selected_clips",
            progress_callback=progress_callback,
        )
        self.cutting_service.concat_stream_copy_segments(temporary_segments, merged_path)

        _emit_progress(progress_callback, 100, "Merged selected clips")
        return self._result_with_duration_validation(
            request,
            [merged_path],
            [_segment_result(segment, merged_path) for segment in request.segments],
            input_duration,
            intervals_duration(selected_intervals),
            merged_output_path=merged_path,
            normalized_intervals=selected_intervals,
        )

    def remove_selected_intervals(
        self,
        request: VideoCutRequest,
        input_duration: float,
        progress_callback=None,
    ) -> VideoCutResult:
        selected_intervals = _segment_intervals(request)
        normalized_removed = normalize_intervals(selected_intervals, input_duration)
        kept_intervals = invert_removed_intervals(normalized_removed, input_duration)
        if not kept_intervals:
            raise ValueError("Removed intervals cover the full video.")

        logger.info("Video export normalized removed intervals: %s", normalized_removed)
        logger.info("Video export computed kept intervals: %s", kept_intervals)

        source_packets = self.packet_probe(request.input_path)
        require_keyframe_aligned_removals(normalized_removed, source_packets)
        copy_ranges = []
        for start_seconds, end_seconds in kept_intervals:
            if not packets_in_range(source_packets, start_seconds, end_seconds):
                continue
            packets = copyable_range(source_packets, start_seconds, end_seconds)
            if packets is None:
                raise FastCuttingPrecisionError(
                    f"Fast Cutting cannot stream-copy {seconds_to_ffmpeg_time(start_seconds)}-"
                    f"{seconds_to_ffmpeg_time(end_seconds)} exactly. {FAST_CUTTING_NOTHING_EXPORTED}"
                )
            copy_ranges.append((start_seconds, end_seconds, packets))

        output_name = request.merged_output_name or f"{request.input_path.stem}_removed_intervals{request.input_path.suffix}"
        output_path = make_unique_path(request.output_dir / Path(output_name).name)
        temporary_segments = self._export_temporary_ranges(
            request.input_path,
            [(start_seconds, end_seconds) for start_seconds, end_seconds, _ in copy_ranges],
            cache_prefix="kept_ranges",
            progress_callback=progress_callback,
            video_frame_counts=[len(packets) for _, _, packets in copy_ranges],
        )
        for segment_path, (start_seconds, end_seconds, packets) in zip(temporary_segments, copy_ranges):
            if hashes(self.packet_probe(segment_path)) != hashes(packets):
                raise FastCuttingVerificationError(
                    "Fast Cutting could not verify that the stream copy of "
                    f"{seconds_to_ffmpeg_time(start_seconds)}-{seconds_to_ffmpeg_time(end_seconds)} contains exactly "
                    f"the kept frames (FFmpeg started or stopped on another frame). {FAST_CUTTING_NOTHING_EXPORTED}"
                )
        self.cutting_service.concat_stream_copy_segments(temporary_segments, output_path)
        expected_signature = frame_signature([packet for _, _, packets in copy_ranges for packet in packets])
        try:
            verified = frame_signature(self.packet_probe(output_path)) == expected_signature
        except (VideoPacketIndexError, OSError):
            verified = False
        if not verified:
            output_path.unlink(missing_ok=True)
            raise FastCuttingVerificationError(
                "Fast Cutting could not verify the joined video against the kept frames. The output was deleted. "
                "Use Smart Cutting for frame-exact removal."
            )

        _emit_progress(progress_callback, 100, "Removed selected intervals")
        return self._result_with_duration_validation(
            request,
            [output_path],
            [_segment_result(segment, output_path) for segment in request.segments],
            input_duration,
            intervals_duration(kept_intervals),
            merged_output_path=output_path,
            normalized_intervals=normalized_removed,
            kept_intervals=kept_intervals,
        )

    def _export_temporary_ranges(
        self,
        input_path: Path,
        intervals: list[tuple[float, float]],
        cache_prefix: str,
        progress_callback=None,
        video_frame_counts: list[int] | None = None,
    ) -> list[Path]:
        job_cache_dir = self.cache_dir / f"{cache_prefix}_{uuid.uuid4().hex}"
        job_cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_segments = []

        for offset, (start_seconds, end_seconds) in enumerate(intervals, start=1):
            temp_output_path = job_cache_dir / f"{input_path.stem}_{cache_prefix}_{offset:03d}{input_path.suffix}"
            self.cutting_service.export_interval(
                input_path,
                temp_output_path,
                start_seconds,
                end_seconds,
                video_frame_count=video_frame_counts[offset - 1] if video_frame_counts else None,
            )
            temporary_segments.append(temp_output_path)
            _emit_progress(
                progress_callback,
                int(offset / (len(intervals) + 1) * 100),
                f"Prepared stream-copy segment {offset}",
            )

        return temporary_segments

    def _result_with_duration_validation(
        self,
        request: VideoCutRequest,
        output_paths: list[Path],
        segment_results: list[CutSegmentResult],
        input_duration: float,
        expected_duration: float,
        merged_output_path: Path | None = None,
        normalized_intervals: list[tuple[float, float]] | None = None,
        kept_intervals: list[tuple[float, float]] | None = None,
    ) -> VideoCutResult:
        actual_duration = sum(_required_duration(self.metadata_probe(path), path) for path in output_paths)
        duration_difference = abs(expected_duration - actual_duration)
        warning = _duration_warning(expected_duration, actual_duration, duration_difference)

        return VideoCutResult(
            input_path=request.input_path,
            output_paths=output_paths,
            merged_output_path=merged_output_path,
            segments=segment_results,
            export_mode=request.export_mode,
            cut_mode=request.cut_mode,
            input_duration_seconds=input_duration,
            expected_output_duration_seconds=round(expected_duration, 3),
            actual_output_duration_seconds=round(actual_duration, 3),
            duration_difference_seconds=round(duration_difference, 3),
            duration_warning=warning,
            normalized_intervals=normalized_intervals or [],
            kept_intervals=kept_intervals or [],
            ffmpeg_commands=list(self.cutting_service.commands),
            ffmpeg_stderr=list(self.cutting_service.stderr),
        )


FAST_CUTTING_NOTHING_EXPORTED = (
    "Nothing was exported and the cuts were not changed. Use Smart Cutting for frame-exact removal."
)


class FastCuttingPrecisionError(ValueError):
    pass


class FastCuttingVerificationError(ValueError):
    pass


def require_keyframe_aligned_removals(
    removed_intervals: list[tuple[float, float]],
    source_packets: list[VideoPacket],
) -> None:
    """Refuse a Fast Cutting removal unless stream copy can honour every boundary exactly.

    Stream copy can only start or stop where a keyframe opens a group of frames that does not depend
    on earlier frames. Any other boundary would keep frames of the removed interval (or drop kept
    ones); the intervals are never widened silently.
    """
    boundaries = sorted({value for interval in removed_intervals for value in interval})
    unaligned = [value for value in boundaries if not is_clean_cut_point(source_packets, value)]
    if not unaligned:
        return
    details = "; ".join(_boundary_detail(source_packets, value) for value in unaligned)
    raise FastCuttingPrecisionError(
        "Fast Cutting cannot remove the selected intervals exactly: stream copy can only cut on a keyframe "
        f"that starts an independent group of frames, and these cut boundaries are not on one: {details}. "
        "Nothing was exported and the cuts were not changed. Use Smart Cutting for frame-exact removal, "
        "or move these boundaries onto the listed keyframes."
    )


def _boundary_detail(source_packets: list[VideoPacket], seconds: float) -> str:
    previous_keyframe, next_keyframe = nearest_keyframes(source_packets, seconds)
    if previous_keyframe is not None and previous_keyframe == next_keyframe:
        return f"{seconds_to_ffmpeg_time(seconds)} (keyframe of an open GOP: earlier frames depend on it)"
    keyframes = [seconds_to_ffmpeg_time(value) for value in (previous_keyframe, next_keyframe) if value is not None]
    return f"{seconds_to_ffmpeg_time(seconds)} (nearest keyframes {' and '.join(keyframes)})"


def make_unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    suffix = path.suffix
    stem = path.stem
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _clip_output_name(input_path: Path, index: int, start_seconds: float, end_seconds: float) -> str:
    start = _filename_timestamp(start_seconds)
    end = _filename_timestamp(end_seconds)
    return f"{input_path.stem}_clip_{index:03d}_{start}_to_{end}{input_path.suffix}"


def _filename_timestamp(seconds: float) -> str:
    return seconds_to_ffmpeg_time(seconds).split(".", 1)[0].replace(":", "-")


def _duration_warning(expected: float, actual: float, difference: float) -> str | None:
    if difference <= 2.0:
        return None

    return (
        f"Expected output duration: {expected:.1f}s. Actual output duration: {actual:.1f}s. "
        f"Difference: {difference:.1f}s. Stream-copy cuts may align to nearby keyframes."
    )


def _mode_value(mode) -> str:
    return getattr(mode, "value", str(mode))


def _required_duration(metadata: dict, path: Path) -> float:
    duration = metadata.get("duration_seconds")
    if duration is None or float(duration) <= 0:
        raise ValueError(f"Unable to read a positive duration for {path}.")
    return float(duration)


def _segment_intervals(request: VideoCutRequest) -> list[tuple[float, float]]:
    return [(segment.start_seconds, segment.end_seconds) for segment in request.segments]


def _segment_result(segment, output_path: Path) -> CutSegmentResult:
    return CutSegmentResult(
        segment_index=segment.index,
        output_path=output_path,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        requested_start_seconds=segment.requested_start_seconds,
        requested_end_seconds=segment.requested_end_seconds,
        previous_keyframe_start=segment.previous_keyframe_start,
        next_keyframe_start=segment.next_keyframe_start,
        previous_keyframe_end=segment.previous_keyframe_end,
        next_keyframe_end=segment.next_keyframe_end,
        duration_seconds=duration_seconds(segment.start_seconds, segment.end_seconds),
    )


def _emit_progress(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)
