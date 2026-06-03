from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot

from controllers.common.qt_state import clamp_percent
from controllers.video_cut.cut_export_runner import CutExportCallbacks, CutExportRunner
from controllers.video_cut.keyframe_alignment import KeyframeAlignmentController
from controllers.video_cut.output_preferences import OutputPreferences
from controllers.video_cut.segment_mapper import segment_to_payload
from controllers.video_cut.video_cut_state import VideoCutState
from core.job_registry import JobRegistry
from services.editing.cut_plan_service import CutPlanService
from services.editing.keyframe_service import KeyframeService
from services.settings_service import SettingsService
from workers.video_cut_worker import VideoCutWorker


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
        cut_plan_service: CutPlanService | None = None,
    ):
        super().__init__()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._job_registry = job_registry or JobRegistry()
        self._worker_factory = worker_factory or VideoCutWorker
        self._settings_service = settings_service or SettingsService()
        self._keyframe_service = keyframe_service or KeyframeService()
        self._cut_plan_service = cut_plan_service or CutPlanService()
        self._state = VideoCutState()
        self._keyframe_alignment = KeyframeAlignmentController(
            self._keyframe_service,
            self._cut_plan_service,
        )
        self._output_preferences = OutputPreferences(self._settings_service)
        self._cut_export_runner = CutExportRunner(
            self._thread_pool,
            self._job_registry,
            self._worker_factory,
            self._output_preferences,
        )

    @Property(bool, notify=cutBusyChanged)
    def cutBusy(self):
        return self._state.cut_busy

    @Property(str, notify=cutStatusChanged)
    def cutStatus(self):
        return self._state.cut_status

    @Property(int, notify=cutProgressValueChanged)
    def cutProgressValue(self):
        return self._state.cut_progress_value

    @Property(str, notify=cutErrorChanged)
    def cutError(self):
        return self._state.cut_error

    @Property(str, notify=cutDetailsChanged)
    def cutDetails(self):
        return self._state.cut_details

    @Property(str, notify=cutWarningChanged)
    def cutWarning(self):
        return self._state.cut_warning

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
        try:
            parsed_segments = []
            for index, segment in enumerate(segments or [], start=1):
                parsed_segments.append(segment_to_payload(index, segment))
        except ValueError as exc:
            error_message = str(exc)
            self._set_cut_error(error_message)
            self._set_cut_status("Video export failed")
            self.cutFailed.emit(error_message)
            return
        self._start_export(input_path, parsed_segments, output_dir, export_mode)

    @Slot(str, str, str, float, result="QVariantMap")
    def keyframeCutInfo(self, input_path: str, requested_start: str, requested_end: str, duration_seconds: float = 0.0):
        return self._keyframe_alignment.get_cut_info(
            input_path,
            requested_start,
            requested_end,
            duration_seconds,
        )

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
        self._cut_export_runner.start(
            input_path,
            segments,
            output_dir,
            export_mode,
            CutExportCallbacks(
                on_busy=self._set_cut_busy,
                on_status=self._set_cut_status,
                on_progress_value=self._set_cut_progress,
                on_error=self._set_cut_error,
                on_details=self._set_cut_details,
                on_warning=self._set_cut_warning,
                on_started=self.cutStarted.emit,
                on_finished=self.cutFinished.emit,
                on_failed=self.cutFailed.emit,
                on_progress=self.cutProgress.emit,
            ),
        )

    @Slot(str, int, str)
    def _on_progress(self, job_key: str, percentage: int, message: str):
        self._cut_export_runner.handle_progress(job_key, percentage, message)

    @Slot(str, object)
    def _on_finished(self, job_key: str, result):
        self._cut_export_runner.handle_finished(job_key, result)

    @Slot(str, str)
    def _on_error(self, job_key: str, error_message: str):
        self._cut_export_runner.handle_error(job_key, error_message)

    def _segment_to_payload(self, index: int, segment) -> dict:
        return segment_to_payload(index, segment)

    def _set_cut_busy(self, value: bool):
        if self._state.cut_busy != value:
            self._state.cut_busy = value
            self.cutBusyChanged.emit()

    def _set_cut_status(self, value: str):
        if self._state.cut_status != value:
            self._state.cut_status = value
            self.cutStatusChanged.emit()

    def _set_cut_progress(self, value: int):
        value = clamp_percent(value)
        if self._state.cut_progress_value != value:
            self._state.cut_progress_value = value
            self.cutProgressValueChanged.emit()

    def _set_cut_error(self, value: str):
        if self._state.cut_error != value:
            self._state.cut_error = value
            self.cutErrorChanged.emit()

    def _set_cut_details(self, value: str):
        if self._state.cut_details != value:
            self._state.cut_details = value
            self.cutDetailsChanged.emit()

    def _set_cut_warning(self, value: str):
        if self._state.cut_warning != value:
            self._state.cut_warning = value
            self.cutWarningChanged.emit()
