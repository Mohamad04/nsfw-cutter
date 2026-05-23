import logging
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot

from core.job_registry import JobRegistry
from core.time_utils import timecode_to_seconds
from schemas.video_cut_schema import VideoCutRequest, VideoCutSegment
from services.keyframe_service import KeyframeService
from services.settings_service import SettingsService
from workers.video_cut_worker import VideoCutWorker


logger = logging.getLogger(__name__)


class VideoCutController(QObject):
    cutStarted = Signal(int)
    cutFinished = Signal(str)
    cutFailed = Signal(str)
    cutProgress = Signal(float)

    cutBusyChanged = Signal()
    cutStatusChanged = Signal()
    cutProgressValueChanged = Signal()
    cutErrorChanged = Signal()
    cutDetailsChanged = Signal()
    cutWarningChanged = Signal()

    def __init__(
        self,
        thread_pool=None,
        job_registry=None,
        worker_factory=None,
        settings_service: SettingsService | None = None,
        keyframe_service: KeyframeService | None = None,
    ):
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._job_registry = job_registry or JobRegistry()
        self._worker_factory = worker_factory or VideoCutWorker
        self._settings_service = settings_service or SettingsService()
        self._keyframe_service = keyframe_service or KeyframeService()
        self._keyframe_cache: dict[str, list[float]] = {}
        self._workers = {}
        self._cut_busy = False
        self._cut_status = "Video export idle"
        self._cut_progress_value = 0
        self._cut_error = ""
        self._cut_details = ""
        self._cut_warning = ""

    @Property(bool, notify=cutBusyChanged)
    def cutBusy(self):
        return self._cut_busy

    @Property(str, notify=cutStatusChanged)
    def cutStatus(self):
        return self._cut_status

    @Property(int, notify=cutProgressValueChanged)
    def cutProgressValue(self):
        return self._cut_progress_value

    @Property(str, notify=cutErrorChanged)
    def cutError(self):
        return self._cut_error

    @Property(str, notify=cutDetailsChanged)
    def cutDetails(self):
        return self._cut_details

    @Property(str, notify=cutWarningChanged)
    def cutWarning(self):
        return self._cut_warning

    @Slot(str, float, float, str)
    def exportSingleSegment(self, input_path: str, start_seconds: float, end_seconds: float, output_dir: str):
        self._start_export(
            input_path,
            [
                {
                    "index": 1,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                }
            ],
            output_dir,
            "export_clips_separate",
        )

    @Slot(str, "QVariantList", str, str)
    def exportSegments(self, input_path: str, segments, output_dir: str, export_mode: str):
        parsed_segments = []
        for index, segment in enumerate(segments or [], start=1):
            parsed_segments.append(self._segment_to_payload(index, segment))
        self._start_export(input_path, parsed_segments, output_dir, export_mode)

    @Slot(str, str, str, float, result="QVariantMap")
    def keyframeCutInfo(self, input_path: str, requested_start: str, requested_end: str, duration_seconds: float = 0.0):
        try:
            start_seconds = timecode_to_seconds(requested_start)
            end_seconds = timecode_to_seconds(requested_end)
            if end_seconds <= start_seconds:
                raise ValueError("End time must be after start time.")

            keyframes = self._keyframes_for_path(input_path)
            return self._keyframe_service.align_interval(
                keyframes,
                start_seconds,
                end_seconds,
                duration_seconds if duration_seconds > 0 else None,
            )
        except Exception as exc:
            logger.info("Unable to align keyframe interval: %s", exc)
            return _fallback_keyframe_info(requested_start, requested_end, str(exc))

    @Slot(str, "QVariant", str)
    def exportCutRow(self, input_path: str, segment, output_dir: str):
        self.exportSegments(input_path, [segment], output_dir, "export_clips_separate")

    def _start_export(
        self,
        input_path: str,
        segments: list[dict],
        output_dir: str,
        export_mode: str,
    ):
        try:
            input_file = Path(input_path)
            resolved_output_dir = self._resolve_output_dir(input_file, output_dir)
            request = VideoCutRequest(
                input_path=input_file,
                output_dir=resolved_output_dir,
                segments=[VideoCutSegment.model_validate(segment) for segment in segments],
                export_mode=export_mode or "remove_intervals",
            )
        except (ValidationError, ValueError) as exc:
            self._set_cut_error(_format_validation_error(exc))
            self._set_cut_status("Video export failed")
            self.cutFailed.emit(self._cut_error)
            return

        job_key = f"video_cut:{request.input_path}:{request.export_mode}:{request.cut_mode}:{len(request.segments)}"
        if not self._job_registry.try_start(job_key):
            self._set_cut_status("This video export is already running.")
            return

        self._remember_preferences(request.output_dir, str(request.export_mode))
        self._set_cut_busy(True)
        self._set_cut_error("")
        self._set_cut_warning("")
        self._set_cut_progress(0)
        self._set_cut_status(_start_status(request.export_mode))

        worker = self._worker_factory(job_key=job_key, request_data=request.model_dump(mode="json"))
        self._workers[job_key] = worker
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.error.connect(self._on_error)
        self.cutStarted.emit(0)
        self._thread_pool.start(worker)

    @Slot(str, int, str)
    def _on_progress(self, job_key: str, percentage: int, message: str):
        if not self._job_registry.is_running(job_key):
            return
        self._set_cut_progress(percentage)
        self._set_cut_status(message)
        self.cutProgress.emit(float(percentage))

    @Slot(str, object)
    def _on_finished(self, job_key: str, result):
        self._job_registry.finish(job_key)
        self._workers.pop(job_key, None)
        result_payload = result.get("result", {}) if isinstance(result, dict) else {}
        output_paths = result_payload.get("output_paths", []) if isinstance(result_payload, dict) else []
        warning = str(result_payload.get("duration_warning") or "") if isinstance(result_payload, dict) else ""
        message = f"Video export completed: {len(output_paths)} output(s)"
        self._set_cut_progress(100)
        self._set_cut_status(message)
        self._set_cut_warning(warning)
        self._set_cut_details(_format_cut_details(result_payload))
        self._set_cut_busy(False)
        self.cutFinished.emit(message)

    @Slot(str, str)
    def _on_error(self, job_key: str, error_message: str):
        self._job_registry.finish(job_key)
        self._workers.pop(job_key, None)
        self._set_cut_error(error_message)
        self._set_cut_status("Video export failed")
        self._set_cut_busy(False)
        self.cutFailed.emit(error_message)

    def _segment_to_payload(self, index: int, segment) -> dict:
        if not isinstance(segment, dict):
            raise ValueError("Each cut segment must be an object.")

        requested_start_seconds = _segment_seconds(segment, "requested_start_seconds", "requestedStartSeconds")
        requested_end_seconds = _segment_seconds(segment, "requested_end_seconds", "requestedEndSeconds")
        if requested_start_seconds is None:
            requested_start_seconds = timecode_to_seconds(segment.get("start", ""))
        if requested_end_seconds is None:
            requested_end_seconds = timecode_to_seconds(segment.get("end", ""))

        start_seconds = _segment_seconds(segment, "safe_start_seconds", "safe_start", "safeStart")
        end_seconds = _segment_seconds(segment, "safe_end_seconds", "safe_end", "safeEnd")
        if start_seconds is None:
            start_seconds = _segment_seconds(segment, "start_seconds")
        if end_seconds is None:
            end_seconds = _segment_seconds(segment, "end_seconds")
        if start_seconds is None:
            start_seconds = requested_start_seconds
        if end_seconds is None:
            end_seconds = requested_end_seconds

        return {
            "index": index,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "requested_start_seconds": requested_start_seconds,
            "requested_end_seconds": requested_end_seconds,
            "previous_keyframe_start": _segment_seconds(segment, "previous_keyframe_start", "previousKeyframeStart"),
            "next_keyframe_start": _segment_seconds(segment, "next_keyframe_start", "nextKeyframeStart"),
            "previous_keyframe_end": _segment_seconds(segment, "previous_keyframe_end", "previousKeyframeEnd"),
            "next_keyframe_end": _segment_seconds(segment, "next_keyframe_end", "nextKeyframeEnd"),
            "label": str(segment.get("reason") or segment.get("label") or "").strip() or None,
        }

    def _keyframes_for_path(self, input_path: str) -> list[float]:
        video_path = Path(input_path)
        if not video_path.is_file():
            raise ValueError("Select a video before reading keyframes.")

        cache_key = str(video_path.resolve())
        if cache_key not in self._keyframe_cache:
            self._keyframe_cache[cache_key] = self._keyframe_service.extract_keyframes(video_path)
        return self._keyframe_cache[cache_key]

    def _resolve_output_dir(self, input_file: Path, output_dir: str) -> Path:
        if output_dir and str(output_dir).strip():
            return Path(output_dir)

        settings = self._settings_service.load()
        if settings.default_export_dir or settings.export_dir:
            return settings.default_export_dir or settings.export_dir
        return input_file.parent / "cuts"

    def _remember_preferences(self, output_dir: Path, export_mode: str):
        try:
            self._settings_service.update(
                default_export_dir=output_dir,
                export_dir=output_dir,
                last_export_mode=export_mode,
            )
        except (OSError, ValidationError):
            logger.exception("Unable to persist video export settings")

    def _set_cut_busy(self, value: bool):
        if self._cut_busy != value:
            self._cut_busy = value
            self.cutBusyChanged.emit()

    def _set_cut_status(self, value: str):
        if self._cut_status != value:
            self._cut_status = value
            self.cutStatusChanged.emit()

    def _set_cut_progress(self, value: int):
        value = max(0, min(100, int(value)))
        if self._cut_progress_value != value:
            self._cut_progress_value = value
            self.cutProgressValueChanged.emit()

    def _set_cut_error(self, value: str):
        if self._cut_error != value:
            self._cut_error = value
            self.cutErrorChanged.emit()

    def _set_cut_details(self, value: str):
        if self._cut_details != value:
            self._cut_details = value
            self.cutDetailsChanged.emit()

    def _set_cut_warning(self, value: str):
        if self._cut_warning != value:
            self._cut_warning = value
            self.cutWarningChanged.emit()


