import shutil
import uuid
from functools import partial
from pathlib import Path

from core.paths import get_cuts_cache_dir
from core.time_intervals import invert_removed_intervals
from services.editing.cut_execution_service import make_unique_path
from services.export.audio_rebuild_service import AudioRebuildService
from services.export.export_validation_service import (
    expected_edited_duration,
    requested_delete_intervals,
    validate_final_output,
    validate_keyframes,
    validate_smart_cutting_input,
    validate_smart_export_mode,
    validate_video_only_output,
)
from services.export.keyframe_service import ExportKeyframeService
from services.export.media_probe_service import MediaProbeService
from services.export.mux_service import MuxService, SubtitleMuxInput
from services.export.smart_cut_planner import COPY_SEGMENT, SmartCutPlanner
from services.export.source_normalization_service import MkvNormalizationService, needs_normalization
from services.export.subtitle_rebuild_service import (
    EmbeddedSubtitleExtractError,
    EmbeddedSubtitleExtractService,
    SubtitleRebuildError,
    SubtitleRebuildService,
)
from services.export.video_concat_service import VideoConcatService
from services.export.video_packet_index import (
    VideoPacket,
    VideoPacketIndexService,
    first_frame_at_or_after,
    frame_signature,
    kept_frame_durations,
    packets_in_range,
    timeline_mismatch,
)
from services.export.video_segment_renderer import (
    VideoSegmentRenderer,
    VideoSegmentVerificationError,
)
from services.infrastructure.ffmpeg.bounded_runner import ExportCancelledError, FFmpegTimeoutError
from services.infrastructure.ffmpeg.subtitles import probe_subtitle_streams
from services.subtitles.inspection_service import get_embedded_subtitle_streams
from services.subtitles.processing_service import SubtitleService


SMART_CUTTING_MODE = "smart_cutting"
SMART_CUTTING_SUBTITLE_SUCCESS = "External text subtitles rebuilt."
SMART_CUTTING_EMBEDDED_UNSUPPORTED = "Embedded image or unsupported subtitles are not rebuilt in Smart Cutting yet."
SMART_CUTTING_SUBTITLE_REBUILD_FAILED = "Subtitle rebuild failed. External subtitles were skipped."
# Matroska stores millisecond timestamps, so frame spacing may be rounded by up to 1 ms on each side.
TIMELINE_TOLERANCE_SECONDS = 0.0021


