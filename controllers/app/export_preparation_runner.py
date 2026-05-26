from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ExportPreparationCallbacks:
    on_busy: Callable[[bool], None]
    on_progress: Callable[[int], None]
    on_status: Callable[[str], None]
    on_job_id: Callable[[str], None]
    on_json_path: Callable[[str], None]


class ExportPreparationRunner:
    def __init__(self, thread_pool, job_registry, worker_factory):
        self._thread_pool = thread_pool
        self._job_registry = job_registry
        self._worker_factory = worker_factory
        self._active_workers = {}
        self._callbacks: dict[str, ExportPreparationCallbacks] = {}

    def start(
        self,
        video_path: str,
        output_path: str,
        callbacks: ExportPreparationCallbacks,
    ) -> bool:
        job_key = f"prepare_export:{video_path}:{output_path}"
        if not self._job_registry.try_start(job_key):
            callbacks.on_status("This backend preparation is already running.")
            return False

        self._callbacks[job_key] = callbacks
        callbacks.on_busy(True)
        callbacks.on_progress(0)
        callbacks.on_status("Starting backend preparation")

        worker = self._worker_factory(
            job_key=job_key,
            input_path=video_path,
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

        export_job = result.get("export_job", {}) if isinstance(result, dict) else {}
        artifacts = result.get("json_artifacts", {}) if isinstance(result, dict) else {}
        callbacks.on_progress(100)
        callbacks.on_status("Preparation completed")
        callbacks.on_job_id(export_job.get("job_id", ""))
        callbacks.on_json_path(artifacts.get("export_job_json_path", ""))
        callbacks.on_busy(False)

    def handle_error(self, job_key: str, error_message: str) -> None:
        self._job_registry.finish(job_key)
        self._active_workers.pop(job_key, None)
        callbacks = self._callbacks.pop(job_key, None)
        if not callbacks:
            return

        callbacks.on_status(f"Preparation failed: {error_message}")
        callbacks.on_busy(False)