def _format_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        return first_error.get("msg") or "Invalid fast cut request."
    return str(exc)


def _start_status(export_mode) -> str:
    export_value = getattr(export_mode, "value", str(export_mode))
    operation = {
        "remove_intervals": "Removing selected intervals",
        "export_clips_separate": "Exporting selected clips",
        "export_clips_merged": "Merging selected clips",
    }.get(export_value, "Starting video export")
    return f"{operation} with FFmpeg stream copy"


def _format_cut_details(result_payload) -> str:
    if not isinstance(result_payload, dict) or not result_payload:
        return ""

    lines = [
        f"Mode: {result_payload.get('export_mode', '')}",
        f"Cutting: {result_payload.get('cut_mode', '')}",
        f"Selected intervals: {len(result_payload.get('segments') or [])}",
        f"Input duration: {_duration_text(result_payload.get('input_duration_seconds'))}",
        f"Expected duration: {_duration_text(result_payload.get('expected_output_duration_seconds'))}",
        f"Actual duration: {_duration_text(result_payload.get('actual_output_duration_seconds'))}",
        f"Difference: {_duration_text(result_payload.get('duration_difference_seconds'))}",
    ]
    normalized_intervals = result_payload.get("normalized_intervals") or []
    kept_intervals = result_payload.get("kept_intervals") or []
    if normalized_intervals:
        lines.append(f"Intervals: {normalized_intervals}")
    if kept_intervals:
        lines.append(f"Kept ranges: {kept_intervals}")
    commands = result_payload.get("ffmpeg_commands") or []
    lines.append(f"FFmpeg commands: {len(commands)}")
    if commands:
        lines.append(f"Final FFmpeg command: {' '.join(str(part) for part in commands[-1])}")
    return "\n".join(lines)


def _duration_text(value) -> str:
    if value in (None, ""):
        return "-"
    return f"{float(value):.3f}s"


def _segment_seconds(segment: dict, *keys: str) -> float | None:
    for key in keys:
        value = segment.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        return timecode_to_seconds(str(value))
    return None


def _fallback_keyframe_info(requested_start: str, requested_end: str, error: str) -> dict:
    try:
        start_seconds = timecode_to_seconds(requested_start)
        end_seconds = timecode_to_seconds(requested_end)
    except ValueError:
        start_seconds = 0.0
        end_seconds = 0.0

    return {
        "valid": False,
        "error": error,
        "requested_start": start_seconds,
        "requested_end": end_seconds,
        "safe_start": start_seconds,
        "safe_end": end_seconds,
        "previous_keyframe_start": start_seconds,
        "next_keyframe_start": start_seconds,
        "previous_keyframe_end": end_seconds,
        "next_keyframe_end": end_seconds,
        "extra_before": 0.0,
        "extra_after": 0.0,
    }
