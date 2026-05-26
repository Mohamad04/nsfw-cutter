import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from core.job_registry import JobRegistry
from services.settings_service import SettingsService
from services.video_import_service import VideoImportService
from workers.prepare_export_job_worker import PrepareExportJobWorker
from workers.video_export_worker import VideoExportWorker


logger = logging.getLogger(__name__)


class AppController(QObject):
    DEFAULT_MAX_THREAD_COUNT = 2

    videoUrlChanged = Signal()
    videoNameChanged = Signal()
    subtitleStatusChanged = Signal()
    projectStatusChanged = Signal()
    currentFolderChanged = Signal()
    availableVideosChanged = Signal()
    selectedVideoPathChanged = Signal()
    exportBusyChanged = Signal()
    exportProgressChanged = Signal()
    exportStatusChanged = Signal()
    backendPreparationBusyChanged = Signal()
    backendPreparationProgressChanged = Signal()
    backendPreparationStatusChanged = Signal()
    currentExportJobIdChanged = Signal()
    currentExportJobJsonPathChanged = Signal()

    def __init__(
        self,
        video_import_service=None,
        thread_pool=None,
        job_registry=None,
        worker_factory=None,
        max_thread_count=None,
        prepare_worker_factory=None,
        settings_service=None,
    ):
        super().__init__()
        self.video_import_service = video_import_service or VideoImportService()
        self.settings_service = settings_service or SettingsService()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._max_thread_count = (
            self.DEFAULT_MAX_THREAD_COUNT if max_thread_count is None else int(max_thread_count)
        )
        self._thread_pool.setMaxThreadCount(self._max_thread_count)
        self._job_registry = job_registry or JobRegistry()
        self._worker_factory = worker_factory or VideoExportWorker
        self._prepare_worker_factory = prepare_worker_factory or PrepareExportJobWorker
        self._active_export_workers = {}
        self._active_prepare_workers = {}

        self._video_url = ""
        self._video_name = "No video selected"
        self._subtitle_status = "Subtitle: not detected"
        self._project_status = "Ready"
        self._current_folder = ""
        self._available_videos = []
        self._selected_video_path = ""
        self._export_busy = False
        self._export_progress = 0
        self._export_status = "No export running"
        self._backend_preparation_busy = False
        self._backend_preparation_progress = 0
        self._backend_preparation_status = "No backend preparation running"
        self._current_export_job_id = ""
        self._current_export_job_json_path = ""

    @Property(str, notify=videoUrlChanged)
    def videoUrl(self):
        return self._video_url

    @Property(str, notify=videoNameChanged)
    def videoName(self):
        return self._video_name

    @Property(str, notify=subtitleStatusChanged)
    def subtitleStatus(self):
        return self._subtitle_status

    @Property(str, notify=projectStatusChanged)
    def projectStatus(self):
        return self._project_status

    @Property(str, notify=currentFolderChanged)
    def currentFolder(self):
        return self._current_folder

    @Property("QVariantList", notify=availableVideosChanged)
    def availableVideos(self):
        return self._available_videos

    @Property(str, notify=selectedVideoPathChanged)
    def selectedVideoPath(self):
        return self._selected_video_path

    @Property(bool, notify=exportBusyChanged)
    def exportBusy(self):
        return self._export_busy

    @Property(int, notify=exportProgressChanged)
    def exportProgress(self):
        return self._export_progress

    @Property(str, notify=exportStatusChanged)
    def exportStatus(self):
        return self._export_status

    @Property(bool, notify=backendPreparationBusyChanged)
    def backendPreparationBusy(self):
        return self._backend_preparation_busy

    @Property(int, notify=backendPreparationProgressChanged)
    def backendPreparationProgress(self):
        return self._backend_preparation_progress

    @Property(str, notify=backendPreparationStatusChanged)
    def backendPreparationStatus(self):
        return self._backend_preparation_status

    @Property(str, notify=currentExportJobIdChanged)
    def currentExportJobId(self):
        return self._current_export_job_id

    @Property(str, notify=currentExportJobJsonPathChanged)
    def currentExportJobJsonPath(self):
        return self._current_export_job_json_path

    @Slot()
    def browseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select video folder")
        if folder:
            self.loadFolder(folder)

    @Slot(str)
    def loadFolder(self, folder: str):
        try:
            self._set_current_folder(folder)
            videos = self.video_import_service.list_importable_videos(folder)
            self._available_videos = videos
            self.availableVideosChanged.emit()

            if not videos:
                self._set_project_status("No video found in selected folder")
                return

            self._set_project_status(f"{len(videos)} video(s) found. Select one to load.")
        except ValueError as exc:
            self._set_current_folder("")
            self._available_videos = []
            self.availableVideosChanged.emit()
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while loading folder")
            self._set_current_folder("")
            self._available_videos = []
            self.availableVideosChanged.emit()
            self._set_project_status("Unexpected error while loading folder")

    @Slot(str)
    def loadVideoFile(self, file_path: str):
        try:
            result = self.video_import_service.import_video_file(file_path)
            self._apply_loaded_video(result)
        except ValueError as exc:
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while loading video")
            self._set_project_status("Unexpected error while loading video")

    @Slot()
    def restoreLastVideo(self):
        last_video = self.settings_service.get_last_video()
        if last_video:
            self.loadVideoFile(str(last_video))

    @Slot(int)
    def selectAvailableVideo(self, index: int):
        try:
            if index < 0 or index >= len(self._available_videos):
                raise ValueError("Invalid video selection")

            self.loadVideoFile(self._available_videos[index]["path"])
        except ValueError as exc:
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while selecting video")
            self._set_project_status("Unexpected error while selecting video")

    @Slot()
    def clearVideo(self):
        self._video_url = ""
        self._video_name = "No video selected"
        self._subtitle_status = "Subtitle: not detected"
        self._project_status = "Ready"
        self._selected_video_path = ""

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.subtitleStatusChanged.emit()
        self.projectStatusChanged.emit()
        self.selectedVideoPathChanged.emit()

    @Slot()
    @Slot(str, str)
    def startLosslessExport(self, input_path: str = "", output_path: str = ""):
        input_path = input_path or self._selected_video_path
        if not input_path:
            self._set_export_status("Select a video before exporting.")
            return

        output_path = output_path or self._default_export_output_path(input_path)
        job_key = f"export:{input_path}:{output_path}"

        if not self._job_registry.try_start(job_key):
            self._set_export_status("This export is already running.")
            return

        self._set_export_busy(True)
        self._set_export_progress(0)
        self._set_export_status("Preparing export...")

        worker = self._worker_factory(
            job_key=job_key,
            input_path=input_path,
            output_path=output_path,
        )
        self._active_export_workers[job_key] = worker

        worker.signals.progress.connect(self._on_export_progress)
        worker.signals.finished.connect(self._on_export_finished)
        worker.signals.error.connect(self._on_export_error)

        self._thread_pool.start(worker)

    @Slot(str, str)
    def prepareExportJob(self, video_path: str, output_path: str = ""):
        video_path = video_path or self._selected_video_path
        if not video_path:
            self._set_backend_preparation_status("Select a video before preparing export.")
            return

        job_key = f"prepare_export:{video_path}:{output_path}"
        if not self._job_registry.try_start(job_key):
            self._set_backend_preparation_status("This backend preparation is already running.")
            return

        self._set_backend_preparation_busy(True)
        self._set_backend_preparation_progress(0)
        self._set_backend_preparation_status("Starting backend preparation")

        worker = self._prepare_worker_factory(
            job_key=job_key,
            input_path=video_path,
            output_path=output_path,
        )
        self._active_prepare_workers[job_key] = worker
        worker.signals.progress.connect(self._on_backend_preparation_progress)
        worker.signals.finished.connect(self._on_backend_preparation_finished)
        worker.signals.error.connect(self._on_backend_preparation_error)

        self._thread_pool.start(worker)

    @Slot("QVariantList")
    def exportCuts(self, cuts):
        if not cuts:
            self._set_project_status("No cuts to export")
            return

        default_name = self._default_cuts_json_path()
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            None,
            "Export cuts JSON",
            default_name,
            "JSON files (*.json)",
        )
        if not file_path:
            return

        try:
            self.exportCutsToPath(cuts, file_path)
        except ValueError as exc:
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while exporting cuts")
            self._set_project_status("Unexpected error while exporting cuts")

    @Slot(result="QVariantList")
    def importCuts(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "Import cuts JSON",
            "",
            "JSON files (*.json)",
        )
        if not file_path:
            return []

        try:
            return self.importCutsFromPath(file_path)
        except ValueError as exc:
            self._set_project_status(str(exc))
            return []
        except Exception:
            logger.exception("Unexpected error while importing cuts")
            self._set_project_status("Unexpected error while importing cuts")
            return []

    def exportCutsToPath(self, cuts, file_path: str):
        normalized_cuts = [self._normalize_cut(cut) for cut in cuts]
        if not normalized_cuts:
            raise ValueError("No cuts to export")

        output_path = Path(file_path)
        if output_path.suffix.lower() != ".json":
            output_path = output_path.with_suffix(".json")

        payload = {
            "version": 1,
            "video": {
                "name": self._video_name,
                "path": self._selected_video_path,
            },
            "cuts": normalized_cuts,
        }

        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._set_project_status(f"Exported {len(normalized_cuts)} cut(s) to {output_path.name}")

    def importCutsFromPath(self, file_path: str):
        input_path = Path(file_path)
        if not input_path.is_file():
            raise ValueError("Selected cuts JSON file does not exist")

        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid cuts JSON: {exc.msg}") from exc

        raw_cuts = payload.get("cuts") if isinstance(payload, dict) else payload
        if not isinstance(raw_cuts, list):
            raise ValueError("Cuts JSON must contain a cuts array")

        normalized_cuts = [self._normalize_cut(cut) for cut in raw_cuts]
        self._set_project_status(f"Imported {len(normalized_cuts)} cut(s) from {input_path.name}")
        return normalized_cuts

    @Slot(str, int, str)
    def _on_export_progress(self, job_key: str, percentage: int, message: str):
        if not self._job_registry.is_running(job_key):
            return

        self._set_export_progress(percentage)
        self._set_export_status(message)

    @Slot(str, object)
    def _on_export_finished(self, job_key: str, result):
        self._job_registry.finish(job_key)
        self._active_export_workers.pop(job_key, None)
        self._set_export_progress(100)
        self._set_export_status(f"Export completed: {result}")
        self._set_export_busy(False)

    @Slot(str, str)
    def _on_export_error(self, job_key: str, error_message: str):
        self._job_registry.finish(job_key)
        self._active_export_workers.pop(job_key, None)
        self._set_export_status(f"Export failed: {error_message}")
        self._set_export_busy(False)

    @Slot(str, int, str)
    def _on_backend_preparation_progress(self, job_key: str, percentage: int, message: str):
        if not self._job_registry.is_running(job_key):
            return

        self._set_backend_preparation_progress(percentage)
        self._set_backend_preparation_status(message)

    @Slot(str, object)
    def _on_backend_preparation_finished(self, job_key: str, result):
        self._job_registry.finish(job_key)
        self._active_prepare_workers.pop(job_key, None)
        export_job = result.get("export_job", {}) if isinstance(result, dict) else {}
        artifacts = result.get("json_artifacts", {}) if isinstance(result, dict) else {}
        self._set_backend_preparation_progress(100)
        self._set_backend_preparation_status("Preparation completed")
        self._set_current_export_job_id(export_job.get("job_id", ""))
        self._set_current_export_job_json_path(artifacts.get("export_job_json_path", ""))
        self._set_backend_preparation_busy(False)

    @Slot(str, str)
    def _on_backend_preparation_error(self, job_key: str, error_message: str):
        self._job_registry.finish(job_key)
        self._active_prepare_workers.pop(job_key, None)
        self._set_backend_preparation_status(f"Preparation failed: {error_message}")
        self._set_backend_preparation_busy(False)

    def _apply_loaded_video(self, result: dict):
        self._video_url = result.get("video_url", "")
        self._video_name = result.get("video_name", "No video selected")
        self._selected_video_path = result.get("video_path", "")

        if result.get("subtitle_found"):
            self._subtitle_status = f"Subtitle found: {result.get('subtitle_name')}"
        else:
            self._subtitle_status = "Subtitle: not detected"

        self._project_status = result.get("status", "Video loaded")

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.subtitleStatusChanged.emit()
        self.projectStatusChanged.emit()
        self.selectedVideoPathChanged.emit()

        if self._selected_video_path:
            try:
                self.settings_service.save_last_video(self._selected_video_path)
            except OSError:
                logger.exception("Unable to persist last opened video")

    def _set_project_status(self, status: str):
        self._project_status = status
        self.projectStatusChanged.emit()

    def _set_current_folder(self, folder: str):
        if self._current_folder != folder:
            self._current_folder = folder
            self.currentFolderChanged.emit()

    def _set_export_busy(self, value: bool):
        if self._export_busy != value:
            self._export_busy = value
            self.exportBusyChanged.emit()

    def _set_export_progress(self, value: int):
        value = max(0, min(100, int(value)))
        if self._export_progress != value:
            self._export_progress = value
            self.exportProgressChanged.emit()

    def _set_export_status(self, value: str):
        if self._export_status != value:
            self._export_status = value
            self.exportStatusChanged.emit()

    def _set_backend_preparation_busy(self, value: bool):
        if self._backend_preparation_busy != value:
            self._backend_preparation_busy = value
            self.backendPreparationBusyChanged.emit()

    def _set_backend_preparation_progress(self, value: int):
        value = max(0, min(100, int(value)))
        if self._backend_preparation_progress != value:
            self._backend_preparation_progress = value
            self.backendPreparationProgressChanged.emit()

    def _set_backend_preparation_status(self, value: str):
        if self._backend_preparation_status != value:
            self._backend_preparation_status = value
            self.backendPreparationStatusChanged.emit()

    def _set_current_export_job_id(self, value: str):
        if self._current_export_job_id != value:
            self._current_export_job_id = value
            self.currentExportJobIdChanged.emit()

    def _set_current_export_job_json_path(self, value: str):
        if self._current_export_job_json_path != value:
            self._current_export_job_json_path = value
            self.currentExportJobJsonPathChanged.emit()

    def _default_export_output_path(self, input_path: str) -> str:
        source = Path(input_path)
        return str(source.with_name(f"{source.stem}_export{source.suffix}"))

    def _default_cuts_json_path(self) -> str:
        if self._selected_video_path:
            source = Path(self._selected_video_path)
            return str(source.with_name(f"{source.stem}_cuts.json"))
        return "cuts.json"

    def _normalize_cut(self, cut):
        if not isinstance(cut, dict):
            raise ValueError("Each cut must be a JSON object")

        start = str(cut.get("start", "")).strip()
        end = str(cut.get("end", "")).strip()
        if self._parse_time_to_seconds(start) >= self._parse_time_to_seconds(end):
            raise ValueError("Each cut must have start before end")

        normalized = {
            "start": start,
            "end": end,
            "reason": str(cut.get("reason") or "Manual cut"),
            "tags": str(cut.get("tags") or "manual"),
            "source": str(cut.get("source") or "Manual"),
            "score": str(cut.get("score") or "--"),
        }
        if _has_keyframe_cut_fields(cut):
            safe_start = str(cut.get("safe_start") or cut.get("safeStart") or start).strip()
            safe_end = str(cut.get("safe_end") or cut.get("safeEnd") or end).strip()
            normalized.update(
                {
                    "safeStart": safe_start,
                    "safeEnd": safe_end,
                    "previousKeyframeStart": str(
                        cut.get("previous_keyframe_start") or cut.get("previousKeyframeStart") or safe_start
                    ),
                    "nextKeyframeStart": str(
                        cut.get("next_keyframe_start") or cut.get("nextKeyframeStart") or start
                    ),
                    "previousKeyframeEnd": str(
                        cut.get("previous_keyframe_end") or cut.get("previousKeyframeEnd") or end
                    ),
                    "nextKeyframeEnd": str(
                        cut.get("next_keyframe_end") or cut.get("nextKeyframeEnd") or safe_end
                    ),
                    "extraBefore": str(cut.get("extraBefore") or cut.get("extra_before") or "0.0s"),
                    "extraAfter": str(cut.get("extraAfter") or cut.get("extra_after") or "0.0s"),
                }
            )
        return normalized

    def _parse_time_to_seconds(self, value: str) -> int:
        parts = value.split(":")
        if len(parts) != 3:
            raise ValueError("Cut times must use HH:MM:SS")

        try:
            hours, minutes, seconds = [int(part) for part in parts]
        except ValueError as exc:
            raise ValueError("Cut times must use HH:MM:SS") from exc

        if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59:
            raise ValueError("Cut times must use HH:MM:SS")

        return hours * 3600 + minutes * 60 + seconds


def _has_keyframe_cut_fields(cut: dict) -> bool:
    return any(
        key in cut
        for key in (
            "safe_start",
            "safeStart",
            "safe_end",
            "safeEnd",
            "previous_keyframe_start",
            "previousKeyframeStart",
            "next_keyframe_start",
            "nextKeyframeStart",
            "previous_keyframe_end",
            "previousKeyframeEnd",
            "next_keyframe_end",
            "nextKeyframeEnd",
            "extra_before",
            "extraBefore",
            "extra_after",
            "extraAfter",
        )
    )
