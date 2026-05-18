import logging
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from core.job_registry import JobRegistry
from services.video_import_service import VideoImportService
from workers.video_export_worker import VideoExportWorker


logger = logging.getLogger(__name__)


class AppController(QObject):
    videoUrlChanged = Signal()
    videoNameChanged = Signal()
    subtitleStatusChanged = Signal()
    projectStatusChanged = Signal()
    availableVideosChanged = Signal()
    selectedVideoPathChanged = Signal()
    exportBusyChanged = Signal()
    exportProgressChanged = Signal()
    exportStatusChanged = Signal()

    def __init__(
        self,
        video_import_service=None,
        thread_pool=None,
        job_registry=None,
        worker_factory=None,
    ):
        super().__init__()
        self.video_import_service = video_import_service or VideoImportService()
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._thread_pool.setMaxThreadCount(2)
        self._job_registry = job_registry or JobRegistry()
        self._worker_factory = worker_factory or VideoExportWorker
        self._active_export_workers = {}

        self._video_url = ""
        self._video_name = "No video selected"
        self._subtitle_status = "Subtitle: not detected"
        self._project_status = "Ready"
        self._available_videos = []
        self._selected_video_path = ""
        self._export_busy = False
        self._export_progress = 0
        self._export_status = "No export running"

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

    @Slot()
    def browseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select video folder")
        if folder:
            self.loadFolder(folder)

    @Slot(str)
    def loadFolder(self, folder: str):
        try:
            videos = self.video_import_service.list_importable_videos(folder)
            self._available_videos = videos
            self.availableVideosChanged.emit()

            if not videos:
                self._set_project_status("No video found in selected folder")
                return

            self._set_project_status(f"{len(videos)} video(s) found. Select one to load.")
        except ValueError as exc:
            self._available_videos = []
            self.availableVideosChanged.emit()
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while loading folder")
            self._available_videos = []
            self.availableVideosChanged.emit()
            self._set_project_status("Unexpected error while loading folder")

    @Slot()
    def browseVideoFile(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "Select video file",
            "",
            "Video files (*.mp4 *.mkv)",
        )
        if file_path:
            self.loadVideoFile(file_path)

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

    def _set_project_status(self, status: str):
        self._project_status = status
        self.projectStatusChanged.emit()

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

    def _default_export_output_path(self, input_path: str) -> str:
        source = Path(input_path)
        return str(source.with_name(f"{source.stem}_export{source.suffix}"))
