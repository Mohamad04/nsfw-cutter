"""Opt-in execution around the unchanged AnalysisPipeline.run entry point."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from evaluation.pilot.manifest import canonical_digest, clip_path, file_digest

ROOT = Path(__file__).resolve().parents[2]
OFFLINE_ENV = {"NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD": "0", "HF_HUB_OFFLINE": "1",
               "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "NSFW_CUTTER_LANGSMITH_TRACING": "0",
               "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}


def write_new(path, value):
    """Exclusive creation: neither attempts nor scoring outputs overwrite files."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


@contextmanager
def offline_environment():
    old = {key: os.environ.get(key) for key in OFFLINE_ENV}
    os.environ.update(OFFLINE_ENV)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def resolve_settings(app_settings_path=None, overrides=None):
    # Reuse the exact application mapping, not a copied list of defaults.
    # Lazy import: manifest validation/scoring never requires Qt or AI packages.
    from controllers.app.app_controller import _analysis_settings_from_app_settings
    from models.app_settings import AppSettings
    from services.analysis.contracts import AnalysisSettings
    from core.paths import get_settings_path

    path = Path(app_settings_path) if app_settings_path else get_settings_path()
    if app_settings_path or path.is_file():
        app = AppSettings.model_validate_json(path.read_text(encoding="utf-8-sig"))
        origin = {"kind": "file", "sha256": file_digest(path), "path": str(path.resolve())}
    else:
        app = AppSettings()
        origin = {"kind": "application_defaults"}
    base = _analysis_settings_from_app_settings(app)
    settings = AnalysisSettings.model_validate({**base.model_dump(), **(overrides or {})})
    immutable = ("provider", "model_id", "model_revision", "prefilter_model_id", "prefilter_model_revision",
                 "whisper_model_id", "whisper_model_revision", "settings_version",
                 "sampling_profile_revision", "prompt_schema_revision")
    if any(getattr(settings, key) != getattr(base, key) for key in immutable):
        raise ValueError("Pilot overrides cannot change production models, pinned revisions or schema/profile versions")
    return settings, {"application_settings": origin, "overrides": overrides or {},
                      "base_analysis_settings": base.model_dump(mode="json")}


def effective_settings(settings):
    from services.analysis.providers.qwen import _MAX_GENERATION_TOKENS, _MAX_REPAIR_TOKENS
    return {"settings": settings.model_dump(mode="json"),
            "resolved_coarse_sample_rate_fps": settings.resolved_coarse_sample_rate_fps,
            "resolved_dense_sample_rate_fps": settings.resolved_dense_sample_rate_fps,
            "resolved_marqo_gate": settings.resolved_prefilter_threshold,
            "effective_max_new_tokens": min(settings.max_new_tokens, _MAX_GENERATION_TOKENS),
            "effective_repair_max_new_tokens": min(settings.repair_max_new_tokens, _MAX_REPAIR_TOKENS),
            "selected_subtitle": None, "text_policy": "production audio/Whisper fallback",
            "force_reanalysis": True}


