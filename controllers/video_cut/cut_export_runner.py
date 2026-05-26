from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from controllers.video_cut.result_formatter import (
    format_cut_details,
    format_validation_error,
    start_status,
)
from schemas.video_cut_schema import VideoCutRequest, VideoCutSegment


@dataclass(frozen=True)
class CutExportCallbacks:
    on_busy: Callable[[bool], None]
    on_status: Callable[[str], None]
    on_progress_value: Callable[[int], None]
    on_error: Callable[[str], None]
    on_details: Callable[[str], None]
    on_warning: Callable[[str], None]
    on_started: Callable[[int], None]
    on_finished: Callable[[str], None]
    on_failed: Callable[[str], None]
    on_progress: Callable[[float], None]


class CutExportRunner:
    def __init__(self, thread_pool, job_registry, worker_factory, output_preferences):
        self._thread_pool = thread_pool
        self._job_registry = job_registry
        self._worker_factory = worker_factory
        self._output_preferences = output_preferences
        self._workers = {}
        self._callbacks: dict[str, CutExportCallbacks] = {}

    def start(
        self,
        input_path: str,
        segments: list[dict],
        output_dir: str,
        export_mode: str,
        callbacks: CutExportCallbacks,
    ) -> bool:
        try:
            input_file = Path(input_path)
            resolved_output_dir = self._output_preferences.resolve_output_dir(input_file, output_dir)
            request = VideoCutRequest(
                input_path=input_file,
                output_dir=resolved_output_dir,
                segments=[VideoCutSegment.model_validate(segment) for segment in segments],
                export_mode=export_mode or "remove_intervals",
            )
        except (ValidationError, ValueError) as exc:
            error_message = format_validation_error(exc)
            callbacks.on_error(error_message)
            callbacks.on_status("Video export failed")
            callbacks.on_failed(error_message)
            return False

        job_key = f"video_cut:{request.input_path}:{request.export_mode}:{request.cut_mode}:{len(request.segments)}"
        if not self._job_registry.try_start(job_key):
            callbacks.on_status("This video export is already running.")
            return False

        self._callbacks[job_key] = callbacks
        self._output_preferences.remember(request.output_dir, str(request.export_mode))
        callbacks.on_busy(True)
        callbacks.on_error("")
        callbacks.on_warning("")
        callbacks.on_progress_value(0)
        callbacks.on_status(start_status(request.export_mode))

        worker = self._worker_factory(job_key=job_key, request_data=request.model_dump(mode="json"))
        self._workers[job_key] = worker
        worker.signals.progress.connect(self.handle_progress)
        worker.signals.finished.connect(self.handle_finished)
        worker.signals.error.connect(self.handle_error)
        callbacks.on_started(0)
        self._thread_pool.start(worker)
        return True

    def handle_progress(self, job_key: str, percentage: int, message: str) -> None:
        if not self._job_registry.is_running(job_key):
            return

        callbacks = self._callbacks.get(job_key)
        if not callbacks:
            return

        callbacks.on_progress_value(percentage)
        callbacks.on_status(message)
        callbacks.on_progress(float(percentage))

    def handle_finished(self, job_key: str, result) -> None:
        self._job_registry.finish(job_key)
        self._workers.pop(job_key, None)
        callbacks = self._callbacks.pop(job_key, None)
        if not callbacks:
            return

        result_payload = result.get("result", {}) if isinstance(result, dict) else {}
        output_paths = result_payload.get("output_paths", []) if isinstance(result_payload, dict) else []
        warning = str(result_payload.get("duration_warning") or "") if isinstance(result_payload, dict) else ""
        message = f"Video export completed: {len(output_paths)} output(s)"
        callbacks.on_progress_value(100)
        callbacks.on_status(message)
        callbacks.on_warning(warning)
        callbacks.on_details(format_cut_details(result_payload))
        callbacks.on_busy(False)
        callbacks.on_finished(message)

    def handle_error(self, job_key: str, error_message: str) -> None:
        self._job_registry.finish(job_key)
        self._workers.pop(job_key, None)
        callbacks = self._callbacks.pop(job_key, None)
        if not callbacks:
            return

        callbacks.on_error(error_message)
        callbacks.on_status("Video export failed")
        callbacks.on_busy(False)
        callbacks.on_failed(error_message)
