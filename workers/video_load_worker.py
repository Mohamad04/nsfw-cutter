import logging

from PySide6.QtCore import QRunnable, Slot

from services.infrastructure.ffmpeg.bounded_runner import ExportCancellationToken, ExportCancelledError
from services.user_errors import is_cancellation, technical_details, user_message
from services.user_messages import localized_text, translated
from workers.worker_signals import WorkerSignals


logger = logging.getLogger(__name__)


class VideoLoadWorker(QRunnable):
    """Validates the selected file(s) with ffprobe off the GUI thread.

    It only checks files: the controller registers and loads the first valid one on the GUI thread,
    once it knows the result is still wanted. ``finished`` carries one outcome per file, in order:
    ``{"path", "listing"}`` for a valid file, ``{"path", "error"}`` for a rejected one.
    """

    def __init__(self, job_token: str, file_paths: list[str], validate):
        super().__init__()
        self.setAutoDelete(True)
        self.job_token = job_token
        self.file_paths = [str(path) for path in file_paths]
        self.validate = validate
        self.cancel_token = ExportCancellationToken()
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self):
        outcomes = []
        for file_path in self.file_paths:
            if self.cancel_token.is_cancelled:
                self._emit("cancelled", "Video loading was cancelled.")
                return
            try:
                outcomes.append({"path": file_path, "listing": self.validate(file_path, self.cancel_token)})
            except ExportCancelledError:
                self._emit("cancelled", "Video loading was cancelled.")
                return
            except ValueError as exc:
                logger.warning("Video not loaded: %s\n%s", file_path, technical_details(exc))
                outcomes.append({"path": file_path, "error": localized_text(exc)})
            except Exception as exc:
                if is_cancellation(exc):
                    self._emit("cancelled", "Video loading was cancelled.")
                    return
                logger.exception("Unexpected error while checking video: %s\n%s", file_path, technical_details(exc))
                outcomes.append({"path": file_path,
                                 "error": translated("media.could_not_open", reason=user_message(exc))})
        self._emit("finished", outcomes)

    def _emit(self, signal_name: str, payload) -> None:
        try:
            getattr(self.signals, signal_name).emit(self.job_token, payload)
        except RuntimeError:
            logger.info("Dropping video load %s after Qt shutdown: job=%s", signal_name, self.job_token)