class SmartCuttingExportService:
    def __init__(
        self,
        *,
        media_probe_service: MediaProbeService | None = None,
        keyframe_service: ExportKeyframeService | None = None,
        planner: SmartCutPlanner | None = None,
        video_renderer: VideoSegmentRenderer | None = None,
        video_concat_service: VideoConcatService | None = None,
        audio_rebuild_service: AudioRebuildService | None = None,
        subtitle_service: SubtitleService | None = None,
        subtitle_rebuild_service: SubtitleRebuildService | None = None,
        embedded_subtitle_extract_service: EmbeddedSubtitleExtractService | None = None,
        mux_service: MuxService | None = None,
        packet_index_service: VideoPacketIndexService | None = None,
        source_normalization_service: MkvNormalizationService | None = None,
        cache_dir: str | Path | None = None,
        debug_keep_temp: bool = False,
        process_runner=None,
    ):
        # process_runner (e.g. BoundedProcessRunner) runs every FFmpeg/ffprobe call of the default services.
        runner = process_runner
        self.media_probe_service = media_probe_service or MediaProbeService(probe_runner=runner)
        self.keyframe_service = keyframe_service or ExportKeyframeService(probe_runner=runner)
        self.planner = planner or SmartCutPlanner()
        self.packet_index_service = packet_index_service or VideoPacketIndexService(probe_runner=runner)
        self.video_renderer = video_renderer or VideoSegmentRenderer(
            command_runner=runner,
            packet_index_service=VideoPacketIndexService(probe_runner=runner),
        )
        self.video_concat_service = video_concat_service or VideoConcatService(command_runner=runner)
        self.audio_rebuild_service = audio_rebuild_service or AudioRebuildService(command_runner=runner)
        self.subtitle_service = subtitle_service or SubtitleService(
            embedded_inspection=partial(
                get_embedded_subtitle_streams,
                subtitle_probe=partial(probe_subtitle_streams, probe_runner=runner),
            )
        )
        self.subtitle_rebuild_service = subtitle_rebuild_service or SubtitleRebuildService()
        self.embedded_subtitle_extract_service = embedded_subtitle_extract_service or EmbeddedSubtitleExtractService(
            command_runner=runner
        )
        self.mux_service = mux_service or MuxService(command_runner=runner)
        self.source_normalization_service = source_normalization_service or MkvNormalizationService(
            command_runner=runner,
            packet_index_service=VideoPacketIndexService(probe_runner=runner),
        )
        self.cache_dir = Path(cache_dir) if cache_dir else get_cuts_cache_dir()
        self.debug_keep_temp = debug_keep_temp

    def export(self, request_data: dict, progress_callback=None) -> dict:
        input_path = Path(request_data.get("input_path") or "")
        output_dir = Path(request_data.get("output_dir") or "")
        export_mode = str(request_data.get("export_mode") or "remove_intervals")
        segments = list(request_data.get("segments") or [])
        if not input_path.is_file():
            raise ValueError(f"Input video does not exist: {input_path}")
        if not segments:
            raise ValueError("At least one cut segment is required.")
        validate_smart_export_mode(export_mode)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._reset_diagnostics()
        temp_dir = self.cache_dir / f"smart_cut_{uuid.uuid4().hex}"
        chunks_dir = temp_dir / "video_chunks"
        subtitle_dir = temp_dir / "subtitles"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            _emit(progress_callback, 2, "Probing media")
            media_info = self.media_probe_service.probe(input_path)
            validate_smart_cutting_input(media_info)

            # Video and audio are cut from cut_source; subtitles are rebuilt from the original file.
            cut_source = input_path
            normalization = None
            if needs_normalization(media_info):
                _emit(progress_callback, 5, "Preparing MKV for exact cutting")
                normalization = self.source_normalization_service.normalize(
                    input_path,
                    temp_dir / "normalized_source.mp4",
                    media_info,
                )
                cut_source = normalization.path
                media_info = self.media_probe_service.probe(cut_source)

            _emit(progress_callback, 10, "Loading keyframes")
            keyframes = validate_keyframes(
                self.keyframe_service.extract_keyframes(cut_source),
                media_info.duration_seconds,
            )

            _emit(progress_callback, 15, "Planning smart cut")
            delete_intervals = requested_delete_intervals(segments, media_info.duration_seconds)
            kept_intervals = invert_removed_intervals(delete_intervals, media_info.duration_seconds)
            expected_duration = expected_edited_duration(media_info.duration_seconds, delete_intervals)
            plan = self.planner.build_plan(delete_intervals, keyframes, media_info.duration_seconds)
            source_packets = self.packet_index_service.probe(cut_source)
            expected_frames = sum(len(packets_in_range(source_packets, start, end)) for start, end in kept_intervals)
            expected_durations = kept_frame_durations(source_packets, kept_intervals)

            _emit(progress_callback, 22, "Exporting video chunks")
            chunks = self.video_renderer.render_plan(
                cut_source,
                plan,
                chunks_dir,
                progress_callback=_scaled_progress(progress_callback, 22, 55),
                source_packets=source_packets,
                track_timescale=_track_timescale(media_info),
                reorder_delay=_reorder_delay(media_info),
            )
            chunk_signature = [item for chunk in chunks for item in chunk.frame_signature]
            if len(chunk_signature) != expected_frames:
                raise VideoSegmentVerificationError(
                    f"Smart Cutting stopped: rendered chunks hold {len(chunk_signature)} frames, "
                    f"expected {expected_frames} kept frames. Nothing was exported."
                )

            _emit(progress_callback, 58, "Concatenating video")
            video_only_path = self.video_concat_service.concat_chunks(
                chunks,
                temp_dir / "video_concat_list.txt",
                temp_dir / "smart_video_only.mkv",
                progress_callback=_scaled_progress(progress_callback, 58, 65),
            )
            video_only_info = self.media_probe_service.probe(video_only_path)
            validate_video_only_output(video_only_info, expected_duration)
            video_only_packets = self.packet_index_service.probe(video_only_path)
            if frame_signature(video_only_packets) != chunk_signature:
                raise VideoSegmentVerificationError(
                    "Smart Cutting stopped: the concatenated video does not match the verified chunks. "
                    "Nothing was exported."
                )
            _verify_timeline(video_only_packets, expected_durations, "the concatenated video")

            audio_path = None
            if media_info.has_audio:
                _emit(progress_callback, 68, "Rebuilding audio")
                audio_ranges, audio_durations = _frame_aligned_audio_ranges(kept_intervals, source_packets)
                audio_path = self.audio_rebuild_service.rebuild_audio(
                    cut_source,
                    audio_ranges,
                    temp_dir / "smart_audio.m4a",
                    progress_callback=_scaled_progress(progress_callback, 68, 78),
                    pad_durations=audio_durations,
                )

            _emit(progress_callback, 80, "Rebuilding subtitles")
            subtitle_inputs, subtitle_status = self._rebuild_subtitles(
                input_path,
                delete_intervals,
                subtitle_dir,
            )

            output_path = make_unique_path(output_dir / f"{input_path.stem}_smart_cut{input_path.suffix}")
            final_output_verified = False
            try:
                # output_path did not exist before this export, so a partial file is ours to delete.
                _emit(progress_callback, 88, "Muxing final output")
                mux_result = self.mux_service.mux(
                    video_only_path,
                    audio_path,
                    subtitle_inputs,
                    output_path,
                    progress_callback=_scaled_progress(progress_callback, 88, 96),
                )

                _emit(progress_callback, 98, "Validating output")
                final_info = self.media_probe_service.probe(mux_result.output_path)
                validate_final_output(
                    final_info,
                    expected_duration,
                    input_had_audio=media_info.has_audio,
                    expected_subtitle_stream=bool(subtitle_inputs),
                )
                final_packets = self.packet_index_service.probe(mux_result.output_path)
                if frame_signature(final_packets) != chunk_signature:
                    raise VideoSegmentVerificationError(
                        "Smart Cutting stopped: the final file's video does not match the verified chunks. "
                        "The output was deleted."
                    )
                _verify_timeline(final_packets, expected_durations, "the final file")
                final_output_verified = True
            finally:
                if not final_output_verified:
                    output_path.unlink(missing_ok=True)

            result = {
                "input_path": str(input_path),
                "output_paths": [str(mux_result.output_path)],
                "merged_output_path": str(mux_result.output_path),
                "segments": segments,
                "export_mode": export_mode,
                "cut_mode": SMART_CUTTING_MODE,
                "input_duration_seconds": round(media_info.duration_seconds, 3),
                "expected_output_duration_seconds": expected_duration,
                "actual_output_duration_seconds": round(final_info.duration_seconds, 3),
                "duration_difference_seconds": round(abs(final_info.duration_seconds - expected_duration), 3),
                "duration_warning": "",
                "normalized_intervals": delete_intervals,
                "kept_intervals": kept_intervals,
                "plan": plan.to_dict(),
                "source_normalization": normalization.to_dict() if normalization else None,
                "video_fallbacks": [
                    {
                        "start_seconds": chunk.start_seconds,
                        "end_seconds": chunk.end_seconds,
                        "reason": chunk.fallback_reason,
                    }
                    for chunk in chunks
                    if chunk.fallback_reason
                ],
                "verification": {
                    "expected_video_frames": expected_frames,
                    "final_video_packets": len(chunk_signature),
                    "copy_chunks_hash_verified": sum(
                        1 for chunk in chunks if chunk.segment_type == COPY_SEGMENT and not chunk.fallback_reason
                    ),
                    "reencoded_chunks_frame_count_verified": sum(
                        1 for chunk in chunks if chunk.segment_type != COPY_SEGMENT or chunk.fallback_reason
                    ),
                },
                "subtitles": subtitle_status,
                "ffmpeg_commands": self._commands(),
                "ffmpeg_stderr": self._stderr(),
                "status": "completed",
            }
            if self.debug_keep_temp:
                result["temporary_directory"] = str(temp_dir)
            _emit(progress_callback, 100, "Smart Cutting export completed")
            return {"job_id": None, "result": result}
        finally:
            if not self.debug_keep_temp:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _rebuild_subtitles(
        self,
        input_path: Path,
        delete_intervals: list[tuple[float, float]],
        subtitle_dir: Path,
    ) -> tuple[list[SubtitleMuxInput], list[dict]]:
        subtitle_inputs: list[SubtitleMuxInput] = []
        subtitle_status: list[dict] = []
        try:
            candidates = self.subtitle_service.discover_subtitles(input_path)
        except (ExportCancelledError, FFmpegTimeoutError):
            raise
        except Exception as exc:
            return [], [{"status": "warning", "message": f"Subtitle discovery failed: {exc}"}]

        for index, candidate in enumerate(candidates, start=1):
            if candidate.get("source") == "embedded":
                self._rebuild_embedded_subtitle(
                    input_path,
                    candidate,
                    index,
                    delete_intervals,
                    subtitle_dir,
                    subtitle_inputs,
                    subtitle_status,
                )
                continue
            if not candidate.get("is_text_readable") or not candidate.get("file_path"):
                subtitle_status.append(
                    {
                        "source": candidate.get("source"),
                        "status": "skipped",
                        "message": candidate.get("note") or "Subtitle format cannot be rebuilt as text.",
                    }
                )
                continue

            source_path = Path(candidate["file_path"])
            output_path = subtitle_dir / f"{source_path.stem}_smart_{index:02d}{source_path.suffix}"
            try:
                rebuilt_path = self.subtitle_rebuild_service.rebuild_external_subtitle(
                    source_path,
                    delete_intervals,
                    output_path,
                )
            except (SubtitleRebuildError, OSError, ValueError) as exc:
                subtitle_status.append(
                    {
                        "source": "external",
                        "status": "warning",
                        "path": str(source_path),
                        "message": f"{SMART_CUTTING_SUBTITLE_REBUILD_FAILED} {exc}",
                    }
                )
                continue

            subtitle_inputs.append(
                SubtitleMuxInput(
                    path=rebuilt_path,
                    language_code=candidate.get("language_code"),
                    title=_subtitle_title(candidate),
                    format=candidate.get("format"),
                )
            )
            subtitle_status.append(
                {
                    "source": "external",
                    "status": "rebuilt",
                    "path": str(source_path),
                    "output_path": str(rebuilt_path),
                    "message": SMART_CUTTING_SUBTITLE_SUCCESS,
                }
            )
        return subtitle_inputs, subtitle_status

    def _rebuild_embedded_subtitle(
        self,
        input_path: Path,
        candidate: dict,
        index: int,
        delete_intervals: list[tuple[float, float]],
        subtitle_dir: Path,
        subtitle_inputs: list[SubtitleMuxInput],
        subtitle_status: list[dict],
    ) -> None:
        stream_index = candidate.get("stream_index")
        if not candidate.get("is_text_readable") or stream_index is None:
            subtitle_status.append(
                {
                    "source": "embedded",
                    "status": "skipped",
                    "message": candidate.get("note") or SMART_CUTTING_EMBEDDED_UNSUPPORTED,
                    "stream_index": stream_index,
                }
            )
            return

        extension = _embedded_subtitle_extension(candidate)
        extracted_path = subtitle_dir / f"embedded_{stream_index}_{index:02d}{extension}"
        rebuilt_path = subtitle_dir / f"embedded_{stream_index}_{index:02d}_smart{extension}"
        try:
            self.embedded_subtitle_extract_service.extract_text_subtitle(
                input_path,
                int(stream_index),
                extracted_path,
            )
            self.subtitle_rebuild_service.rebuild_external_subtitle(
                extracted_path,
                delete_intervals,
                rebuilt_path,
            )
        except (EmbeddedSubtitleExtractError, SubtitleRebuildError, OSError, ValueError) as exc:
            subtitle_status.append(
                {
                    "source": "embedded",
                    "status": "warning",
                    "stream_index": stream_index,
                    "message": f"{SMART_CUTTING_SUBTITLE_REBUILD_FAILED} {exc}",
                }
            )
            return

        subtitle_inputs.append(
            SubtitleMuxInput(
                path=rebuilt_path,
                language_code=candidate.get("language_code"),
                title=_subtitle_title(candidate),
                format=candidate.get("codec_name"),
            )
        )
        subtitle_status.append(
            {
                "source": "embedded",
                "status": "rebuilt",
                "stream_index": stream_index,
                "output_path": str(rebuilt_path),
                "message": "Embedded text subtitles rebuilt.",
            }
        )

    def _reset_diagnostics(self) -> None:
        for service in (
            self.source_normalization_service,
            self.video_renderer,
            self.video_concat_service,
            self.audio_rebuild_service,
            self.embedded_subtitle_extract_service,
            self.mux_service,
        ):
            reset = getattr(service, "reset_diagnostics", None)
            if reset is not None:
                reset()

    def _commands(self) -> list[list[str]]:
        return (
            list(getattr(self.source_normalization_service, "commands", []))
            + list(getattr(self.video_renderer, "commands", []))
            + list(getattr(self.video_concat_service, "commands", []))
            + list(getattr(self.audio_rebuild_service, "commands", []))
            + list(getattr(self.embedded_subtitle_extract_service, "commands", []))
            + list(getattr(self.mux_service, "commands", []))
        )

    def _stderr(self) -> list[str]:
        return (
            list(getattr(self.source_normalization_service, "stderr", []))
            + list(getattr(self.video_renderer, "stderr", []))
            + list(getattr(self.video_concat_service, "stderr", []))
            + list(getattr(self.audio_rebuild_service, "stderr", []))
            + list(getattr(self.embedded_subtitle_extract_service, "stderr", []))
            + list(getattr(self.mux_service, "stderr", []))
        )


