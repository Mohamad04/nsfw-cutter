import logging
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QRunnable, Slot

from services.editing.keyframe_service import KeyframeService
from workers.worker_signals import WorkerSignals


logger = logging.getLogger(__name__)


class KeyframeIndexWorker(QRunnable):
    def __init__(
        self,
        job_token: str,
        input_path: str | Path,
        keyframe_service: KeyframeService,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.job_token = job_token
        self.input_path = str(input_path)
        self.keyframe_service = keyframe_service
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        started_at = perf_counter()
        logger.info(
            "[Keyframes] Indexing started: %s / job=%s",
            self.input_path,
            self.job_token,
        )
        try:
            keyframes = self.keyframe_service.extract_keyframes(self.input_path)
        except Exception as exc:
            self._emit_error(str(exc))
            return

        try:
            self.signals.finished.emit(
                self.job_token,
                {
                    "input_path": self.input_path,
                    "keyframes": keyframes,
                    "elapsed_seconds": perf_counter() - started_at,
                },
            )
        except RuntimeError:
            logger.info(
                "[Keyframes] Dropping completed result after Qt shutdown: %s / job=%s",
                self.input_path,
                self.job_token,
            )

    def _emit_error(self, error_message: str) -> None:
        try:
            self.signals.error.emit(self.job_token, error_message)
        except RuntimeError:
            logger.info(
                "[Keyframes] Dropping failure after Qt shutdown: %s / job=%s / error=%s",
                self.input_path,
                self.job_token,
                error_message,
            )
