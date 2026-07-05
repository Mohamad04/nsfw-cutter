import logging
import math
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QThreadPool, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog

from controllers.app.app_state import AppState
from controllers.app.cut_normalizer import normalize_cut, parse_hh_mm_ss_to_seconds
from controllers.app.export_preparation_runner import (
    ExportPreparationCallbacks,
    ExportPreparationRunner,
)
from controllers.app.lossless_export_runner import ExportCallbacks, LosslessExportRunner
from controllers.app.video_loader import VideoLoader
from controllers.common.qt_state import clamp_percent
from core.job_registry import JobRegistry
from services.editing.keyframe_service import KeyframeService
from services.export.cut_json_service import CutJsonError, CutJsonService
from services.settings_service import SettingsService
from services.media.import_service import VideoImportService
from services.subtitles.processing_service import SubtitleService
from services.subtitles.selection_service import (
    OFF_SUBTITLE_OPTION_ID,
    analysis_subtitle_status_text,
    attach_candidate_ids,
    attach_player_subtitle_track_indexes,
    auto_select_analysis_subtitle_id,
    build_analysis_subtitle_options,
    find_selectable_candidate,
    preview_subtitle_track_index_for_selection,
)
from services.subtitles.subtitle_loader_service import load_subtitle_events, subtitle_text_at_position
from workers.keyframe_index_worker import KeyframeIndexWorker
from workers.prepare_export_job_worker import PrepareExportJobWorker
from workers.subtitle_discovery_worker import SubtitleDiscoveryWorker
from workers.video_export_worker import VideoExportWorker


logger = logging.getLogger(__name__)


def _path_exists(path_text: str) -> bool:
    if not path_text:
        return False

    try:
        return Path(path_text).expanduser().is_file()
    except OSError:
        return False


def _local_file_url(path_text: str) -> str:
    if not path_text:
        return ""

    return QUrl.fromLocalFile(str(Path(path_text).expanduser())).toString()