def _track_timescale(media_info) -> int | None:
    time_base = (media_info.video_stream.time_base or "") if media_info.video_stream else ""
    numerator, _, denominator = time_base.partition("/")
    if numerator == "1" and denominator.isdigit() and int(denominator) > 0:
        return int(denominator)
    return None


def _reorder_delay(media_info) -> int | None:
    stream = media_info.video_stream
    for raw_stream in (media_info.raw or {}).get("streams", []):
        if stream is not None and raw_stream.get("index") == stream.index:
            value = raw_stream.get("has_b_frames")
            return int(value) if value is not None else None
    return None


def _verify_timeline(packets: list[VideoPacket], expected_durations: list[float], label: str) -> None:
    problem = timeline_mismatch(packets, expected_durations, TIMELINE_TOLERANCE_SECONDS)
    if problem:
        raise VideoSegmentVerificationError(
            f"Smart Cutting stopped: {label} does not keep the source frame timing ({problem}). "
            "No output was kept."
        )


def _frame_aligned_audio_ranges(
    kept_intervals: list[tuple[float, float]],
    source_packets: list[VideoPacket],
) -> tuple[list[tuple[float, float]], list[float]]:
    """Audio pieces that follow the frames actually kept.

    A kept range [start, end) shows its frames from the first frame at or after ``start`` until the
    first frame at or after ``end``. Each audio piece starts with that first kept frame and is padded
    with silence (never with removed audio) up to the next frame position, so audio and video stay
    aligned across any number of off-grid cuts.
    """
    ranges = []
    durations = []
    for start, end in kept_intervals:
        first_frame = first_frame_at_or_after(source_packets, start)
        if first_frame is None or first_frame >= end:
            continue
        video_end = first_frame_at_or_after(source_packets, end)
        ranges.append((first_frame, end))
        durations.append((video_end if video_end is not None else end) - first_frame)
    return ranges, durations


def _subtitle_title(candidate: dict) -> str | None:
    return candidate.get("label") or candidate.get("language_name") or candidate.get("filename")


def _embedded_subtitle_extension(candidate: dict) -> str:
    codec = (candidate.get("codec_name") or candidate.get("codec") or "").casefold()
    if codec in {"ass", "ssa"}:
        return ".ass"
    if codec == "webvtt":
        return ".vtt"
    return ".srt"


def _emit(progress_callback, percentage: int, message: str) -> None:
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(percentage))), message)


def _scaled_progress(progress_callback, start_percent: int, end_percent: int):
    def emit(percent: int, message: str) -> None:
        span = max(0, end_percent - start_percent)
        _emit(progress_callback, start_percent + int(span * max(0, min(100, int(percent))) / 100), message)

    return emit
