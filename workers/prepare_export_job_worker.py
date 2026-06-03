from PySide6.QtCore import QRunnable, Slot

from services.workflows.backend_pipeline_service import prepare_export_job_pipeline
from workers.worker_signals import WorkerSignals


class PrepareExportJobWorker(QRunnable):
    def __init__(self, job_key: str, input_path: str, output_path: str = "", pipeline=None):
        super().__init__()
        self.job_key = job_key
        self.input_path = input_path
        self.output_path = output_path or None
        self.pipeline = pipeline or prepare_export_job_pipeline
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.progress.emit(self.job_key, 0, "Starting backend preparation")
            result = self.pipeline(
                self.input_path,
                self.output_path,
                progress_callback=lambda percent, message: self.signals.progress.emit(
                    self.job_key,
                    percent,
                    message,
                ),
            )
            self.signals.progress.emit(self.job_key, 100, "Preparation completed")
            self.signals.finished.emit(self.job_key, result)
        except Exception as exc:
            self.signals.error.emit(self.job_key, str(exc))
