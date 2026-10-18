import logging

from PySide6.QtCore import QRunnable, Slot

from services.editing.export_service import export_lossless_video
from services.user_errors import technical_details, user_message
from workers.worker_signals import WorkerSignals


logger = logging.getLogger(__name__)


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
            logger.error("Lossless export failed: %s\n%s", self.job_key, technical_details(exc), exc_info=exc)
            self.signals.error.emit(self.job_key, user_message(exc))
