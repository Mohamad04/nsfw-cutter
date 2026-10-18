import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Property, QMetaObject, QObject, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication


class FakeAppController(QObject):
    selectedVideoPathChanged = Signal()
    aiSuggestionsChanged = Signal()
    subtitleCandidatesChanged = Signal()
    aiModelsReadyChanged = Signal()
    aiModelSetupStateChanged = Signal()
    aiModelSetupProgressChanged = Signal()
    aiModelSetupStatusChanged = Signal()
    aiModelSetupErrorChanged = Signal()
    aiModelSetupComponentChanged = Signal()
    videoLoadErrorChanged = Signal()
    videoLoadingChanged = Signal()

    def __init__(self):
        super().__init__()
        self._selected_video_path = ""
        self._video_load_error = ""
        self._video_loading_name = ""
        self.video_load_cancellations = 0
        self._ai_models_ready = True
        self._ai_model_setup_state = "ready"
        self._ai_model_setup_progress = 3
        self._ai_model_setup_status = "AI models are ready"
        self._ai_model_setup_error = ""
        self._ai_model_setup_component = ""
        self.model_status_refreshes = 0
        self.model_downloads = 0
        self.model_retries = 0
        self.model_cancellations = 0
        self.open_file_requests = 0

    @Property(str, notify=selectedVideoPathChanged)
    def selectedVideoPath(self):
        return self._selected_video_path

    @Property(str, constant=True)
    def videoName(self):
        return ""

    @Property(str, constant=True)
    def videoUrl(self):
        return ""

    @Property(str, constant=True)
    def currentFolder(self):
        return ""

    @Property(str, constant=True)
    def projectStatus(self):
        return "Ready"

    @Property(str, notify=videoLoadErrorChanged)
    def videoLoadError(self):
        return self._video_load_error

    @Slot()
    def dismissVideoLoadError(self):
        self.set_video_load_error("")

    @Property(bool, notify=videoLoadingChanged)
    def videoLoading(self):
        return bool(self._video_loading_name)

    @Property(str, notify=videoLoadingChanged)
    def videoLoadingName(self):
        return self._video_loading_name

    @Slot()
    def cancelVideoLoad(self):
        self.video_load_cancellations += 1
        self.set_video_loading("")

    def set_video_loading(self, name: str):
        self._video_loading_name = name
        self.videoLoadingChanged.emit()

    def set_video_load_error(self, message: str):
        self._video_load_error = message
        self.videoLoadErrorChanged.emit()

    @Property(str, constant=True)
    def subtitleDetectionState(self):
        return "idle"

    @Property(str, constant=True)
    def previewSubtitleText(self):
        return ""

    @Property(int, constant=True)
    def activePreviewSubtitleTrackIndex(self):
        return -1

    @Property("QVariantList", constant=True)
    def availableVideos(self):
        return []

    @Property("QVariantList", constant=True)
    def recentFiles(self):
        return []

    @Property("QVariantList", constant=True)
    def subtitleCandidates(self):
        return []

    @Property("QVariantList", constant=True)
    def analysisSubtitleOptions(self):
        return []

    @Property("QVariantList", notify=aiSuggestionsChanged)
    def aiSuggestions(self):
        return []

    @Property(str, constant=True)
    def aiAnalysisState(self):
        return "idle"

    @Property(int, constant=True)
    def aiAnalysisProgress(self):
        return 0

    @Property(str, constant=True)
    def aiAnalysisStatus(self):
        return "No analysis running"

    @Property(str, constant=True)
    def aiAnalysisError(self):
        return ""

    @Property("QVariantMap", constant=True)
    def aiAnalysisDetails(self):
        return {}

    @Property(bool, notify=aiModelsReadyChanged)
    def aiModelsReady(self):
        return self._ai_models_ready

    @Property(str, notify=aiModelSetupStateChanged)
    def aiModelSetupState(self):
        return self._ai_model_setup_state

    @Property(int, notify=aiModelSetupProgressChanged)
    def aiModelSetupProgress(self):
        return self._ai_model_setup_progress

    @Property(int, constant=True)
    def aiModelSetupTotal(self):
        return 3

    @Property(str, notify=aiModelSetupStatusChanged)
    def aiModelSetupStatus(self):
        return self._ai_model_setup_status

    @Property(str, notify=aiModelSetupErrorChanged)
    def aiModelSetupError(self):
        return self._ai_model_setup_error

    @Property(str, notify=aiModelSetupComponentChanged)
    def aiModelSetupComponent(self):
        return self._ai_model_setup_component

    @Slot(result=bool)
    def refreshAiModelStatus(self):
        self.model_status_refreshes += 1
        return True

    @Slot(result=bool)
    def downloadAiModels(self):
        self.model_downloads += 1
        return True

    @Slot(result=bool)
    def retryAiModelDownload(self):
        self.model_retries += 1
        return True

    @Slot(result=bool)
    def cancelAiModelDownload(self):
        self.model_cancellations += 1
        return True

    @Slot()
    def openFile(self):
        self.open_file_requests += 1

    @Slot(result=bool)
    def analyzeVideo(self):
        return self._ai_models_ready

    @Slot(result=bool)
    def cancelVideoAnalysis(self):
        return True

    def set_ai_model_setup(
        self,
        state,
        *,
        ready=False,
        progress=0,
        status="",
        error="",
        component="",
    ):
        self._ai_models_ready = ready
        self._ai_model_setup_state = state
        self._ai_model_setup_progress = progress
        self._ai_model_setup_status = status
        self._ai_model_setup_error = error
        self._ai_model_setup_component = component
        self.aiModelsReadyChanged.emit()
        self.aiModelSetupStateChanged.emit()
        self.aiModelSetupProgressChanged.emit()
        self.aiModelSetupStatusChanged.emit()
        self.aiModelSetupErrorChanged.emit()
        self.aiModelSetupComponentChanged.emit()

    def activate_video(self, video_path: str):
        self._selected_video_path = video_path
        self.selectedVideoPathChanged.emit()


