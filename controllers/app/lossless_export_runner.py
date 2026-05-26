from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExportCallbacks:
    on_busy: Callable[[bool], None]
    on_progress: Callable[[int], None]
    on_status: Callable[[str], None]


class LosslessExportRunner:
    def __init__(self, thread_pool, job_registry, worker_factory):
        self._thread_pool = thread_pool
        self._job_registry = job_registry
        self._worker_factory = worker_factory
        self._active_workers = {}
        self._callbacks: dict[str, ExportCallbacks] = {}

    def start(self, input_path: str, output_path: str, callbacks: ExportCallbacks) -> bool:
        job_key = f"export:{input_path}:{output_path}"
        if not self._job_registry.try_start(job_key):
            callbacks.on_status("This export is already running.")
            return False

        self._callbacks[job_key] = callbacks
        callbacks.on_busy(True)
        callbacks.on_progress(0)
        callbacks.on_status("Preparing export...")

        worker = self._worker_factory(
            job_key=job_key,
            input_path=input_path,
            output_path=output_path,
        )
        self._active_workers[job_key] = worker
        worker.signals.progress.connect(self.handle_progress)
        worker.signals.finished.connect(self.handle_finished)
        worker.signals.error.connect(self.handle_error)

        self._thread_pool.start(worker)
        return True

    def handle_progress(self, job_key: str, percentage: int, message: str) -> None:
        if not self._job_registry.is_running(job_key):
            return

        callbacks = self._callbacks.get(job_key)
        if not callbacks:
            return

        callbacks.on_progress(percentage)
        callbacks.on_status(message)

    def handle_finished(self, job_key: str, result) -> None:
        self._job_registry.finish(job_key)
        self._active_workers.pop(job_key, None)
        callbacks = self._callbacks.pop(job_key, None)
        if not callbacks:
            return

        callbacks.on_progress(100)
        callbacks.on_status(f"Export completed: {result}")
        callbacks.on_busy(False)

    def handle_error(self, job_key: str, error_message: str) -> None:
        self._job_registry.finish(job_key)
        self._active_workers.pop(job_key, None)
        callbacks = self._callbacks.pop(job_key, None)
        if not callbacks:
            return

        callbacks.on_status(f"Export failed: {error_message}")
        callbacks.on_busy(False)
