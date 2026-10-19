import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Q_ARG, Property, QMetaObject, QObject, QUrl, Signal, Slot
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
        self._ai_suggestions = []

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
        return list(self._ai_suggestions)

    def set_ai_suggestions(self, suggestions):
        self._ai_suggestions = [dict(item) for item in suggestions]
        self.aiSuggestionsChanged.emit()

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

    def test_export_explanation_and_loading_notice_are_translated(self):
        import subprocess
        import sys
        import tempfile

        from controllers.settings_controller import SettingsController
        from controllers.update_controller import UpdateController
        from services.i18n.translation_service import TranslationService
        from services.settings_service import SettingsService

        lrelease = Path(sys.executable).parent / "pyside6-lrelease.exe"
        if not lrelease.is_file():
            self.skipTest("pyside6-lrelease is not available")
        root_dir = Path(__file__).resolve().parents[1]
        expected = {
            "fr": ("supprime toutes les coupes de la liste", "Vérification de movie.mkv…"),
            "ar": ("يزيل «تصدير فيديو نظيف» كل القصوص", "جارٍ التحقق من movie.mkv…"),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            # Compile the tracked catalogs, so the test checks them rather than a stale local .qm.
            for language in expected:
                completed = subprocess.run(
                    [str(lrelease), str(root_dir / "resources" / "i18n" / f"app_{language}.ts"),
                     "-qm", str(Path(temp_dir) / f"app_{language}.qm")],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            for language, (settings_fragment, loading_text) in expected.items():
                with self.subTest(language=language):
                    engine = QQmlApplicationEngine()
                    translation = TranslationService(engine, temp_dir, parent=engine)
                    self.assertTrue(translation.setLanguage(language))
                    try:
                        service = SettingsService(settings_path=Path(temp_dir) / "settings.json")
                        context = engine.rootContext()
                        context.setContextProperty("translationService", translation)
                        context.setContextProperty(
                            "settingsController", SettingsController(settings_service=service,
                                                                     translation_service=translation))
                        context.setContextProperty("updateController", UpdateController())
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
                        window = engine.rootObjects()[0]
                        description = window.findChild(QObject, "exportModeDescription")
                        self.assertIn(settings_fragment, description.property("text"))

                        page_engine, page, app_controller, _cut = self._load_windowed_page()
                        app_controller.set_video_loading("movie.mkv")
                        self.app.processEvents()
                        self.assertEqual(page.findChild(QObject, "videoLoadingText").property("text"), loading_text)
                        page_engine.deleteLater()
                        engine.deleteLater()
                        self.app.processEvents()
                    finally:
                        translation.setLanguage("en")

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

    def test_reviewing_a_suggestion_keeps_the_list_scroll_position(self):
        engine, page, app_controller, _video_cut_controller = self._load_windowed_page(height=900)
        suggestions = [
            {"id": f"s{index}", "start": f"00:00:{index * 3:02d}", "end": f"00:00:{index * 3 + 2:02d}",
             "category": "uncertain", "confidence": "50%", "reason": f"Fixture {index}", "review_state": "pending"}
            for index in range(6)
        ]
        app_controller.set_ai_suggestions(suggestions)
        popup = self._open_ai_picks(page)
        suggestion_list = next(child for child in popup.findChildren(QObject)
                               if child.metaObject().className() == "QQuickListView")
        self.assertGreater(suggestion_list.property("contentHeight"), suggestion_list.property("height"))
        suggestion_list.setProperty("contentY", 300)
        self.app.processEvents()

        suggestions[3]["review_state"] = "rejected"  # what reviewAiSuggestion publishes
        app_controller.set_ai_suggestions(suggestions)
        self.app.processEvents()

        self.assertEqual(suggestion_list.property("contentY"), 300)
        self.assertEqual(suggestion_list.property("count"), 6)
        # A different set of suggestions (a new analysis) is still shown from the top.
        app_controller.set_ai_suggestions(suggestions[:2])
        self.app.processEvents()
        self.assertEqual(suggestion_list.property("count"), 2)
        self.assertIsNotNone(engine)

    def test_a_long_export_refusal_is_shown_in_full(self):
        engine, page, _app_controller, video_cut_controller = self._load_windowed_page(width=1280, height=760)
        refusal = (
            "Fast Cutting cannot remove the selected intervals exactly: stream copy can only cut on a keyframe that "
            "starts an independent group of frames, and these cut boundaries are not on one: 00:00:15.520 (nearest "
            "keyframes 00:00:14.000 and 00:00:16.000). Nothing was exported and the cuts were not changed. Use Smart "
            "Cutting for frame-exact removal, or move these boundaries onto the listed keyframes."
        )
        video_cut_controller.fail_export(refusal)
        self.app.processEvents()
        error = page.findChild(QObject, "exportErrorText")
        self.assertEqual(error.property("text"), refusal)
        self.assertFalse(error.property("truncated"))
        self.assertGreater(error.property("lineCount"), 1)
        self.assertIsNotNone(engine)

    def test_buttons_and_settings_show_whole_labels_in_english_french_and_arabic(self):
        import subprocess
        import sys
        import tempfile

        from PySide6.QtGui import QFont

        from controllers.settings_controller import SettingsController
        from controllers.update_controller import UpdateController
        from services.i18n.translation_service import TranslationService
        from services.settings_service import SettingsService

        lrelease = Path(sys.executable).parent / "pyside6-lrelease.exe"
        if not lrelease.is_file():
            self.skipTest("pyside6-lrelease is not available")
        root_dir = Path(__file__).resolve().parents[1]
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        from main import load_windows_ui_font_family

        original_font = self.app.font()
        self.app.setFont(QFont(load_windows_ui_font_family(), 9))  # as main.py does
        self.addCleanup(self.app.setFont, original_font)

        def truncated_labels(window):
            labels = []
            for item in window.findChildren(QObject):
                class_name = item.metaObject().className()
                if not class_name.startswith(("QQuickText", "QQuickLabel")) or class_name.startswith(
                        ("QQuickTextEdit", "QQuickTextInput", "QQuickTextField", "QQuickTextArea")):
                    continue
                if item.property("visible") and item.property("width") > 0 and item.property("truncated"):
                    labels.append(item.property("text"))
            return labels

        with tempfile.TemporaryDirectory() as temp_dir:
            for language in ("fr", "ar"):
                completed = subprocess.run(
                    [str(lrelease), str(root_dir / "resources" / "i18n" / f"app_{language}.ts"),
                     "-qm", str(Path(temp_dir) / f"app_{language}.qm")],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
            # 1888x1017 physical pixels at 125 % scaling (the validated Windows setup), and the minimum size.
            for width, height in ((1510, 790), (1280, 720)):
                for language in ("en", "fr", "ar"):
                    with self.subTest(language=language, width=width):
                        engine, page, _app, _cut = self._load_windowed_page(width=width, height=height)
                        translation = TranslationService(engine, temp_dir, parent=engine)
                        self.assertTrue(translation.setLanguage(language))
                        try:
                            self.app.processEvents()
                            self.assertEqual(truncated_labels(engine._test_window), [])

                            settings_engine = QQmlApplicationEngine()
                            settings_translation = TranslationService(settings_engine, temp_dir, parent=settings_engine)
                            context = settings_engine.rootContext()
                            context.setContextProperty("translationService", settings_translation)
                            context.setContextProperty("settingsController", SettingsController(
                                settings_service=SettingsService(settings_path=Path(temp_dir) / "settings.json"),
                                translation_service=settings_translation))
                            context.setContextProperty("updateController", UpdateController())
                            settings_dir = root_dir / "vue" / "qml" / "WindowsApplication" / "Settings"
                            qml = f'''import QtQuick
import QtQuick.Controls
import "{settings_dir.as_uri()}" as Settings

ApplicationWindow {{
    visible: true
    width: {width}
    height: {height}
    Settings.SettingsDialog {{ objectName: "settingsDialog" }}
}}
'''
                            settings_engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(Path(__file__).resolve())))
                            settings_window = settings_engine.rootObjects()[0]
                            dialog = settings_window.findChild(QObject, "settingsDialog")
                            self.assertTrue(QMetaObject.invokeMethod(dialog, "open"))
                            self.app.processEvents()
                            self.assertEqual(truncated_labels(settings_window), [])
                            settings_engine.deleteLater()
                        finally:
                            translation.setLanguage("en")
                        engine.deleteLater()
                        self.app.processEvents()


class PlayerAppController(QObject):
    """The part of AppController that VideoWorkspace uses, with a settable video."""

    selectedVideoPathChanged = Signal()
    keyframeStateChanged = Signal()

    def __init__(self):
        super().__init__()
        self._path = ""

    def set_video(self, path):
        self._path = str(path) if path else ""
        self.selectedVideoPathChanged.emit()

    @Property(str, notify=selectedVideoPathChanged)
    def selectedVideoPath(self):
        return self._path

    @Property(str, notify=selectedVideoPathChanged)
    def videoUrl(self):
        return QUrl.fromLocalFile(self._path).toString() if self._path else ""

    @Property(str, constant=True)
    def previewSubtitleText(self):
        return ""

    @Property(int, constant=True)
    def activePreviewSubtitleTrackIndex(self):
        return -1

    @Slot(str, str, str, str, str, str)
    def logPlaybackState(self, *_args):
        pass

    @Slot(int)
    def updatePlayerSubtitleTrackCount(self, _count):
        pass

    @Slot(float)
    def updatePreviewSubtitlePosition(self, _position):
        pass

    @Slot()
    def openFile(self):
        pass


class VideoWorkspacePreviewTests(unittest.TestCase):
    """V05: a seek before the first Play must show the frame at the new position, silently."""

    @classmethod
    def setUpClass(cls):
        import sys
        import tempfile

        from PySide6 import QtMultimedia  # noqa: F401  (registers the QVideoSink type for property access)

        cls.app = QApplication.instance() or QApplication([])
        root_dir = Path(__file__).resolve().parents[1]
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        from evaluation import export_frame_accuracy as efa
        from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path

        try:
            ffmpeg = get_ffmpeg_path()
        except FFmpegNotFoundError:
            raise unittest.SkipTest("FFmpeg is not available") from None
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        # Pattern: left half encodes the source second, right half the frame within the second (25 fps).
        cls.mp4 = efa.generate_fixture(ffmpeg, efa.FIXTURES["h264_aac_mp4"], folder)
        cls.mkv = efa.generate_fixture(ffmpeg, efa.FIXTURES["h264_aac_mkv"], folder)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.controller = PlayerAppController()
        self.engine = QQmlApplicationEngine()
        context = self.engine.rootContext()
        context.setContextProperty("appController", self.controller)
        context.setContextProperty("videoCutController", FakeVideoCutController())
        player_dir = Path(__file__).resolve().parents[1] / "vue" / "qml" / "WindowsApplication" / "VideoPlayer"
        qml = f'''import QtQuick
import QtQuick.Controls
import "{player_dir.as_uri()}" as Player

ApplicationWindow {{
    visible: true
    width: 900
    height: 700
    ListModel {{ id: cuts }}
    Player.VideoWorkspace {{ objectName: "workspace"; anchors.fill: parent; cutsModel: cuts }}
}}
'''
        self.engine.loadData(qml.encode("utf-8"), QUrl.fromLocalFile(str(Path(__file__).resolve())))
        self.window = self.engine.rootObjects()[0]
        self.workspace = self.window.findChild(QObject, "workspace")
        self.player = next(child for child in self.workspace.findChildren(QObject)
                           if child.metaObject().className() == "QQuickMediaPlayer")
        output = next(child for child in self.window.findChildren(QObject)
                      if child.metaObject().className() == "QQuickVideoOutput")
        self.sink = output.property("videoSink")
        self.states = []
        self.player.playbackStateChanged.connect(lambda state: self.states.append(int(getattr(state, "value", state))))

    def tearDown(self):
        self.controller.set_video("")
        self.engine.deleteLater()
        self.app.processEvents()

    def state(self):
        # 0 stopped, 1 playing, 2 paused
        value = self.player.property("playbackState")
        return int(getattr(value, "value", value))

    def wait_for(self, condition, timeout_ms=8000):
        from PySide6.QtCore import QElapsedTimer, QEventLoop

        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < timeout_ms:
            if condition():
                return True
            self.app.processEvents(QEventLoop.AllEvents, 20)
        return condition()

    def shown_frame_index(self):
        frame = self.sink.videoFrame()
        if not frame.isValid():
            return None
        image = frame.toImage()
        y = image.height() // 2
        second = round(image.pixelColor(image.width() // 4, y).red() * 219 / 255 / 8)
        within = round(image.pixelColor(3 * image.width() // 4, y).red() * 219 / 255 / 8)
        return second * 25 + within

    def assert_shows(self, position_ms):
        # Paused Qt shows the last frame starting at or before the position.
        expected = int(position_ms // 40)
        self.assertTrue(self.wait_for(lambda: self.shown_frame_index() in (expected - 1, expected)),
                        f"shown frame {self.shown_frame_index()}, expected about {expected}")

    def seek_to(self, position_ms):
        QMetaObject.invokeMethod(self.workspace, "seekTo", Q_ARG("QVariant", position_ms))

    def seek_by(self, seconds):
        QMetaObject.invokeMethod(self.workspace, "seekBy", Q_ARG("QVariant", seconds))

    def test_seek_before_first_play_shows_the_frame_without_playing(self):
        self.controller.set_video(self.mp4)
        self.assertTrue(self.wait_for(lambda: self.state() == 2))  # paused, not playing
        self.seek_to(12000)
        self.assert_shows(12000)
        self.seek_by(5)
        self.assert_shows(17000)
        self.assertEqual(self.player.property("position"), 17000)
        self.assertNotIn(1, self.states, "the player must never start playing on its own")

    def test_seek_requested_while_loading_is_applied_once_loaded(self):
        self.controller.set_video(self.mp4)
        self.seek_to(9000)  # media not loaded yet
        self.assertTrue(self.wait_for(lambda: self.player.property("position") == 9000))
        self.assert_shows(9000)
        self.assertNotIn(1, self.states)

    def test_switching_video_drops_the_old_pending_seek(self):
        self.controller.set_video(self.mp4)
        self.seek_to(20000)
        self.controller.set_video(self.mkv)  # before the MP4 finished loading
        self.assertTrue(self.wait_for(lambda: self.state() == 2))
        self.assertEqual(self.player.property("position"), 0)
        self.seek_to(4000)
        self.assert_shows(4000)

    def test_opening_another_video_after_a_loaded_one_still_shows_frames(self):
        # Packaged-app V05 retest: MP4 loaded (paused on its first frame), then an MKV is opened.
        self.controller.set_video(self.mp4)
        self.assertTrue(self.wait_for(lambda: self.state() == 2))
        self.assert_shows(0)
        self.controller.set_video(self.mkv)
        self.assertTrue(self.wait_for(lambda: self.player.property("source").toLocalFile().endswith(".mkv")
                                      and self.state() == 2 and self.shown_frame_index() == 0))
        self.seek_to(12000)
        self.assert_shows(12000)
        self.assertNotIn(1, self.states)

    def test_seek_right_after_opening_another_video_is_applied_to_it(self):
        self.controller.set_video(self.mp4)
        self.assertTrue(self.wait_for(lambda: self.state() == 2))
        self.controller.set_video(self.mkv)
        self.seek_to(9000)  # while the MKV is still being opened
        self.assertTrue(self.wait_for(lambda: self.player.property("source").toLocalFile().endswith(".mkv")
                                      and self.player.property("position") == 9000))
        self.assert_shows(9000)
        self.assertEqual(self.state(), 2)
        self.assertNotIn(1, self.states)

    def test_seek_after_the_end_of_the_video_shows_the_frame(self):
        self.controller.set_video(self.mkv)
        self.assertTrue(self.wait_for(lambda: self.state() == 2))
        self.seek_to(29600)
        QMetaObject.invokeMethod(self.workspace, "togglePlayback")
        self.assertTrue(self.wait_for(lambda: self.state() == 0))  # stopped at the end
        self.seek_to(6000)
        self.assert_shows(6000)
        self.assertEqual(self.state(), 2)


if __name__ == "__main__":
    unittest.main()
