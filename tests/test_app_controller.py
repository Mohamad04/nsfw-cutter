import unittest

from controllers.app_controller import AppController
from workers.worker_signals import WorkerSignals


class FakeVideoImportService:
    def __init__(self):
        self.videos = [
            {
                "name": "a.mp4",
                "path": "/tmp/a.mp4",
                "subtitle_found": False,
                "subtitle_name": None,
            }
        ]

    def list_importable_videos(self, folder):
        if folder == "invalid":
            raise ValueError("Selected folder does not exist")
        if folder == "empty":
            return []
        return self.videos

    def import_video_file(self, file_path, user_id=None):
        if file_path == "invalid":
            raise ValueError("Selected video file does not exist")
        return {
            "video_id": 1,
            "video_name": "a.mp4",
            "video_path": "/tmp/a.mp4",
            "video_url": "file:///tmp/a.mp4",
            "subtitle_found": False,
            "subtitle_name": None,
            "status": "Video loaded",
        }


class FakeThreadPool:
    def __init__(self):
        self.workers = []
        self.max_thread_count = None

    def setMaxThreadCount(self, count):
        self.max_thread_count = count

    def start(self, worker):
        self.workers.append(worker)


class FakeExportWorker:
    def __init__(self, job_key, input_path, output_path):
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path
        self.signals = WorkerSignals()


class AppControllerTests(unittest.TestCase):
    def setUp(self):
        self.thread_pool = FakeThreadPool()
        self.controller = AppController(
            video_import_service=FakeVideoImportService(),
            thread_pool=self.thread_pool,
            worker_factory=FakeExportWorker,
        )

    def test_load_folder_populates_available_videos(self):
        self.controller.loadFolder("folder")

        self.assertEqual(self.controller.availableVideos[0]["name"], "a.mp4")
        self.assertEqual(self.controller.projectStatus, "1 video(s) found. Select one to load.")

    def test_load_folder_empty_sets_status(self):
        self.controller.loadFolder("empty")

        self.assertEqual(self.controller.availableVideos, [])
        self.assertEqual(self.controller.projectStatus, "No video found in selected folder")

    def test_load_video_file_updates_properties(self):
        self.controller.loadVideoFile("/tmp/a.mp4")

        self.assertEqual(self.controller.videoUrl, "file:///tmp/a.mp4")
        self.assertEqual(self.controller.videoName, "a.mp4")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: not detected")
        self.assertEqual(self.controller.projectStatus, "Video loaded")
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")

    def test_load_video_file_invalid_does_not_crash(self):
        self.controller.loadVideoFile("invalid")

        self.assertEqual(self.controller.projectStatus, "Selected video file does not exist")

    def test_select_available_video_loads_by_index(self):
        self.controller.loadFolder("folder")
        self.controller.selectAvailableVideo(0)

        self.assertEqual(self.controller.videoName, "a.mp4")
        self.assertEqual(self.controller.selectedVideoPath, "/tmp/a.mp4")

    def test_select_available_video_invalid_index_sets_status(self):
        self.controller.selectAvailableVideo(10)

        self.assertEqual(self.controller.projectStatus, "Invalid video selection")

    def test_clear_video_resets_properties(self):
        self.controller.loadVideoFile("/tmp/a.mp4")
        self.controller.clearVideo()

        self.assertEqual(self.controller.videoUrl, "")
        self.assertEqual(self.controller.videoName, "No video selected")
        self.assertEqual(self.controller.subtitleStatus, "Subtitle: not detected")
        self.assertEqual(self.controller.projectStatus, "Ready")
        self.assertEqual(self.controller.selectedVideoPath, "")

    def test_start_lossless_export_updates_state_and_starts_worker(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.assertTrue(self.controller.exportBusy)
        self.assertEqual(self.controller.exportProgress, 0)
        self.assertEqual(self.controller.exportStatus, "Preparing export...")
        self.assertEqual(len(self.thread_pool.workers), 1)

    def test_start_lossless_export_blocks_duplicate_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.assertEqual(len(self.thread_pool.workers), 1)
        self.assertEqual(self.controller.exportStatus, "This export is already running.")

    def test_export_finished_cleans_up_running_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.controller._on_export_finished("export:/tmp/a.mp4:/tmp/a_export.mp4", "/tmp/a_export.mp4")

        self.assertFalse(self.controller.exportBusy)
        self.assertEqual(self.controller.exportProgress, 100)
        self.assertEqual(self.controller.exportStatus, "Export completed: /tmp/a_export.mp4")

    def test_export_error_cleans_up_running_job(self):
        self.controller.startLosslessExport("/tmp/a.mp4", "/tmp/a_export.mp4")

        self.controller._on_export_error("export:/tmp/a.mp4:/tmp/a_export.mp4", "bad input")

        self.assertFalse(self.controller.exportBusy)
        self.assertEqual(self.controller.exportStatus, "Export failed: bad input")


if __name__ == "__main__":
    unittest.main()
