import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.job_registry import JobRegistry
from services.editing.export_service import export_lossless_video
from workers.video_export_worker import VideoExportWorker


class BackgroundJobTests(unittest.TestCase):
    def test_job_registry_prevents_duplicate_jobs(self):
        registry = JobRegistry()

        self.assertIs(registry.try_start("job1"), True)
        self.assertIs(registry.try_start("job1"), False)

        registry.finish("job1")

        self.assertIs(registry.try_start("job1"), True)

    def test_export_service_rejects_missing_input(self):
        with self.assertRaises(FileNotFoundError):
            export_lossless_video("missing.mp4", "out.mp4")

    def test_export_service_rejects_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "source.txt"
            source.write_text("not a video")

            with self.assertRaises(ValueError):
                export_lossless_video(str(source), str(Path(tmp_dir) / "out.mp4"))

    def test_export_service_accepts_supported_video_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "source.mp4"
            destination = Path(tmp_dir) / "out.mp4"
            source.write_bytes(b"video fixture")

            result = export_lossless_video(str(source), str(destination))

            self.assertEqual(result, str(destination))
            self.assertEqual(destination.read_bytes(), b"video fixture")

    def test_worker_emits_finished_on_success(self):
        worker = VideoExportWorker("job1", "in.mp4", "out.mp4")
        finished = []
        errors = []

        worker.signals.finished.connect(lambda job_key, result: finished.append((job_key, result)))
        worker.signals.error.connect(lambda job_key, message: errors.append((job_key, message)))

        with patch("workers.video_export_worker.export_lossless_video", return_value="out.mp4"):
            worker.run()

        self.assertEqual(finished, [("job1", "out.mp4")])
        self.assertEqual(errors, [])

    def test_worker_emits_error_on_failure(self):
        worker = VideoExportWorker("job1", "in.mp4", "out.mp4")
        finished = []
        errors = []

        worker.signals.finished.connect(lambda job_key, result: finished.append((job_key, result)))
        worker.signals.error.connect(lambda job_key, message: errors.append((job_key, message)))

        with patch(
            "workers.video_export_worker.export_lossless_video",
            side_effect=RuntimeError("export failed"),
        ):
            worker.run()

        self.assertEqual(finished, [])
        self.assertEqual(errors, [("job1", "export failed")])


if __name__ == "__main__":
    unittest.main()