class AppController(QObject):
    DEFAULT_MAX_THREAD_COUNT = 2

    videoUrlChanged = Signal()
    videoNameChanged = Signal()
    subtitleStatusChanged = Signal()
    subtitleDetectionStateChanged = Signal()
    subtitleCandidatesChanged = Signal()
    subtitleErrorChanged = Signal()
    analysisSubtitleOptionsChanged = Signal()
    selectedAnalysisSubtitleChanged = Signal()
    activePreviewSubtitleTrackIndexChanged = Signal()
    previewSubtitleTextChanged = Signal()
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
    recentFilesChanged = Signal()
    keyframeStateChanged = Signal()
    keyframeErrorChanged = Signal()
    keyframeCountChanged = Signal()
    keyframeMediaPathChanged = Signal()
    aiAnalysisStateChanged = Signal()
    aiSuggestionsChanged = Signal()

    def __init__(
        self,
        video_import_service=None,
        thread_pool=None,
        job_registry=None,
        worker_factory=None,
        max_thread_count=None,
        prepare_worker_factory=None,
        settings_service=None,
        keyframe_service=None,
        keyframe_worker_factory=None,
        subtitle_service=None,
        subtitle_worker_factory=None,
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
        self.keyframe_service = keyframe_service or KeyframeService()
        self._keyframe_worker_factory = keyframe_worker_factory or KeyframeIndexWorker
        self._keyframe_workers = {}
        self.subtitle_service = (
            subtitle_service
            or getattr(self.video_import_service, "subtitle_service", None)
            or SubtitleService()
        )
        self._subtitle_worker_factory = subtitle_worker_factory or SubtitleDiscoveryWorker
        self._subtitle_workers = {}

        self._state = AppState()
        self._video_loader = VideoLoader(self.video_import_service, self.settings_service)
        self._cut_json_service = CutJsonService()
        self._lossless_export_runner = LosslessExportRunner(
            self._thread_pool,
            self._job_registry,
            self._worker_factory,
        )
        self._export_preparation_runner = ExportPreparationRunner(
            self._thread_pool,
            self._job_registry,
            self._prepare_worker_factory,
        )

    @Property(str, notify=videoUrlChanged)
    def videoUrl(self):
        return self._state.video_url

    @Property(str, notify=videoNameChanged)
    def videoName(self):
        return self._state.video_name

    @Property(str, notify=subtitleStatusChanged)
    def subtitleStatus(self):
        return self._state.subtitle_status

    @Property(str, notify=subtitleDetectionStateChanged)
    def subtitleDetectionState(self):
        return self._state.subtitle_detection_state

    @Property("QVariantList", notify=subtitleCandidatesChanged)
    def subtitleCandidates(self):
        return list(self._state.subtitle_candidates)

    @Property(str, notify=subtitleErrorChanged)
    def subtitleError(self):
        return self._state.subtitle_error

    @Property("QVariantList", notify=analysisSubtitleOptionsChanged)
    def analysisSubtitleOptions(self):
        return build_analysis_subtitle_options(
            self._state.subtitle_candidates,
            self._state.selected_analysis_subtitle_id,
            include_off=True,
        )

    @Property(str, notify=selectedAnalysisSubtitleChanged)
    def selectedAnalysisSubtitleId(self):
        return self._state.selected_analysis_subtitle_id

    @Property("QVariant", notify=selectedAnalysisSubtitleChanged)
    def selectedAnalysisSubtitle(self):
        return self._state.selected_analysis_subtitle or {}

    @Property(int, notify=activePreviewSubtitleTrackIndexChanged)
    def activePreviewSubtitleTrackIndex(self):
        return self._state.active_preview_subtitle_track_index

    @Property(str, notify=previewSubtitleTextChanged)
    def previewSubtitleText(self):
        return self._state.preview_subtitle_text

    @Property(str, notify=projectStatusChanged)
    def projectStatus(self):
        return self._state.project_status

    @Property(str, notify=currentFolderChanged)
    def currentFolder(self):
        return self._state.current_folder

    @Property("QVariantList", notify=availableVideosChanged)
    def availableVideos(self):
        return self._state.available_videos

    @Property(str, notify=selectedVideoPathChanged)
    def selectedVideoPath(self):
        return self._state.selected_video_path

    @Property("QVariantList", notify=recentFilesChanged)
    def recentFiles(self):
        return self._recent_file_items()

    @Property(bool, notify=exportBusyChanged)
    def exportBusy(self):
        return self._state.export_busy

    @Property(int, notify=exportProgressChanged)
    def exportProgress(self):
        return self._state.export_progress

    @Property(str, notify=exportStatusChanged)
    def exportStatus(self):
        return self._state.export_status

    @Property(bool, notify=backendPreparationBusyChanged)
    def backendPreparationBusy(self):
        return self._state.backend_preparation_busy

    @Property(int, notify=backendPreparationProgressChanged)
    def backendPreparationProgress(self):
        return self._state.backend_preparation_progress

    @Property(str, notify=backendPreparationStatusChanged)
    def backendPreparationStatus(self):
        return self._state.backend_preparation_status

    @Property(str, notify=currentExportJobIdChanged)
    def currentExportJobId(self):
        return self._state.current_export_job_id

    @Property(str, notify=currentExportJobJsonPathChanged)
    def currentExportJobJsonPath(self):
        return self._state.current_export_job_json_path

    @Property(str, notify=keyframeStateChanged)
    def keyframeState(self):
        return self.keyframe_service.keyframe_state

    @Property(str, notify=keyframeErrorChanged)
    def keyframeError(self):
        return self.keyframe_service.keyframe_error

    @Property(int, notify=keyframeCountChanged)
    def keyframeCount(self):
        return len(self.keyframe_service.keyframe_timestamps)

    @Property("QVariantList", notify=keyframeCountChanged)
    def keyframeTimestamps(self):
        return self.keyframe_service.keyframe_timestamps

    @Property(str, notify=keyframeMediaPathChanged)
    def keyframeMediaPath(self):
        return self.keyframe_service.active_media_path

    @Property(str, notify=aiAnalysisStateChanged)
    def aiAnalysisState(self):
        return self._state.ai_analysis_state

    @Property("QVariantList", notify=aiSuggestionsChanged)
    def aiSuggestions(self):
        return list(self._state.ai_suggestions)

    @Slot()
    def browseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select video folder")
        if folder:
            self.loadFolder(folder)

    @Slot()
    def openFile(self):
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "Open video file",
            "",
            self._video_file_filter(),
        )
        if file_path:
            self.loadVideoFile(file_path)

    @Slot()
    def openFiles(self):
        file_paths, _selected_filter = QFileDialog.getOpenFileNames(
            None,
            "Open video files",
            "",
            self._video_file_filter(),
        )
        if file_paths:
            self.loadVideoFiles(file_paths)

    @Slot(str)
    def loadFolder(self, folder: str):
        try:
            self._set_current_folder(folder)
            videos = self._video_loader.list_folder_videos(folder)
            self._set_available_videos(videos)

            if not videos:
                self._set_project_status("No video found in selected folder")
                return

            self._set_project_status(f"{len(videos)} video(s) found. Select one to load.")
        except ValueError as exc:
            self._set_current_folder("")
            self._set_available_videos([])
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while loading folder")
            self._set_current_folder("")
            self._set_available_videos([])
            self._set_project_status("Unexpected error while loading folder")

    @Slot(str)
    def loadVideoFile(self, file_path: str):
        self._load_video_file(file_path)

    @Slot(str, str, str, str, str, str)
    def logPlaybackState(
        self,
        player_name: str,
        event_name: str,
        source: str,
        media_status: str,
        error: str,
        error_string: str,
    ):
        error_string = error_string or ""
        log_method = logger.warning if error_string else logger.info
        log_method(
            "[Playback][%s] %s source=%s mediaStatus=%s error=%s errorString=%s",
            player_name,
            event_name,
            source,
            media_status,
            error,
            error_string,
        )

    @Slot("QVariantList")
    def loadVideoFiles(self, file_paths):
        valid_videos = []
        skipped = 0
        for file_path in file_paths or []:
            try:
                video = self.video_import_service.build_video_listing_for_file(file_path)
            except ValueError:
                skipped += 1
                continue

            if not any(existing["path"] == video["path"] for existing in valid_videos):
                valid_videos.append(video)

        if not valid_videos:
            self._set_project_status("No supported videos selected.")
            return

        self._append_available_videos(valid_videos)
        self._set_current_folder("Selected files")
        self.settings_service.add_recent_videos([video["path"] for video in valid_videos])
        self.recentFilesChanged.emit()

        loaded = self._load_video_file(valid_videos[0]["path"])
        if not loaded:
            return

        if skipped:
            self._set_project_status(
                f"Loaded {len(valid_videos)} video(s); skipped {skipped} unsupported or missing file(s)."
            )
        elif len(valid_videos) > 1:
            self._set_project_status(f"Loaded {len(valid_videos)} selected video(s).")

    def _load_video_file(self, file_path: str) -> bool:
        try:
            result = self._video_loader.import_video_file(file_path)
            self._apply_loaded_video(result)
            return True
        except ValueError as exc:
            self._set_project_status(str(exc))
            return False
        except Exception:
            logger.exception("Unexpected error while loading video")
            self._set_project_status("Unexpected error while loading video")
            return False

    @Slot(str)
    def openRecentFile(self, file_path: str):
        if not file_path:
            return

        video_path = Path(file_path).expanduser()
        if not video_path.is_file():
            self.settings_service.remove_recent_video(video_path)
            self.recentFilesChanged.emit()
            self._set_project_status("Recent file no longer exists.")
            return

        self.loadVideoFile(str(video_path))

    @Slot(result="QVariantList")
    def refreshRecentFiles(self):
        _settings, changed = self.settings_service.prune_missing_recent_videos()
        if changed:
            self.recentFilesChanged.emit()
        return self.recentFiles

    @Slot()
    def clearRecentFiles(self):
        self.settings_service.clear_recent_videos()
        self.recentFilesChanged.emit()

    @Slot()
    def restoreLastVideo(self):
        last_video = self._video_loader.get_last_video()
        if last_video:
            self.loadVideoFile(str(last_video))

    @Slot(int)
    def selectAvailableVideo(self, index: int):
        try:
            if index < 0 or index >= len(self._state.available_videos):
                raise ValueError("Invalid video selection")

            self.loadVideoFile(self._state.available_videos[index]["path"])
        except ValueError as exc:
            self._set_project_status(str(exc))
        except Exception:
            logger.exception("Unexpected error while selecting video")
            self._set_project_status("Unexpected error while selecting video")

    @Slot()
    def clearVideo(self):
        self._state.video_url = ""
        self._state.video_name = "No video selected"
        self._clear_subtitle_discovery()
        self._clear_ai_suggestions()
        self._state.project_status = "Ready"
        self._state.selected_video_path = ""
        self.keyframe_service.clear_active_media()

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.projectStatusChanged.emit()
        self.selectedVideoPathChanged.emit()
        self._emit_keyframe_state_changed()

    @Slot(str, result=bool)
    def selectAnalysisSubtitle(self, candidate_id: str) -> bool:
        if candidate_id == OFF_SUBTITLE_OPTION_ID:
            self._state.selected_analysis_subtitle_id = OFF_SUBTITLE_OPTION_ID
            self._state.selected_analysis_subtitle = None
            self._state.analysis_subtitle_auto_selected = False
            self._state.subtitle_status = analysis_subtitle_status_text(
                self._state.subtitle_candidates,
                self._state.selected_analysis_subtitle_id,
            )
            self._set_active_preview_subtitle_track_index(-1)
            self._clear_preview_subtitle_overlay()
            logger.info("[Subtitles] Preview subtitles disabled")
            self._emit_subtitle_state_changed()
            return True

        candidate = find_selectable_candidate(self._state.subtitle_candidates, candidate_id)
        if candidate is None:
            logger.info("[Subtitles] Analysis selection rejected: candidate is not text-readable")
            return False

        self._state.selected_analysis_subtitle_id = candidate["candidate_id"]
        self._state.selected_analysis_subtitle = candidate
        self._state.analysis_subtitle_auto_selected = False
        self._state.subtitle_status = analysis_subtitle_status_text(
            self._state.subtitle_candidates,
            self._state.selected_analysis_subtitle_id,
        )
        self._apply_preview_subtitle_selection(candidate)
        logger.info(
            "[Subtitles] Analysis subtitle selected: source=%s, language=%s, id=%s",
            candidate.get("source"),
            candidate.get("language_name") or candidate.get("language_code") or "unknown",
            candidate.get("candidate_id"),
        )
        self._emit_subtitle_state_changed()
        return True

    @Slot(int)
    def updatePlayerSubtitleTrackCount(self, track_count: int) -> None:
        normalized_count = max(0, int(track_count))
        if self._state.player_subtitle_track_count == normalized_count:
            return

        logger.info("[Subtitles] Qt player subtitle tracks reported: count=%s", normalized_count)
        self._state.player_subtitle_track_count = normalized_count
        self._state.subtitle_candidates = attach_player_subtitle_track_indexes(
            self._state.subtitle_candidates,
            normalized_count,
        )
        if (
            self._state.selected_analysis_subtitle_id
            and self._state.selected_analysis_subtitle_id != OFF_SUBTITLE_OPTION_ID
        ):
            self._state.selected_analysis_subtitle = find_selectable_candidate(
                self._state.subtitle_candidates,
                self._state.selected_analysis_subtitle_id,
            )
        self._refresh_active_preview_subtitle_track()
        self._emit_subtitle_state_changed()

    @Slot(int)
    @Slot(float)
    def updatePreviewSubtitlePosition(self, position_ms) -> None:
        if not self._state.preview_subtitle_cues:
            self._set_preview_subtitle_text("")
            return

        text = subtitle_text_at_position(
            self._state.preview_subtitle_cues,
            max(0, int(position_ms)),
        )
        self._set_preview_subtitle_text(text)

    @Slot()
    @Slot(str, str)
    def startLosslessExport(self, input_path: str = "", output_path: str = ""):
        input_path = input_path or self._state.selected_video_path
        if not input_path:
            self._set_export_status("Select a video before exporting.")
            return

        output_path = output_path or self._default_export_output_path(input_path)
        self._lossless_export_runner.start(
            input_path,
            output_path,
            ExportCallbacks(
                on_busy=self._set_export_busy,
                on_progress=self._set_export_progress,
                on_status=self._set_export_status,
            ),
        )

    @Slot(str, str)
    def prepareExportJob(self, video_path: str, output_path: str = ""):
        video_path = video_path or self._state.selected_video_path
        if not video_path:
            self._set_backend_preparation_status("Select a video before preparing export.")
            return

        self._export_preparation_runner.start(
            video_path,
            output_path,
            ExportPreparationCallbacks(
                on_busy=self._set_backend_preparation_busy,
                on_progress=self._set_backend_preparation_progress,
                on_status=self._set_backend_preparation_status,
                on_job_id=self._set_current_export_job_id,
                on_json_path=self._set_current_export_job_json_path,
            ),
        )

    @Slot("QVariantList")
    def exportCuts(self, cuts):
        self.getCutsJsonText(cuts, 0.0)

    @Slot("QVariantList", result=str)
    @Slot("QVariantList", float, result=str)
    def exportCutsJson(self, cuts, duration_seconds: float = 0.0):
        return self.getCutsJsonText(cuts, duration_seconds)

    @Slot("QVariantList", result=str)
    @Slot("QVariantList", float, result=str)
    def getCutsJsonText(self, cuts, duration_seconds: float = 0.0):
        if not cuts:
            self._set_project_status(QCoreApplication.translate("AppController", "No cuts to export"))
            return ""

        try:
            return self._cut_json_service.export_to_text(
                cuts=cuts,
                video_filename=Path(self._state.selected_video_path).name or self._state.video_name,
                video_duration_seconds=duration_seconds,
            )
        except CutJsonError as exc:
            if exc.code == CutJsonService.NO_CUTS:
                message = QCoreApplication.translate("AppController", "No cuts to export")
            else:
                message = QCoreApplication.translate("AppController", "Could not export cuts")
                logger.info("Unable to export cuts JSON text: %s", exc.detail or exc)
            self._set_project_status(message)
            return ""
        except Exception:
            logger.exception("Unexpected error while generating cuts JSON")
            self._set_project_status(QCoreApplication.translate("AppController", "Could not export cuts"))
            return ""

    @Slot(result="QVariantList")
    def importCuts(self):
        result = self.importCutsJson(0.0)
        if not result.get("accepted"):
            return []
        return result.get("cuts", [])

    @Slot(result="QVariantMap")
    @Slot(float, result="QVariantMap")
    def importCutsJson(self, duration_seconds: float = 0.0):
        message = QCoreApplication.translate("AppController", "Could not import cuts")
        self._set_project_status(message)
        return {"accepted": False, "cuts": [], "error": message}

    @Slot(str, result="QVariantMap")
    @Slot(str, float, result="QVariantMap")
    def importCutsJsonText(self, json_text: str, duration_seconds: float = 0.0):
        try:
            cuts = self._cut_json_service.import_from_text(
                json_text,
                video_duration_seconds=duration_seconds,
            )
            message = QCoreApplication.translate("AppController", "Cuts imported successfully")
            self._set_project_status(message)
            return {"accepted": True, "cuts": cuts, "error": ""}
        except CutJsonError as exc:
            logger.info("Unable to import cuts JSON text: %s", exc.detail or exc)
            if exc.code == CutJsonService.INVALID_JSON:
                message = QCoreApplication.translate("AppController", "Invalid JSON content")
            else:
                message = QCoreApplication.translate("AppController", "Could not import cuts")
            self._set_project_status(message)
            return {"accepted": False, "cuts": [], "error": message}
        except Exception:
            logger.exception("Unexpected error while importing cuts JSON text")
            message = QCoreApplication.translate("AppController", "Could not import cuts")
            self._set_project_status(message)
            return {"accepted": False, "cuts": [], "error": message}

    @Slot(str, result=bool)
    def copyTextToClipboard(self, text: str):
        if not str(text or "").strip():
            return False

        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False

        clipboard.setText(str(text))
        return True

    def exportCutsToPath(self, cuts, file_path: str, duration_seconds: float = 0.0):
        count, output_path = self._cut_json_service.export_to_path(
            cuts=cuts,
            file_path=file_path,
            video_filename=Path(self._state.selected_video_path).name or self._state.video_name,
            video_duration_seconds=duration_seconds,
        )
        return count, output_path

    def importCutsFromPath(self, file_path: str, duration_seconds: float = 0.0):
        normalized_cuts, input_path = self._cut_json_service.import_from_path(
            file_path,
            video_duration_seconds=duration_seconds,
        )
        message = QCoreApplication.translate("AppController", "Cuts imported successfully")
        self._set_project_status(f"{message}: {input_path.name}")
        return normalized_cuts

    @Slot(str, int, str)
    def _on_export_progress(self, job_key: str, percentage: int, message: str):
        self._lossless_export_runner.handle_progress(job_key, percentage, message)

    @Slot(str, object)
    def _on_export_finished(self, job_key: str, result):
        self._lossless_export_runner.handle_finished(job_key, result)

    @Slot(str, str)
    def _on_export_error(self, job_key: str, error_message: str):
        self._lossless_export_runner.handle_error(job_key, error_message)

    @Slot(str, int, str)
    def _on_backend_preparation_progress(self, job_key: str, percentage: int, message: str):
        self._export_preparation_runner.handle_progress(job_key, percentage, message)

    @Slot(str, object)
    def _on_backend_preparation_finished(self, job_key: str, result):
        self._export_preparation_runner.handle_finished(job_key, result)

    @Slot(str, str)
    def _on_backend_preparation_error(self, job_key: str, error_message: str):
        self._export_preparation_runner.handle_error(job_key, error_message)

    def _apply_loaded_video(self, result: dict):
        selected_video_path = result.get("video_path", "")
        converted_video_url = (
            _local_file_url(selected_video_path)
            if selected_video_path
            else result.get("video_url", "")
        )
        file_exists = _path_exists(selected_video_path)

        logger.info(
            "[Playback] Selected raw path=%s converted_url=%s exists=%s",
            selected_video_path,
            converted_video_url,
            file_exists,
        )

        self._state.video_url = converted_video_url
        self._state.video_name = result.get("video_name", "No video selected")
        self._state.selected_video_path = selected_video_path
        self._state.project_status = result.get("status", "Video loaded")
        self._clear_ai_suggestions()

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.projectStatusChanged.emit()
        self.selectedVideoPathChanged.emit()

        if self._state.selected_video_path:
            self._start_keyframe_indexing(self._state.selected_video_path)
            self._start_subtitle_discovery(self._state.selected_video_path)
        else:
            self._clear_subtitle_discovery()

        if self._state.selected_video_path:
            try:
                self._video_loader.save_last_video(self._state.selected_video_path)
                self.recentFilesChanged.emit()
            except OSError:
                logger.exception("Unable to persist last opened video")

    def _start_keyframe_indexing(self, input_path: str) -> bool:
        logger.info(
            "[Keyframes] Video loaded; scheduling background indexing: %s",
            input_path,
        )
        request = self.keyframe_service.request_indexing(input_path)
        self._emit_keyframe_state_changed()
        if request is None:
            return False

        try:
            worker = self._keyframe_worker_factory(
                job_token=request.job_token,
                input_path=request.media_path,
                keyframe_service=self.keyframe_service,
            )
            self._keyframe_workers[request.job_token] = worker
            worker.signals.finished.connect(self._on_keyframe_indexing_finished)
            worker.signals.error.connect(self._on_keyframe_indexing_error)
            self._thread_pool.start(worker)
        except Exception as exc:
            self._keyframe_workers.pop(request.job_token, None)
            self.keyframe_service.fail_indexing(
                request.media_path,
                request.job_token,
                str(exc),
            )
            self._emit_keyframe_state_changed()
            logger.exception("[Keyframes] Unable to start background indexing worker")
            return False
        return True

    def _start_subtitle_discovery(self, input_path: str) -> bool:
        media_path = _resolved_media_path(input_path)
        if (
            self._state.subtitle_detection_state == "loading"
            and self._state.subtitle_active_media_path == media_path
        ):
            logger.info("[Subtitles] Duplicate discovery ignored; already loading: %s", media_path)
            return False

        job_token = uuid.uuid4().hex
        self._state.subtitle_detection_state = "loading"
        self._state.subtitle_status = "Subtitle: Detecting..."
        self._state.subtitle_candidates = []
        self._state.subtitle_error = ""
        self._state.player_subtitle_track_count = 0
        self._set_active_preview_subtitle_track_index(-1)
        self._clear_analysis_subtitle_selection()
        self._clear_preview_subtitle_overlay()
        self._state.subtitle_active_job_token = job_token
        self._state.subtitle_active_media_path = media_path
        self._emit_subtitle_state_changed()

        try:
            worker = self._subtitle_worker_factory(
                job_token=job_token,
                input_path=media_path,
                subtitle_service=self.subtitle_service,
            )
            self._subtitle_workers[job_token] = worker
            worker.signals.finished.connect(self._on_subtitle_discovery_finished)
            worker.signals.error.connect(self._on_subtitle_discovery_error)
            self._thread_pool.start(worker)
        except Exception as exc:
            self._subtitle_workers.pop(job_token, None)
            self._apply_subtitle_discovery_error(media_path, job_token, str(exc))
            logger.exception("[Subtitles] Unable to start background discovery worker")
            return False
        return True

    @Slot(str, object)
    def _on_subtitle_discovery_finished(self, job_token: str, result) -> None:
        worker = self._subtitle_workers.pop(job_token, None)
        input_path = result.get("input_path", "") if isinstance(result, dict) else ""
        if not input_path and worker is not None:
            input_path = worker.input_path
        if not input_path:
            logger.info("[Subtitles] Ignoring result without media path: job=%s", job_token)
            return

        media_path = _resolved_media_path(input_path)
        if not self._is_active_subtitle_job(media_path, job_token):
            logger.info("[Subtitles] Ignoring stale discovery result: %s", media_path)
            return

        candidates = result.get("candidates", []) if isinstance(result, dict) else []
        if not isinstance(candidates, list):
            candidates = []

        prepared_candidates = attach_player_subtitle_track_indexes(
            attach_candidate_ids(media_path, candidates),
            self._state.player_subtitle_track_count,
        )
        selected_id = auto_select_analysis_subtitle_id(prepared_candidates)
        selected_candidate = (
            find_selectable_candidate(prepared_candidates, selected_id)
            if selected_id
            else None
        )

        self._state.subtitle_detection_state = "ready"
        self._state.subtitle_candidates = prepared_candidates
        self._state.subtitle_error = ""
        self._state.selected_analysis_subtitle_id = selected_id or ""
        self._state.selected_analysis_subtitle = selected_candidate
        self._state.analysis_subtitle_auto_selected = selected_candidate is not None
        self._state.subtitle_status = analysis_subtitle_status_text(
            prepared_candidates,
            self._state.selected_analysis_subtitle_id,
            auto_selected=self._state.analysis_subtitle_auto_selected,
        )
        self._state.subtitle_active_job_token = ""
        if selected_candidate is not None:
            self._apply_preview_subtitle_selection(selected_candidate)
        else:
            self._clear_preview_subtitle_overlay()
            self._refresh_active_preview_subtitle_track()
        if selected_candidate is not None:
            logger.info(
                "[Subtitles] Analysis subtitle auto-selected: source=%s, language=%s, id=%s",
                selected_candidate.get("source"),
                selected_candidate.get("language_name")
                or selected_candidate.get("language_code")
                or "unknown",
                selected_candidate.get("candidate_id"),
            )
        self._emit_subtitle_state_changed()

    @Slot(str, str)
    def _on_subtitle_discovery_error(self, job_token: str, error_message: str) -> None:
        worker = self._subtitle_workers.pop(job_token, None)
        if worker is None:
            logger.info("[Subtitles] Ignoring failure for unknown job: %s", job_token)
            return

        media_path = _resolved_media_path(worker.input_path)
        self._apply_subtitle_discovery_error(media_path, job_token, error_message)

    def _apply_subtitle_discovery_error(
        self,
        media_path: str,
        job_token: str,
        error_message: str,
    ) -> bool:
        if not self._is_active_subtitle_job(media_path, job_token):
            logger.info("[Subtitles] Ignoring stale discovery failure: %s", media_path)
            return False

        self._state.subtitle_detection_state = "error"
        self._state.subtitle_candidates = []
        self._state.subtitle_error = str(error_message)
        self._state.subtitle_status = "Subtitle: Detection error"
        self._state.subtitle_active_job_token = ""
        self._clear_analysis_subtitle_selection()
        self._clear_preview_subtitle_overlay()
        self._emit_subtitle_state_changed()
        return True

    def _apply_preview_subtitle_selection(self, candidate: dict) -> None:
        if candidate.get("source") == "external":
            self._set_active_preview_subtitle_track_index(-1)
            self._load_external_preview_subtitle(candidate)
            return

        self._clear_preview_subtitle_overlay()
        self._refresh_active_preview_subtitle_track()

    def _load_external_preview_subtitle(self, candidate: dict) -> None:
        subtitle_path = candidate.get("file_path") or candidate.get("path") or ""
        if not subtitle_path:
            logger.info(
                "[Subtitles] Cannot render selected external subtitle without file path: id=%s",
                candidate.get("candidate_id"),
            )
            self._clear_preview_subtitle_overlay()
            return

        if not candidate.get("is_text_readable"):
            logger.info(
                "[Subtitles] External subtitle preview requires a text-readable subtitle: id=%s, path=%s",
                candidate.get("candidate_id"),
                subtitle_path,
            )
            self._clear_preview_subtitle_overlay()
            return

        try:
            cues = load_subtitle_events(subtitle_path)
        except Exception:
            logger.exception("[Subtitles] Unable to load external subtitle preview: %s", subtitle_path)
            self._clear_preview_subtitle_overlay()
            return

        self._state.preview_subtitle_cues = cues
        self._state.preview_subtitle_candidate_id = candidate.get("candidate_id", "")
        self._set_preview_subtitle_text("")
        logger.info(
            "[Subtitles] Activating external subtitle overlay: language=%s, cues=%s, path=%s",
            candidate.get("language_name") or candidate.get("language_code") or "unknown",
            len(cues),
            subtitle_path,
        )

    def _refresh_active_preview_subtitle_track(self) -> None:
        track_index = preview_subtitle_track_index_for_selection(
            self._state.subtitle_candidates,
            self._state.selected_analysis_subtitle_id,
        )
        selected_candidate = self._state.selected_analysis_subtitle or {}
        if selected_candidate.get("source") == "embedded" and track_index >= 0:
            logger.info(
                "[Subtitles] Activating preview embedded subtitle: language=%s, qt_track_index=%s",
                selected_candidate.get("language_name")
                or selected_candidate.get("language_code")
                or "unknown",
                track_index,
            )
        elif selected_candidate.get("source") == "embedded":
            logger.info(
                "[Subtitles] Unable to map embedded candidate to Qt subtitle track: id=%s, "
                "qt_track_count=%s",
                selected_candidate.get("candidate_id"),
                self._state.player_subtitle_track_count,
            )
        self._set_active_preview_subtitle_track_index(track_index)

    def _set_active_preview_subtitle_track_index(self, track_index: int) -> None:
        normalized_index = int(track_index)
        if self._state.active_preview_subtitle_track_index != normalized_index:
            self._state.active_preview_subtitle_track_index = normalized_index
            self.activePreviewSubtitleTrackIndexChanged.emit()

    def _clear_preview_subtitle_overlay(self) -> None:
        self._state.preview_subtitle_cues = []
        self._state.preview_subtitle_candidate_id = ""
        self._set_preview_subtitle_text("")

    def _set_preview_subtitle_text(self, text: str) -> None:
        normalized_text = str(text or "")
        if self._state.preview_subtitle_text != normalized_text:
            self._state.preview_subtitle_text = normalized_text
            self.previewSubtitleTextChanged.emit()

    def _is_active_subtitle_job(self, media_path: str, job_token: str) -> bool:
        return (
            self._state.subtitle_active_media_path == media_path
            and self._state.subtitle_active_job_token == job_token
        )

    def _clear_subtitle_discovery(self) -> None:
        self._state.subtitle_status = "Subtitle: Not detected"
        self._state.subtitle_detection_state = "idle"
        self._state.subtitle_candidates = []
        self._state.subtitle_error = ""
        self._state.subtitle_active_job_token = ""
        self._state.subtitle_active_media_path = ""
        self._state.player_subtitle_track_count = 0
        self._set_active_preview_subtitle_track_index(-1)
        self._clear_analysis_subtitle_selection()
        self._clear_preview_subtitle_overlay()
        self._emit_subtitle_state_changed()

    def _clear_analysis_subtitle_selection(self) -> None:
        if self._state.selected_analysis_subtitle_id:
            logger.info("[Subtitles] Analysis subtitle cleared for newly loaded media")
        self._state.selected_analysis_subtitle_id = ""
        self._state.selected_analysis_subtitle = None
        self._state.analysis_subtitle_auto_selected = False

    @Slot("QVariantList")
    def setAiSuggestions(self, suggestions) -> None:
        normalized_suggestions = []
        for suggestion in suggestions or []:
            normalized = _normalize_ai_suggestion(suggestion)
            if normalized is not None:
                normalized_suggestions.append(normalized)

        self._state.ai_suggestions = normalized_suggestions
        self._state.ai_analysis_state = "ready"
        self.aiSuggestionsChanged.emit()
        self.aiAnalysisStateChanged.emit()

    def _clear_ai_suggestions(self) -> None:
        changed_suggestions = bool(self._state.ai_suggestions)
        changed_state = self._state.ai_analysis_state != "idle"
        self._state.ai_suggestions = []
        self._state.ai_analysis_state = "idle"
        if changed_suggestions:
            self.aiSuggestionsChanged.emit()
        if changed_state:
            self.aiAnalysisStateChanged.emit()

    @Slot(str, object)
    def _on_keyframe_indexing_finished(self, job_token: str, result) -> None:
        worker = self._keyframe_workers.pop(job_token, None)
        input_path = result.get("input_path", "") if isinstance(result, dict) else ""
        if not input_path and worker is not None:
            input_path = worker.input_path
        if not input_path:
            logger.info("[Keyframes] Ignoring result without media path: job=%s", job_token)
            return

        applied = self.keyframe_service.complete_indexing(
            input_path,
            job_token,
            result.get("keyframes", []) if isinstance(result, dict) else [],
            result.get("elapsed_seconds") if isinstance(result, dict) else None,
        )
        if applied:
            self._emit_keyframe_state_changed()

    @Slot(str, str)
    def _on_keyframe_indexing_error(self, job_token: str, error_message: str) -> None:
        worker = self._keyframe_workers.pop(job_token, None)
        if worker is None:
            logger.info("[Keyframes] Ignoring failure for unknown job: %s", job_token)
            return

        applied = self.keyframe_service.fail_indexing(
            worker.input_path,
            job_token,
            error_message,
        )
        if applied:
            self._emit_keyframe_state_changed()

    def _emit_keyframe_state_changed(self) -> None:
        self.keyframeStateChanged.emit()
        self.keyframeErrorChanged.emit()
        self.keyframeCountChanged.emit()
        self.keyframeMediaPathChanged.emit()

    def _emit_subtitle_state_changed(self) -> None:
        self.subtitleStatusChanged.emit()
        self.subtitleDetectionStateChanged.emit()
        self.subtitleCandidatesChanged.emit()
        self.subtitleErrorChanged.emit()
        self.analysisSubtitleOptionsChanged.emit()
        self.selectedAnalysisSubtitleChanged.emit()
        self.activePreviewSubtitleTrackIndexChanged.emit()

    def _append_available_videos(self, videos: list[dict]):
        existing_paths = {video.get("path") for video in self._state.available_videos}
        merged = list(self._state.available_videos)
        for video in videos:
            if video["path"] not in existing_paths:
                merged.append(video)
                existing_paths.add(video["path"])

        if merged != self._state.available_videos:
            self._set_available_videos(merged)

    def _recent_file_items(self) -> list[dict]:
        settings = self.settings_service.load()
        return [
            {
                "name": path.name,
                "path": str(path),
            }
            for path in settings.recent_videos
        ]

    def _video_file_filter(self) -> str:
        discovery_service = getattr(self.video_import_service, "video_discovery_service", None)
        extensions = getattr(discovery_service, "VIDEO_EXTENSIONS", {".mkv", ".mp4"})
        patterns = " ".join(f"*{extension}" for extension in sorted(extensions))
        return f"Video files ({patterns})"

    def _set_project_status(self, status: str):
        self._state.project_status = status
        self.projectStatusChanged.emit()

    def _set_current_folder(self, folder: str):
        if self._state.current_folder != folder:
            self._state.current_folder = folder
            self.currentFolderChanged.emit()

    def _set_available_videos(self, videos):
        self._state.available_videos = videos
        self.availableVideosChanged.emit()

    def _set_export_busy(self, value: bool):
        if self._state.export_busy != value:
            self._state.export_busy = value
            self.exportBusyChanged.emit()

    def _set_export_progress(self, value: int):
        value = clamp_percent(value)
        if self._state.export_progress != value:
            self._state.export_progress = value
            self.exportProgressChanged.emit()

    def _set_export_status(self, value: str):
        if self._state.export_status != value:
            self._state.export_status = value
            self.exportStatusChanged.emit()

    def _set_backend_preparation_busy(self, value: bool):
        if self._state.backend_preparation_busy != value:
            self._state.backend_preparation_busy = value
            self.backendPreparationBusyChanged.emit()

    def _set_backend_preparation_progress(self, value: int):
        value = clamp_percent(value)
        if self._state.backend_preparation_progress != value:
            self._state.backend_preparation_progress = value
            self.backendPreparationProgressChanged.emit()

    def _set_backend_preparation_status(self, value: str):
        if self._state.backend_preparation_status != value:
            self._state.backend_preparation_status = value
            self.backendPreparationStatusChanged.emit()

    def _set_current_export_job_id(self, value: str):
        if self._state.current_export_job_id != value:
            self._state.current_export_job_id = value
            self.currentExportJobIdChanged.emit()

    def _set_current_export_job_json_path(self, value: str):
        if self._state.current_export_job_json_path != value:
            self._state.current_export_job_json_path = value
            self.currentExportJobJsonPathChanged.emit()

    def _default_export_output_path(self, input_path: str) -> str:
        source = Path(input_path)
        return str(source.with_name(f"{source.stem}_export{source.suffix}"))

    def _normalize_cut(self, cut):
        return normalize_cut(cut)

    def _parse_time_to_seconds(self, value: str) -> int:
        return parse_hh_mm_ss_to_seconds(value)


