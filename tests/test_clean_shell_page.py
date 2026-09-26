import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication


class FakeAppController(QObject):
    selectedVideoPathChanged = Signal()
    aiSuggestionsChanged = Signal()
    subtitleCandidatesChanged = Signal()

    def __init__(self):
        super().__init__()
        self._selected_video_path = ""

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

    def activate_video(self, video_path: str):
        self._selected_video_path = video_path
        self.selectedVideoPathChanged.emit()


class FakeSettingsController(QObject):
    themeChanged = Signal()

    @Property(str, notify=themeChanged)
    def theme(self):
        return "dark"

    @Slot(result=str)
    def getExportDir(self):
        return ""


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

    def __init__(self):
        super().__init__()
        self._cut_busy = False
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


if __name__ == "__main__":
    unittest.main()
