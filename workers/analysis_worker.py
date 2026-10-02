from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable, Slot

from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import AnalysisRunRequest
from services.workflows.analysis_service import AnalysisService
from workers.worker_signals import WorkerSignals

logger = logging.getLogger(__name__)


class AnalysisWorker(QRunnable):
    def __init__(
        self,
        job_token: str,
        request: AnalysisRunRequest,
        cancellation: CancellationToken | None = None,
        analysis_service=None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.job_token = job_token
        self.request = request
        self.input_path = str(request.video_path)
        self.cancellation = cancellation or CancellationToken()
        self.analysis_service = analysis_service
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancellation.cancel()

    @Slot()
    def run(self) -> None:
        try:
            service = self.analysis_service or AnalysisService()
            result = service.analyze(
                self.request,
                self.cancellation,
                progress_callback=lambda percent, message: self._emit_progress(
                    percent,
                    message,
                ),
                event_callback=self._emit_event,
                job_id=self.job_token,
            )
            self.signals.finished.emit(self.job_token, result)
        except Exception as exc:
            logger.exception("Unexpected analysis worker failure")
            self._emit_error(str(exc))

    def _emit_progress(self, percent: int, message: str) -> None:
        try:
            self.signals.progress.emit(self.job_token, int(percent), str(message))
        except RuntimeError:
            logger.info("Dropping analysis progress after Qt shutdown")

    def _emit_error(self, message: str) -> None:
        try:
            self.signals.error.emit(self.job_token, str(message))
        except RuntimeError:
            logger.info("Dropping analysis failure after Qt shutdown")

    def _emit_event(self, event) -> None:
        try:
            payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else event
            self.signals.analysisEvent.emit(self.job_token, payload)
        except RuntimeError:
            logger.info("Dropping analysis event after Qt shutdown")