def _resolved_media_path(media_path: str | Path) -> str:
    return str(Path(media_path).expanduser().resolve())


def _normalize_ai_suggestion(suggestion) -> dict | None:
    if not isinstance(suggestion, dict):
        return None

    start = _ai_suggestion_time_value(
        suggestion,
        "start",
        "start_time",
        "startTime",
        "start_seconds",
        "startSeconds",
    )
    end = _ai_suggestion_time_value(
        suggestion,
        "end",
        "end_time",
        "endTime",
        "end_seconds",
        "endSeconds",
    )
    if not start or not end:
        return None

    return {
        "start": start,
        "end": end,
        "confidence": _normalize_ai_confidence(suggestion.get("confidence")),
        "reason": str(suggestion.get("reason") or "").strip(),
    }


def _ai_suggestion_time_value(suggestion: dict, *keys: str) -> str:
    for key in keys:
        if key not in suggestion:
            continue
        value = suggestion.get(key)
        formatted = _format_ai_time(value)
        if formatted:
            return formatted
    return ""


def _format_ai_time(value) -> str:
    if value is None:
        return ""

    if isinstance(value, (int, float)):
        return _format_seconds_to_hhmmss_millis(float(value))

    text = str(value).strip()
    if not text:
        return ""

    if ":" in text:
        return _normalize_hhmmss_millis(text)

    try:
        return _format_seconds_to_hhmmss_millis(float(text))
    except ValueError:
        return ""


def _normalize_hhmmss_millis(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) != 3:
        return ""

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return ""

    if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds >= 60:
        return ""

    total_seconds = hours * 3600 + minutes * 60 + seconds
    return _format_seconds_to_hhmmss_millis(total_seconds)


def _format_seconds_to_hhmmss_millis(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return ""

    total_milliseconds = int(round(seconds * 1000))
    total_seconds = total_milliseconds // 1000
    milliseconds = total_milliseconds % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    whole_seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _normalize_ai_confidence(value) -> str:
    if isinstance(value, (int, float)):
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            return "Medium"
        if numeric_value >= 0.8:
            return "High"
        if numeric_value >= 0.5:
            return "Medium"
        return "Low"

    text = str(value or "").strip().lower()
    if text == "high":
        return "High"
    if text == "medium":
        return "Medium"
    if text == "low":
        return "Low"
    return "Medium"
