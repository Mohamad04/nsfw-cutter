import json
import logging
import subprocess
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
from services.ffmpeg_service import FFmpegService


logger = logging.getLogger(__name__)


class VideoCutError(RuntimeError):
    def __init__(self, command: list[str], return_code: int, stderr: str):
        self.command = command
        self.return_code = return_code
        self.stderr = stderr
        super().__init__(
            "Video export failed. This workflow uses FFmpeg stream copy and the source streams must support it."
        )


class VideoCutService:
    def __init__(
        self,
        ffmpeg_service: FFmpegService | None = None,
        command_runner=None,
        probe_runner=None,
        metadata_probe=None,
        cache_dir=None,
    ):
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.command_runner = command_runner or subprocess.run
        self.probe_runner = probe_runner or subprocess.run
        self.metadata_probe = metadata_probe or self._probe_media
        self.cache_dir = Path(cache_dir) if cache_dir else get_cuts_cache_dir()
        self._ffmpeg_commands: list[list[str]] = []
        self._ffmpeg_stderr: list[str] = []

    def export_segments(self, request: VideoCutRequest, progress_callback=None) -> VideoCutResult:
        request = VideoCutRequest.model_validate(request)
        request.output_dir.mkdir(parents=True, exist_ok=True)
        self._ffmpeg_commands = []
        self._ffmpeg_stderr = []

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
            self.export_interval(
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
        self._concat_stream_copy_segments(temporary_segments, merged_path)

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

        output_name = request.merged_output_name or f"{request.input_path.stem}_removed_intervals{request.input_path.suffix}"
        output_path = make_unique_path(request.output_dir / Path(output_name).name)
        temporary_segments = self._export_temporary_ranges(
            request.input_path,
            kept_intervals,
            cache_prefix="kept_ranges",
            progress_callback=progress_callback,
        )
        self._concat_stream_copy_segments(temporary_segments, output_path)

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

    def export_interval(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_command(self.build_cut_command(input_path, output_path, start_seconds, end_seconds))
        return output_path

    def _export_temporary_ranges(
        self,
        input_path: Path,
        intervals: list[tuple[float, float]],
        cache_prefix: str,
        progress_callback=None,
    ) -> list[Path]:
        job_cache_dir = self.cache_dir / f"{cache_prefix}_{uuid.uuid4().hex}"
        job_cache_dir.mkdir(parents=True, exist_ok=True)
        temporary_segments = []

        for offset, (start_seconds, end_seconds) in enumerate(intervals, start=1):
            temp_output_path = job_cache_dir / f"{input_path.stem}_{cache_prefix}_{offset:03d}{input_path.suffix}"
            self._run_command(self.build_cut_command(input_path, temp_output_path, start_seconds, end_seconds))
            temporary_segments.append(temp_output_path)
            _emit_progress(
                progress_callback,
                int(offset / (len(intervals) + 1) * 100),
                f"Prepared stream-copy segment {offset}",
            )

        return temporary_segments

    def _concat_stream_copy_segments(self, temporary_segments: list[Path], output_path: Path) -> None:
        concat_list_path = temporary_segments[0].parent / "concat_list.txt"
        concat_list_path.write_text(
            "\n".join(_concat_line(path) for path in temporary_segments),
            encoding="utf-8",
        )
        self._run_command(self.build_concat_command(concat_list_path, output_path))

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
            ffmpeg_commands=list(self._ffmpeg_commands),
            ffmpeg_stderr=list(self._ffmpeg_stderr),
        )

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

    def _probe_media(self, media_path: str | Path) -> dict:
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
            "has_audio": any(stream.get("codec_type") == "audio" for stream in raw.get("streams", [])),
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
        self._ffmpeg_commands.append(list(command))
        self._ffmpeg_stderr.append(completed.stderr or "")
        logger.info("FFmpeg return code: %s", completed.returncode)
        if completed.stderr:
            logger.info("FFmpeg stderr: %s", completed.stderr)
        if completed.returncode != 0:
            logger.error("FFmpeg export failed: %s", completed.stderr)
            raise VideoCutError(command, completed.returncode, completed.stderr)


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


def _concat_line(path: Path) -> str:
    escaped_path = path.as_posix().replace("'", "'\\''")
    return f"file '{escaped_path}'"


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
