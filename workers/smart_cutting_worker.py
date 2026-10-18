import logging

from PySide6.QtCore import QRunnable, Slot

from services.export.smart_cutting_export_service import SmartCuttingExportService
from services.infrastructure.ffmpeg.bounded_runner import (
    BoundedProcessRunner,
    ExportCancellationToken,
    ExportCancelledError,
)
from services.user_errors import is_cancellation, technical_details, user_message
from workers.worker_signals import WorkerSignals


logger = logging.getLogger(__name__)


def run_smart_cutting_job(request_data: dict, progress_callback=None, cancel_token=None) -> dict:
    runner = BoundedProcessRunner(cancel_token=cancel_token)
    return SmartCuttingExportService(process_runner=runner).export(request_data, progress_callback=progress_callback)


class SmartCuttingWorker(QRunnable):
    def __init__(self, job_key: str, request_data: dict, pipeline=None):
        super().__init__()
        self.job_key = job_key
        self.request_data = request_data
        self.pipeline = pipeline or run_smart_cutting_job
        self.cancel_token = ExportCancellationToken()
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancel_token.cancel()

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
                cancel_token=self.cancel_token,
            )
            self.signals.progress.emit(self.job_key, 100, "Smart Cutting export completed")
            self.signals.finished.emit(self.job_key, result)
        except ExportCancelledError as exc:
            self.signals.cancelled.emit(self.job_key, str(exc))
        except Exception as exc:
            if is_cancellation(exc):
                self.signals.cancelled.emit(self.job_key, user_message(exc))
                return
            logger.error("Smart Cutting export failed: %s\n%s", self.job_key, technical_details(exc), exc_info=exc)
            self.signals.error.emit(self.job_key, user_message(exc))
