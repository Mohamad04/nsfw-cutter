from pathlib import Path

from controllers.video_cut.cut_export_runner import CutExportCallbacks
from controllers.video_cut.result_formatter import format_cut_details


class SmartCuttingExportRunner:
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
            if not input_file.is_file():
                raise ValueError(f"Input video does not exist: {input_file}")
            if not segments:
                raise ValueError("At least one cut segment is required.")
            resolved_output_dir = self._output_preferences.resolve_output_dir(input_file, output_dir)
        except ValueError as exc:
            error_message = str(exc)
            callbacks.on_error(error_message)
            callbacks.on_status("Video export failed")
            callbacks.on_failed(error_message)
            return False

        job_key = f"smart_cut:{input_file}:{export_mode}:{len(segments)}"
        if not self._job_registry.try_start(job_key):
            callbacks.on_status("This Smart Cutting export is already running.")
            return False

        request_data = {
            "input_path": str(input_file),
            "output_dir": str(resolved_output_dir),
            "segments": segments,
            "export_mode": export_mode or "remove_intervals",
            "cut_mode": "smart_cutting",
        }
        self._callbacks[job_key] = callbacks
        self._output_preferences.remember(resolved_output_dir, str(export_mode or "remove_intervals"))
        callbacks.on_busy(True)
        callbacks.on_error("")
        callbacks.on_warning("")
        callbacks.on_progress_value(0)
        callbacks.on_status("Preparing Smart Cutting export")

        worker = self._worker_factory(job_key=job_key, request_data=request_data)
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
        subtitles = result_payload.get("subtitles", []) if isinstance(result_payload, dict) else []
        warning = _subtitle_warning(subtitles)
        message = f"Smart Cutting export completed: {len(output_paths)} output(s)"
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


def _subtitle_warning(subtitles: list[dict]) -> str:
    warnings = [
        str(item.get("message"))
        for item in subtitles
        if isinstance(item, dict) and item.get("status") in {"warning", "skipped"}
    ]
    return "\n".join(message for message in warnings if message)

