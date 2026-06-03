import logging
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QRunnable, Slot

from services.subtitles.processing_service import SubtitleService
from workers.worker_signals import WorkerSignals


logger = logging.getLogger(__name__)


class SubtitleDiscoveryWorker(QRunnable):
    def __init__(
        self,
        job_token: str,
        input_path: str | Path,
        subtitle_service: SubtitleService,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.job_token = job_token
        self.input_path = str(input_path)
        self.subtitle_service = subtitle_service
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        started_at = perf_counter()
        logger.info("[Subtitles] Starting discovery for: %s", self.input_path)
        try:
            candidates = self.subtitle_service.discover_subtitles(self.input_path)
        except Exception as exc:
            self._emit_error(str(exc))
            return

        embedded_count = sum(1 for candidate in candidates if candidate.get("source") == "embedded")
        external_count = sum(1 for candidate in candidates if candidate.get("source") == "external")
        if candidates:
            logger.info(
                "[Subtitles] Discovery completed: embedded=%s, external=%s, elapsed=%.3fs",
                embedded_count,
                external_count,
                perf_counter() - started_at,
            )
        else:
            logger.info("[Subtitles] No subtitles detected for: %s", self.input_path)

        try:
            self.signals.finished.emit(
                self.job_token,
                {
                    "input_path": self.input_path,
                    "candidates": candidates,
                    "elapsed_seconds": perf_counter() - started_at,
                },
            )
        except RuntimeError:
            logger.info(
                "[Subtitles] Dropping completed result after Qt shutdown: %s / job=%s",
                self.input_path,
                self.job_token,
            )

    def _emit_error(self, error_message: str) -> None:
        logger.error(
            "[Subtitles] Discovery failed: %s, error=%s",
            self.input_path,
            error_message,
        )
        try:
            self.signals.error.emit(self.job_token, error_message)
        except RuntimeError:
            logger.info(
                "[Subtitles] Dropping failure after Qt shutdown: %s / job=%s / error=%s",
                self.input_path,
                self.job_token,
                error_message,
            )