def _command(command):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=5, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def environment_metadata():
    versions = {}
    for name in ("pydantic", "torch", "torchvision", "transformers", "huggingface-hub",
                 "accelerate", "bitsandbytes", "faster-whisper", "ctranslate2", "Pillow",
                 "langgraph", "langchain-core", "langsmith", "PySide6", "numpy", "timm",
                 "qwen-vl-utils", "lm-format-enforcer", "psutil", "pysubs2", "platformdirs"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    from services.infrastructure.ffmpeg.paths import get_ffmpeg_path
    try:
        ffmpeg_path = str(get_ffmpeg_path())
        ffmpeg = _command([ffmpeg_path, "-version"])
    except RuntimeError:
        ffmpeg_path, ffmpeg = None, None
    try:
        import psutil
        ram_bytes = psutil.virtual_memory().total
    except (ImportError, OSError):
        ram_bytes = None
    # Includes untracked evaluation code without retaining source/private paths.
    source_hashes = {}
    for directory in ("evaluation/pilot", "services", "core", "models", "controllers/app", "workers"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            source_hashes[path.relative_to(ROOT).as_posix()] = file_digest(path)
    return {"git_commit": _command(["git", "rev-parse", "HEAD"]),
            "git_status": _command(["git", "status", "--porcelain"]),
            "source_sha256": source_hashes, "python": sys.version,
            "dependencies": versions, "ffmpeg_path": ffmpeg_path, "ffmpeg_version": ffmpeg,
            "hardware": {"platform": platform.platform(), "machine": platform.machine(),
                         "processor": platform.processor(), "cpu_count": os.cpu_count(), "ram_bytes": ram_bytes,
                         "gpu": _command(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                                          "--format=csv,noheader"])},
            "offline_environment": OFFLINE_ENV,
            "runtime_environment": {key: os.environ.get(key) for key in (
                "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                "CUBLAS_WORKSPACE_CONFIG", "PYTORCH_CUDA_ALLOC_CONF", "NSFW_CUTTER_MODEL_CACHE")},
            "determinism": "production greedy generation; GPU bitwise determinism not guaranteed"}


def production_pipeline(cache, journal):
    from services.analysis.pipeline import AnalysisPipeline, AnalysisServices
    from services.analysis.tracing import OptionalLangSmithTracer
    from evaluation.pilot.observability import attach_observers
    # Construct defaults FIRST: injecting Qwen into AnalysisServices would disable
    # its default Marqo branch. Wrapping the existing services preserves both.
    services = AnalysisServices(cache=cache, tracer=OptionalLangSmithTracer(enabled=False))
    return AnalysisPipeline(attach_observers(services, journal))


def run_attempt(manifest, manifest_path, clip, settings, output_root, *,
                settings_origin=None, pipeline_factory=None, metadata_factory=None):
    """One clip = one immutable attempt directory; dependencies injectable in tests."""
    from evaluation.pilot.observability import Journal, PrivateEvaluationCache
    from services.analysis.cancellation import CancellationToken
    from services.analysis.contracts import AnalysisRunRequest

    manifest.require_ready()
    if manifest.synthetic and pipeline_factory is None:
        raise ValueError("Synthetic manifests require a mocked pipeline factory")
    if clip not in manifest.clips:
        raise ValueError("Clip is not part of manifest")
    attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex
    directory = Path(output_root) / attempt_id
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = manifest.model_dump(mode="json")
    write_new(directory / "manifest.json", snapshot)
    config = effective_settings(settings)
    write_new(directory / "config.json", {"schema_version": 1, **config,
                                         "origin": settings_origin or {}})
    started_at = datetime.now(UTC).isoformat()
    write_new(directory / "attempt.json", {"schema_version": 1, "attempt_id": attempt_id,
              "clip_id": clip.clip_id, "split": clip.split, "started_at": started_at,
              "manifest_sha256": canonical_digest(snapshot), "configuration_sha256": canonical_digest(config),
              "cache_policy": "fresh isolated per-attempt analysis cache; no resume; model files reused; OS cache uncontrolled",
              "status": "running"})
    journal = Journal(directory / "observations.jsonl")
    cancellation = CancellationToken()
    previous_handler = None
    if threading.current_thread() is threading.main_thread():
        previous_handler = signal.signal(signal.SIGINT, lambda *_: cancellation.cancel())
    started, pipeline_started = perf_counter(), None
    record, error_type, error_code, status = None, None, None, "failed"
    pipeline_seconds, record_saved = None, False
    try:
        with offline_environment():
            write_new(directory / "environment.json", {
                **(metadata_factory or environment_metadata)(), "schema_version": 1})
            video = clip_path(clip, Path(manifest_path))
            if file_digest(video, cancellation=cancellation) != clip.sha256:
                error_code = "clip_sha256_mismatch"
                raise ValueError("clip SHA-256 mismatch")
            cancellation.raise_if_cancelled()
            cache = PrivateEvaluationCache(directory / "cache")
            pipeline = (pipeline_factory or production_pipeline)(cache, journal)
            pipeline_started = perf_counter()
            record = pipeline.run(AnalysisRunRequest(video_path=video, settings=settings,
                                  selected_subtitle=None, force_reanalysis=True),
                                  cancellation=cancellation, event_callback=journal.progress, job_id=attempt_id)
            pipeline_seconds = perf_counter() - pipeline_started
            # Save THE RETURN VALUE, including partial/cancelled/failed records.
            write_new(directory / "record.json", record.model_dump(mode="json"))
            record_saved = True
            status = record.status.value
            journal.emit("final_suggestions", suggestions=[s.model_dump(mode="json", exclude={"reason"})
                                                           for s in record.suggestions])
            journal.emit("final_candidates", windows=[c.model_dump(mode="json") for c in record.candidate_windows])
            journal.emit("diagnostic_counts", warnings=len(record.warnings), failures=len(record.errors))
    except (Exception, KeyboardInterrupt) as exc:
        from services.analysis.cancellation import AnalysisCancelled
        status = "cancelled" if isinstance(exc, (AnalysisCancelled, KeyboardInterrupt)) else "failed"
        error_type = type(exc).__name__
        journal.emit("runner_failure", error_type=error_type, error_code=error_code)
    finally:
        wall = perf_counter() - started
        if previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)
        pipeline_elapsed = (pipeline_seconds if pipeline_seconds is not None
                            else perf_counter() - pipeline_started if pipeline_started is not None else None)
        summary = {"schema_version": 1, "attempt_id": attempt_id, "clip_id": clip.clip_id,
                   "status": status, "error_type": error_type, "error_code": error_code,
                   "finished_at": datetime.now(UTC).isoformat(),
                   "wall_seconds": wall, "pipeline_seconds": pipeline_elapsed,
                   "real_time_factor": pipeline_elapsed / clip.duration_seconds if pipeline_elapsed is not None else None,
                   "throughput_video_seconds_per_second": clip.duration_seconds / pipeline_elapsed if pipeline_elapsed else None,
                   "record_available": record_saved,
                   "record_sha256": file_digest(directory / "record.json") if record_saved else None,
                   "reliability": journal.reliability()}
        write_new(directory / "summary.json", summary)
        journal.close()
    return directory, summary
