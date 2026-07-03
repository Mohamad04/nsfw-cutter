from PySide6.QtCore import QRunnable, Slot

from services.export.smart_cutting_export_service import SmartCuttingExportService
from workers.worker_signals import WorkerSignals


def run_smart_cutting_job(request_data: dict, progress_callback=None) -> dict:
    return SmartCuttingExportService().export(request_data, progress_callback=progress_callback)


class SmartCuttingWorker(QRunnable):
    def __init__(self, job_key: str, request_data: dict, pipeline=None):
        super().__init__()
        self.job_key = job_key
        self.request_data = request_data
        self.pipeline = pipeline or run_smart_cutting_job
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
            self.signals.progress.emit(self.job_key, 100, "Smart Cutting export completed")
            self.signals.finished.emit(self.job_key, result)
        except Exception as exc:
            self.signals.error.emit(self.job_key, str(exc))