class FakeSettingsController(QObject):
    themeChanged = Signal()

    @Property(str, notify=themeChanged)
    def theme(self):
        return "dark"

    def __init__(self):
        super().__init__()
        self.last_export_mode_reads = 0

    @Slot(result=str)
    def getExportDir(self):
        return ""

    @Slot(result=str)
    def getLastExportMode(self):
        # A value saved by an older version, when the settings window offered clip export.
        self.last_export_mode_reads += 1
        return "export_clips_separate"


class FakeVideoCutController(QObject):
    cutStarted = Signal(int)
    cutFinished = Signal(str)
    cutFailed = Signal(str)
    cutProgress = Signal(float)
    cutBusyChanged = Signal()
    cutProgressValueChanged = Signal()
    cutStatusChanged = Signal()
    cutErrorChanged = Signal()
    cutWarningChanged = Signal()
    cutDetailsChanged = Signal()
    cutOutputPathsChanged = Signal()
    cutCancelledChanged = Signal()

    def __init__(self):
        super().__init__()
        self._cut_busy = False
        self._cut_cancelled = False
        self.cancel_requests = 0
        self._cut_progress_value = 0
        self._cut_status = "Video export idle"
        self._cut_error = ""
        self._cut_warning = ""
        self._cut_details = ""
        self._cut_output_paths = []

    @Property(bool, notify=cutBusyChanged)
    def cutBusy(self):
        return self._cut_busy

    @Property(int, notify=cutProgressValueChanged)
    def cutProgressValue(self):
        return self._cut_progress_value

    @Property(str, notify=cutStatusChanged)
    def cutStatus(self):
        return self._cut_status

    @Property(str, notify=cutErrorChanged)
    def cutError(self):
        return self._cut_error

    @Property(str, notify=cutWarningChanged)
    def cutWarning(self):
        return self._cut_warning

    @Property(str, notify=cutDetailsChanged)
    def cutDetails(self):
        return self._cut_details

    @Property("QVariantList", notify=cutOutputPathsChanged)
    def cutOutputPaths(self):
        return list(self._cut_output_paths)

    @Property(bool, notify=cutCancelledChanged)
    def cutCancelled(self):
        return self._cut_cancelled

    @Slot(result=bool)
    def cancelExport(self):
        self.cancel_requests += 1
        return self._cut_busy

    def start_export(self):
        self._cut_busy = True
        self._cut_cancelled = False
        self._cut_progress_value = 40
        self._cut_status = "Exporting video chunks"
        self.cutBusyChanged.emit()
        self.cutCancelledChanged.emit()
        self.cutProgressValueChanged.emit()
        self.cutStatusChanged.emit()

    def cancel_export_done(self):
        self._cut_busy = False
        self._cut_cancelled = True
        self._cut_progress_value = 0
        self._cut_status = "Video export cancelled"
        self._cut_error = ""
        self._cut_output_paths = []
        self.cutBusyChanged.emit()
        self.cutCancelledChanged.emit()
        self.cutProgressValueChanged.emit()
        self.cutStatusChanged.emit()
        self.cutErrorChanged.emit()
        self.cutOutputPathsChanged.emit()

    @Slot()
    def clearExportResult(self):
        if self._cut_busy:
            return
        self._cut_progress_value = 0
        self._cut_status = "Video export idle"
        self._cut_error = ""
        self._cut_warning = ""
        self._cut_details = ""
        self._cut_output_paths = []
        self.cutProgressValueChanged.emit()
        self.cutStatusChanged.emit()
        self.cutErrorChanged.emit()
        self.cutWarningChanged.emit()
        self.cutDetailsChanged.emit()
        self.cutOutputPathsChanged.emit()

    def complete_export(self, output_path, warning="", details="Mode: remove_intervals"):
        self._cut_busy = False
        self._cut_progress_value = 100
        self._cut_status = "Video export completed: 1 output(s)"
        self._cut_error = ""
        self._cut_warning = warning
        self._cut_details = details
        self._cut_output_paths = [output_path]
        self.cutBusyChanged.emit()
        self.cutProgressValueChanged.emit()
        self.cutStatusChanged.emit()
        self.cutErrorChanged.emit()
        self.cutWarningChanged.emit()
        self.cutDetailsChanged.emit()
        self.cutOutputPathsChanged.emit()
        self.cutFinished.emit(self._cut_status)

    def fail_export(self, error):
        self._cut_busy = False
        self._cut_status = "Video export failed"
        self._cut_error = error
        self._cut_warning = ""
        self._cut_details = ""
        self._cut_output_paths = []
        self.cutBusyChanged.emit()
        self.cutStatusChanged.emit()
        self.cutErrorChanged.emit()
        self.cutWarningChanged.emit()
        self.cutDetailsChanged.emit()
        self.cutOutputPathsChanged.emit()
        self.cutFailed.emit(error)

    @Slot(str, str, str, float, result="QVariantMap")
    def keyframeCutInfo(self, _input_path, _start, _end, _duration=0.0):
        return {"valid": False}

    @Slot(str, "QVariant", str, str)
    def exportSegments(self, input_path, segments, output_dir, export_mode):
        self.export_requests = [*getattr(self, "export_requests", []),
                                {"input_path": input_path, "segments": segments, "export_mode": export_mode}]


class CleanShellPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _load_page(self):
        app_controller = FakeAppController()
        settings_controller = FakeSettingsController()
        video_cut_controller = FakeVideoCutController()
        engine = QQmlApplicationEngine()
        context = engine.rootContext()
        context.setContextProperty("appController", app_controller)
        context.setContextProperty("settingsController", settings_controller)
        context.setContextProperty("videoCutController", video_cut_controller)

        qml_path = (
            Path(__file__).resolve().parents[1]
            / "vue"
            / "qml"
            / "WindowsApplication"
            / "AppShell"
            / "CleanShellPage.qml"
        )
        engine.load(QUrl.fromLocalFile(str(qml_path)))
        self.assertTrue(engine.rootObjects())
        page = engine.rootObjects()[0]
        return engine, page, app_controller, video_cut_controller

    def _load_windowed_page(self, width=1200, height=800, helpers=""):
        app_controller = FakeAppController()
        settings_controller = FakeSettingsController()
        video_cut_controller = FakeVideoCutController()
        engine = QQmlApplicationEngine()
        context = engine.rootContext()
        context.setContextProperty("appController", app_controller)
        context.setContextProperty("settingsController", settings_controller)
        context.setContextProperty("videoCutController", video_cut_controller)
        app_shell_dir = (
            Path(__file__).resolve().parents[1]
            / "vue"
            / "qml"
            / "WindowsApplication"
            / "AppShell"
        )
        qml = f'''import QtQuick
import QtQuick.Controls
import "{app_shell_dir.as_uri()}" as AppShell

ApplicationWindow {{
    visible: true
    width: {width}
    height: {height}
    AppShell.CleanShellPage {{
        id: page
        objectName: "windowedCleanShellPage"
        anchors.fill: parent
    }}
    {helpers}
}}
'''
        engine.loadData(
            qml.encode("utf-8"),
            QUrl.fromLocalFile(str(Path(__file__).resolve())),
        )
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        engine._test_window = window
        page = window.findChild(QObject, "windowedCleanShellPage")
        self.assertIsNotNone(page)
        engine._test_settings_controller = settings_controller
        return engine, page, app_controller, video_cut_controller

    def test_rejected_video_shows_a_dismissible_notice(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        banner = page.findChild(QObject, "videoLoadErrorBanner")
        self.assertIsNotNone(banner)
        self.assertFalse(banner.property("visible"))

        message = '"clip.mp4" is incomplete: the end of the video is missing or damaged.'
        app_controller.set_video_load_error(message)
        self.app.processEvents()
        self.assertTrue(banner.property("visible"))
        self.assertEqual(page.findChild(QObject, "videoLoadErrorText").property("text"), message)
        self.assertEqual(app_controller.selectedVideoPath, "")

        app_controller.dismissVideoLoadError()
        self.app.processEvents()
        self.assertFalse(banner.property("visible"))
        engine.deleteLater()

    def test_export_clean_video_always_removes_the_cuts(self):
        helpers = """
    function addRemovalCut() {
        page.appendCut({"start": "00:00:02", "end": "00:00:04", "safeStart": "00:00:02", "safeEnd": "00:00:04",
                        "safeStartSeconds": 2.0, "safeEndSeconds": 4.0,
                        "requestedStartSeconds": 2.0, "requestedEndSeconds": 4.0})
    }
"""
        engine, page, app_controller, video_cut_controller = self._load_windowed_page(helpers=helpers)
        settings_controller = engine._test_settings_controller
        app_controller.activate_video("C:/videos/movie.mp4")
        self.assertTrue(QMetaObject.invokeMethod(engine._test_window, "addRemovalCut"))
        self.app.processEvents()

        button = page.findChild(QObject, "exportCleanVideoButton")
        self.assertTrue(button.property("enabled"))
        self.assertTrue(QMetaObject.invokeMethod(button, "click"))
        self.app.processEvents()

        # Whatever an older version saved, the visible action exports the cut list as removals.
        self.assertEqual(len(video_cut_controller.export_requests), 1)
        request = video_cut_controller.export_requests[0]
        self.assertEqual(request["export_mode"], "remove_intervals")
        self.assertEqual(request["input_path"], "C:/videos/movie.mp4")
        self.assertEqual(settings_controller.last_export_mode_reads, 0)
        engine.deleteLater()

    def test_settings_window_offers_only_the_connected_export_mode(self):
        import tempfile

        from controllers.settings_controller import SettingsController
        from controllers.update_controller import UpdateController
        from services.i18n.translation_service import TranslationService
        from services.settings_service import SettingsService

        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            service = SettingsService(settings_path=settings_path)
            service.update(last_export_mode="export_clips_merged")  # saved by an older version

            engine = QQmlApplicationEngine()
            root_dir = Path(__file__).resolve().parents[1]
            translation = TranslationService(engine, root_dir / "resources" / "i18n", parent=engine)
            settings_controller = SettingsController(settings_service=service, translation_service=translation)
            update_controller = UpdateController()
            context = engine.rootContext()
            context.setContextProperty("translationService", translation)
            context.setContextProperty("settingsController", settings_controller)
            context.setContextProperty("updateController", update_controller)
            settings_dir = root_dir / "vue" / "qml" / "WindowsApplication" / "Settings"
            qml = f'''import QtQuick
import QtQuick.Controls
import "{settings_dir.as_uri()}" as Settings

ApplicationWindow {{
    visible: true
    width: 900
    height: 900
    Settings.SettingsDialog {{ objectName: "settingsDialog" }}
}}
'''
            engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(Path(__file__).resolve())))
            self.assertTrue(engine.rootObjects())
            window = engine.rootObjects()[0]
            dialog = window.findChild(QObject, "settingsDialog")
            self.assertIsNotNone(dialog)
            self.assertTrue(QMetaObject.invokeMethod(dialog, "openWithCurrentSettings"))
            self.app.processEvents()

            description = dialog.findChild(QObject, "exportModeDescription")
            self.assertIsNotNone(description)
            self.assertIn("removes every cut", description.property("text"))
            visible_text = " ".join(str(item.property(name) or "") for item in dialog.findChildren(QObject)
                                     for name in ("text", "displayText"))
            for advertised in ("clips separately", "merged clips", "remove intervals"):
                self.assertNotIn(advertised, visible_text.casefold())

            save = next(item for item in dialog.findChildren(QObject) if item.property("text") == "Save")
            self.assertTrue(QMetaObject.invokeMethod(save, "click"))
            self.app.processEvents()
            # Saving does not rewrite the old value; nothing reads it for exports.
            self.assertEqual(SettingsService(settings_path=settings_path).load().last_export_mode,
                             "export_clips_merged")
            engine.deleteLater()
            self.app.processEvents()

    def test_video_check_in_progress_is_visible_and_cancellable(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        banner = page.findChild(QObject, "videoLoadingBanner")
        self.assertFalse(banner.property("visible"))

        app_controller.set_video_loading("movie.mkv")
        self.app.processEvents()
        self.assertTrue(banner.property("visible"))
        self.assertIn("movie.mkv", page.findChild(QObject, "videoLoadingText").property("text"))

        self.assertTrue(QMetaObject.invokeMethod(page.findChild(QObject, "cancelVideoLoadButton"), "click"))
        self.app.processEvents()
        self.assertEqual(app_controller.video_load_cancellations, 1)
        self.assertFalse(banner.property("visible"))
        engine.deleteLater()

    def test_empty_video_stage_is_a_real_open_button(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        open_button = page.findChild(QObject, "openVideoButton")
        self.assertIsNotNone(open_button)
        self.assertTrue(open_button.property("visible"))

        self.assertTrue(QMetaObject.invokeMethod(open_button, "click"))
        self.app.processEvents()

        self.assertEqual(app_controller.open_file_requests, 1)
        self.assertIsNotNone(engine)

    def test_video_controls_stay_inside_a_short_window(self):
        engine, page, _app_controller, _video_cut_controller = self._load_windowed_page(
            height=640
        )
        self.app.processEvents()

        workspace = page.findChild(QObject, "videoWorkspace")
        playback_controls = page.findChild(QObject, "playbackControlsBar")
        cut_actions = page.findChild(QObject, "cutActionBar")
        self.assertIsNotNone(workspace)
        self.assertIsNotNone(playback_controls)
        self.assertIsNotNone(cut_actions)

        workspace_height = float(workspace.property("height"))
        self.assertLessEqual(
            float(playback_controls.property("y"))
            + float(playback_controls.property("height")),
            workspace_height,
        )
        self.assertLessEqual(
            float(cut_actions.property("y")) + float(cut_actions.property("height")),
            workspace_height,
        )
        self.assertIsNotNone(engine)

    def _open_ai_picks(self, page):
        popup = page.findChild(QObject, "aiPicksPopup")
        self.assertIsNotNone(popup)
        self.assertTrue(QMetaObject.invokeMethod(popup, "open"))
        self.app.processEvents()
        self.assertTrue(popup.property("opened"))
        return popup

    def test_switching_video_clears_page_local_cuts(self):
        engine, page, app_controller, _video_cut_controller = self._load_page()
        cuts_model = page.findChild(QObject, "cutsModel")
        self.assertIsNotNone(cuts_model)

        app_controller.activate_video("C:/videos/a.mp4")
        page.applyImportedCuts(
            [
                {
                    "start": "00:00:01",
                    "end": "00:00:02",
                    "requested_start_seconds": 1.0,
                    "requested_end_seconds": 2.0,
                    "safe_start_seconds": 1.0,
                    "safe_end_seconds": 2.0,
                }
            ]
        )
        self.assertEqual(cuts_model.property("count"), 1)

        app_controller.activate_video("C:/videos/a.mp4")
        self.assertEqual(cuts_model.property("count"), 1)

        app_controller.activate_video("C:/videos/b.mp4")

        self.assertEqual(cuts_model.property("count"), 0)
        self.assertEqual(page.property("selectedCutIndex"), -1)
        self.assertIsNotNone(engine)

    def test_successful_export_surfaces_output_warning_and_details(self):
        engine, page, _app_controller, video_cut_controller = self._load_page()
        output_path = "C:/exports/movie_removed_intervals.mp4"

        video_cut_controller.complete_export(
            output_path,
            warning="Output duration differs by 0.4 seconds.",
            details="Mode: remove_intervals\nActual duration: 42.000s",
        )
        self.app.processEvents()

        panel = page.findChild(QObject, "exportResultPanel")
        status = page.findChild(QObject, "exportResultStatusText")
        output = page.findChild(QObject, "exportOutputPathText")
        warning = page.findChild(QObject, "exportWarningText")
        details = page.findChild(QObject, "exportDetailsText")
        self.assertTrue(panel.property("visible"))
        self.assertEqual(status.property("text"), "Export completed")
        self.assertIn(output_path, output.property("text"))
        self.assertIn("differs by 0.4 seconds", warning.property("text"))
        self.assertIn("Actual duration: 42.000s", details.property("text"))
        self.assertIsNotNone(engine)

    def test_failed_export_surfaces_error_information(self):
        engine, page, _app_controller, video_cut_controller = self._load_page()

        video_cut_controller.fail_export("FFmpeg could not write the output file.")
        self.app.processEvents()

        panel = page.findChild(QObject, "exportResultPanel")
        status = page.findChild(QObject, "exportResultStatusText")
        error = page.findChild(QObject, "exportErrorText")
        self.assertTrue(panel.property("visible"))
        self.assertEqual(status.property("text"), "Export failed")
        self.assertEqual(error.property("text"), "FFmpeg could not write the output file.")
        self.assertIsNotNone(engine)

    def test_cancel_button_is_offered_while_exporting_and_calls_the_controller(self):
        engine, page, _app_controller, video_cut_controller = self._load_page()
        cancel_button = page.findChild(QObject, "cancelExportButton")
        self.assertIsNotNone(cancel_button)
        self.assertFalse(cancel_button.property("visible"))

        video_cut_controller.start_export()
        self.app.processEvents()

        self.assertTrue(cancel_button.property("visible"))
        self.assertTrue(QMetaObject.invokeMethod(cancel_button, "click"))
        self.app.processEvents()
        self.assertEqual(video_cut_controller.cancel_requests, 1)
        self.assertIsNotNone(engine)

    def test_cancelled_export_is_reported_distinctly_from_failure(self):
        engine, page, _app_controller, video_cut_controller = self._load_page()
        video_cut_controller.start_export()
        self.app.processEvents()

        video_cut_controller.cancel_export_done()
        self.app.processEvents()

        panel = page.findChild(QObject, "exportResultPanel")
        status = page.findChild(QObject, "exportResultStatusText")
        cancel_button = page.findChild(QObject, "cancelExportButton")
        self.assertTrue(panel.property("visible"))
        self.assertEqual(status.property("text"), "Export cancelled. No file was kept.")
        self.assertFalse(cancel_button.property("visible"))
        self.assertIsNotNone(engine)

    def test_switching_video_clears_terminal_export_result(self):
        engine, page, app_controller, video_cut_controller = self._load_page()
        app_controller.activate_video("C:/videos/a.mp4")
        page.setProperty("exportVideoPath", "C:/videos/a.mp4")
        video_cut_controller.complete_export("C:/exports/a_clean.mp4")
        self.app.processEvents()
        panel = page.findChild(QObject, "exportResultPanel")
        self.assertTrue(panel.property("visible"))

        app_controller.activate_video("C:/videos/b.mp4")
        self.app.processEvents()

        self.assertFalse(panel.property("visible"))
        self.assertEqual(video_cut_controller.cutOutputPaths, [])
        self.assertIsNotNone(engine)

    def test_ai_picks_requires_explicit_model_download_confirmation(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        popup = self._open_ai_picks(page)
        app_controller.set_ai_model_setup(
            "required",
            status="Production AI model setup is required.",
        )
        self.app.processEvents()

        explanation = popup.findChild(QObject, "aiModelSetupExplanation")
        download_button = popup.findChild(QObject, "downloadAiModelsButton")
        analyze_button = popup.findChild(QObject, "aiPicksActionButton")
        confirmation = popup.findChild(QObject, "aiModelDownloadConfirmation")
        confirm_button = popup.findChild(QObject, "confirmAiModelDownloadButton")
        self.assertTrue(popup.property("showModelSetup"))
        self.assertTrue(popup.property("showModelDownloadAction"))
        self.assertTrue(explanation.property("visible"))
        self.assertTrue(download_button.property("visible"))
        self.assertIn("7.5 GiB", explanation.property("text"))
        self.assertFalse(popup.property("analyzeActionEnabled"))
        self.assertFalse(analyze_button.property("enabled"))

        self.assertTrue(QMetaObject.invokeMethod(download_button, "click"))
        self.app.processEvents()
        self.assertTrue(confirmation.property("opened"))
        self.assertEqual(app_controller.model_downloads, 0)

        self.assertTrue(QMetaObject.invokeMethod(confirm_button, "click"))
        self.app.processEvents()
        self.assertEqual(app_controller.model_downloads, 1)
        self.assertFalse(confirmation.property("opened"))
        self.assertGreaterEqual(app_controller.model_status_refreshes, 1)
        self.assertIsNotNone(engine)

    def test_ai_picks_shows_truthful_downloading_and_cancelling_states(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        popup = self._open_ai_picks(page)
        app_controller.set_ai_model_setup(
            "downloading",
            progress=1,
            status="Downloading pinned visual review model",
            component="Visual review",
        )
        self.app.processEvents()

        progress = popup.findChild(QObject, "aiModelSetupProgressText")
        component = popup.findChild(QObject, "aiModelSetupComponentText")
        cancel_button = popup.findChild(QObject, "cancelAiModelDownloadButton")
        self.assertTrue(popup.property("showModelSetupProgress"))
        self.assertTrue(progress.property("visible"))
        self.assertEqual(progress.property("text"), "1 / 3 models ready")
        self.assertEqual(component.property("text"), "Visual review")
        self.assertTrue(cancel_button.property("visible"))
        self.assertTrue(cancel_button.property("enabled"))

        self.assertTrue(QMetaObject.invokeMethod(cancel_button, "click"))
        self.assertEqual(app_controller.model_cancellations, 1)
        app_controller.set_ai_model_setup(
            "cancelling",
            progress=1,
            status="waiting",
            component="Visual review",
        )
        self.app.processEvents()
        status = popup.findChild(QObject, "aiModelSetupStatusText")
        self.assertIn("current model transfer", status.property("text"))
        self.assertFalse(cancel_button.property("enabled"))
        self.assertIsNotNone(engine)

    def test_ai_picks_error_and_cancelled_states_offer_retry(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        popup = self._open_ai_picks(page)
        retry_button = popup.findChild(QObject, "retryAiModelDownloadButton")
        error_text = popup.findChild(QObject, "aiModelSetupErrorText")

        app_controller.set_ai_model_setup(
            "error",
            status="Production AI model setup failed.",
            error="Network connection was interrupted.",
        )
        self.app.processEvents()
        self.assertTrue(popup.property("showModelSetupRetry"))
        self.assertTrue(retry_button.property("visible"))
        self.assertTrue(error_text.property("visible"))
        self.assertIn("interrupted", error_text.property("text"))
        confirmation = popup.findChild(QObject, "aiModelDownloadConfirmation")
        confirm_button = popup.findChild(QObject, "confirmAiModelDownloadButton")
        self.assertTrue(QMetaObject.invokeMethod(retry_button, "click"))
        self.app.processEvents()
        self.assertTrue(confirmation.property("opened"))
        self.assertEqual(app_controller.model_retries, 0)
        self.assertTrue(QMetaObject.invokeMethod(confirm_button, "click"))
        self.app.processEvents()
        self.assertEqual(app_controller.model_retries, 1)

        app_controller.set_ai_model_setup(
            "cancelled",
            status="Downloaded data was kept for retry.",
        )
        self.app.processEvents()
        self.assertTrue(popup.property("showModelSetupRetry"))
        self.assertIsNotNone(engine)

    def test_ai_picks_hides_setup_and_restores_analyze_when_ready(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page()
        app_controller.activate_video("C:/videos/a.mp4")
        popup = self._open_ai_picks(page)
        app_controller.set_ai_model_setup(
            "ready",
            ready=True,
            progress=3,
            status="AI models are ready",
        )
        self.app.processEvents()

        setup_panel = popup.findChild(QObject, "aiModelSetupPanel")
        analyze_button = popup.findChild(QObject, "aiPicksActionButton")
        self.assertFalse(popup.property("showModelSetup"))
        self.assertTrue(popup.property("analyzeActionEnabled"))
        self.assertFalse(setup_panel.property("visible"))
        self.assertTrue(analyze_button.property("enabled"))
        self.assertIsNotNone(engine)


if __name__ == "__main__":
    unittest.main()
