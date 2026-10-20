"""One benchmark attempt in one fresh process: python -m evaluation.benchmark.worker SPEC_JSON.

The unchanged production AnalysisPipeline runs through the pilot's delegating observers, with a private
cache and force_reanalysis. The parent requests cancellation by creating the attempt's "cancel" file.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from time import perf_counter

from evaluation.benchmark.atomic import write_atomic
from evaluation.pilot.manifest import file_digest

# Exact production warnings (services/analysis/text_evidence.py) that mean Whisper did not run on CUDA.
WHISPER_CPU_MARKERS = ("CUDA Whisper initialization failed", "CUDA Whisper inference failed",
                       "CUDA is unavailable; Whisper", "Whisper is using the slow CPU backend")
TEXT_NOT_APPLICABLE = "Text evidence not applicable"
TEXT_UNAVAILABLE = "Text/audio evidence is unavailable"


def whisper_backend(warnings: list[str]) -> str:
    if any(marker in w for w in warnings for marker in WHISPER_CPU_MARKERS):
        return "cpu_fallback"
    if any(w.startswith(TEXT_UNAVAILABLE) for w in warnings):
        return "unavailable"
    if any(w.startswith(TEXT_NOT_APPLICABLE) for w in warnings):
        return "not_applicable"
    return "cuda_float16"


def stage_seconds(journal_path: Path):
    """First-to-last progress timestamp per pipeline stage (structured events only)."""
    spans = {}
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("kind") == "progress" and entry.get("stage"):
            start, _ = spans.get(entry["stage"], (entry["elapsed_seconds"], None))
            spans[entry["stage"]] = (start, entry["elapsed_seconds"])
    return {stage: round(end - start, 3) for stage, (start, end) in spans.items()}


def loaded_runtime_libraries():
    try:
        import psutil
        paths = {m.path for m in psutil.Process().memory_maps()}
    except Exception:  # noqa: BLE001 - provenance only
        return None
    return sorted(p for p in paths if Path(p).name.lower().startswith(("cublas", "cudnn", "ctranslate2", "cudart")))


def _watch_cancel(flag: Path, token, stop: threading.Event):
    while not stop.wait(0.5):
        if flag.exists():
            token.cancel()
            return


def run_attempt(spec_path: Path, *, pipeline_factory=None):
    from evaluation.pilot.observability import Journal, PrivateEvaluationCache
    from evaluation.pilot.runner import offline_environment, production_pipeline
    from evaluation.technical.benchmark import frozen_settings
    from services.analysis.cancellation import AnalysisCancelled, CancellationToken
    from services.analysis.contracts import AnalysisRunRequest

    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    directory = Path(spec["attempt_dir"])
    summary = {"item_id": spec["item_id"], "config": spec["config"], "status": "failed", "error_type": "",
               "whisper_backend": None, "stage_seconds": {}, "pipeline_seconds": None}
    started = perf_counter()
    journal = Journal(directory / "observations.jsonl")
    token, stop = CancellationToken(), threading.Event()
    watcher = threading.Thread(target=_watch_cancel, args=(directory / "cancel", token, stop), daemon=True)
    watcher.start()
    try:
        if spec["preload_whisper_cuda12"]:
            from evaluation.benchmark.media import enable_whisper_cuda12_cublas
            handles = enable_whisper_cuda12_cublas()  # noqa: F841 - keep the modules loaded
            import torch
            # Bind PyTorch's own cuDNN 9.20 before CTranslate2 loads its cudnn64_9 shim (same file name).
            torch.cuda.init()
        if file_digest(Path(spec["input_path"]), cancellation=token) != spec["input_sha256"]:
            raise ValueError("input_sha256_mismatch")
        settings = frozen_settings()
        factory = pipeline_factory or production_pipeline
        with offline_environment():
            pipeline = factory(PrivateEvaluationCache(directory / "cache"), journal)
            pipeline_start = perf_counter()
            record = pipeline.run(AnalysisRunRequest(video_path=Path(spec["input_path"]), settings=settings,
                                                     force_reanalysis=True, selected_subtitle=None),
                                  cancellation=token, event_callback=journal.progress, job_id=directory.name)
            summary["pipeline_seconds"] = perf_counter() - pipeline_start
        write_atomic(directory / "record.json", record.model_dump(mode="json"))
        if (record.status.value == "running" or record.settings != settings.model_dump(mode="json")
                or record.video_fingerprint != "sha256:" + spec["input_sha256"]):
            raise ValueError("record_identity_or_configuration_mismatch")
        summary["whisper_backend"] = backend = whisper_backend(record.warnings)
        summary["status"] = record.status.value
        if spec["config"] == "A2" and backend in ("cpu_fallback", "unavailable"):
            summary.update(status="failed", error_type=f"whisper_{backend}")
        elif spec["config"] == "A1" and backend != "not_applicable":
            summary.update(status="failed", error_type="a1_text_branch_ran")
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - recorded as a typed status
        cancelled = isinstance(exc, (AnalysisCancelled, KeyboardInterrupt)) or token.is_cancelled
        summary.update(status="cancelled" if cancelled else "failed",
                       error_type=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        journal.emit("runner_failure", error_type=type(exc).__name__)
    finally:
        stop.set()
        journal.close()
        summary["stage_seconds"] = stage_seconds(directory / "observations.jsonl")
        summary["worker_seconds"] = perf_counter() - started
        summary["reliability"] = journal.reliability()
        summary["loaded_runtime_libraries"] = loaded_runtime_libraries()
        write_atomic(directory / "summary.json", summary)
    return summary


if __name__ == "__main__":
    result = run_attempt(Path(sys.argv[1]))
    sys.exit(0 if result["status"] == "completed" else 2)
