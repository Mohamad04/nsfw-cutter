import shutil
import uuid
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
from services.export.smart_cut_planner import SmartCutPlanner
from services.export.subtitle_rebuild_service import (
    EmbeddedSubtitleExtractError,
    EmbeddedSubtitleExtractService,
    SubtitleRebuildError,
    SubtitleRebuildService,
)
from services.export.video_concat_service import VideoConcatService
from services.export.video_segment_renderer import VideoSegmentRenderer
from services.subtitles.processing_service import SubtitleService


SMART_CUTTING_MODE = "smart_cutting"
SMART_CUTTING_SUBTITLE_SUCCESS = "External text subtitles rebuilt."
SMART_CUTTING_EMBEDDED_UNSUPPORTED = "Embedded image or unsupported subtitles are not rebuilt in Smart Cutting yet."
SMART_CUTTING_SUBTITLE_REBUILD_FAILED = "Subtitle rebuild failed. External subtitles were skipped."


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
        cache_dir: str | Path | None = None,
        debug_keep_temp: bool = False,
    ):
        self.media_probe_service = media_probe_service or MediaProbeService()
        self.keyframe_service = keyframe_service or ExportKeyframeService()
        self.planner = planner or SmartCutPlanner()
        self.video_renderer = video_renderer or VideoSegmentRenderer()
        self.video_concat_service = video_concat_service or VideoConcatService()
        self.audio_rebuild_service = audio_rebuild_service or AudioRebuildService()
        self.subtitle_service = subtitle_service or SubtitleService()
        self.subtitle_rebuild_service = subtitle_rebuild_service or SubtitleRebuildService()
        self.embedded_subtitle_extract_service = embedded_subtitle_extract_service or EmbeddedSubtitleExtractService()
        self.mux_service = mux_service or MuxService()
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

            _emit(progress_callback, 10, "Loading keyframes")
            keyframes = validate_keyframes(
                self.keyframe_service.extract_keyframes(input_path),
                media_info.duration_seconds,
            )

            _emit(progress_callback, 15, "Planning smart cut")
            delete_intervals = requested_delete_intervals(segments, media_info.duration_seconds)
            kept_intervals = invert_removed_intervals(delete_intervals, media_info.duration_seconds)
            expected_duration = expected_edited_duration(media_info.duration_seconds, delete_intervals)
            plan = self.planner.build_plan(delete_intervals, keyframes, media_info.duration_seconds)

            _emit(progress_callback, 22, "Exporting video chunks")
            chunks = self.video_renderer.render_plan(
                input_path,
                plan,
                chunks_dir,
                progress_callback=_scaled_progress(progress_callback, 22, 55),
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

            audio_path = None
            if media_info.has_audio:
                _emit(progress_callback, 68, "Rebuilding audio")
                audio_path = self.audio_rebuild_service.rebuild_audio(
                    input_path,
                    kept_intervals,
                    temp_dir / "smart_audio.m4a",
                    progress_callback=_scaled_progress(progress_callback, 68, 78),
                )

            _emit(progress_callback, 80, "Rebuilding subtitles")
            subtitle_inputs, subtitle_status = self._rebuild_subtitles(
                input_path,
                delete_intervals,
                subtitle_dir,
            )

            output_path = make_unique_path(output_dir / f"{input_path.stem}_smart_cut{input_path.suffix}")
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
            list(getattr(self.video_renderer, "commands", []))
            + list(getattr(self.video_concat_service, "commands", []))
            + list(getattr(self.audio_rebuild_service, "commands", []))
            + list(getattr(self.embedded_subtitle_extract_service, "commands", []))
            + list(getattr(self.mux_service, "commands", []))
        )

    def _stderr(self) -> list[str]:
        return (
            list(getattr(self.video_renderer, "stderr", []))
            + list(getattr(self.video_concat_service, "stderr", []))
            + list(getattr(self.audio_rebuild_service, "stderr", []))
            + list(getattr(self.embedded_subtitle_extract_service, "stderr", []))
            + list(getattr(self.mux_service, "stderr", []))
        )


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
