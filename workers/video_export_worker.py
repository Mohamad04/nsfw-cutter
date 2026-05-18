from PySide6.QtCore import QRunnable, Slot

from services.video_export_service import export_lossless_video
from workers.worker_signals import WorkerSignals


class VideoExportWorker(QRunnable):
    def __init__(self, job_key: str, input_path: str, output_path: str):
        super().__init__()
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.progress.emit(self.job_key, 0, "Starting export...")

            result = export_lossless_video(
                input_path=self.input_path,
                output_path=self.output_path,
                progress_callback=lambda percent, message: self.signals.progress.emit(
                    self.job_key,
                    percent,
                    message,
                ),
            )

            self.signals.progress.emit(self.job_key, 100, "Export completed")
            self.signals.finished.emit(self.job_key, result)
        except Exception as exc:
            self.signals.error.emit(self.job_key, str(exc))
