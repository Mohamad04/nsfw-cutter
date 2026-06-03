from PySide6.QtCore import QRunnable, Slot

from services.editing.cut_pipeline_service import run_video_cut_job
from workers.worker_signals import WorkerSignals


class VideoCutWorker(QRunnable):
    def __init__(self, job_key: str, request_data: dict, pipeline=None):
        super().__init__()
        self.job_key = job_key
        self.request_data = request_data
        self.pipeline = pipeline or run_video_cut_job
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.pipeline(
                self.request_data,
                progress_callback=lambda percent, message: self.signals.progress.emit(
                    self.job_key,
                    percent,
                    message,
                ),
            )
            self.signals.progress.emit(self.job_key, 100, "Fast cut completed")
            self.signals.finished.emit(self.job_key, result)
        except Exception as exc:
            self.signals.error.emit(self.job_key, str(exc))
