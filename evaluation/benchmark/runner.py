"""Sequential, resumable benchmark campaign around the frozen pipeline (evaluation-only).

For each evaluable item (one independent source video at a time): verify the media SHA-256, prepare the
verified video-only copy for A1, then run A2 (original) and A1 (copy), each in a fresh worker process
(cold_process), in an alternating order. A0 is derived later from A2's recorded Marqo scores.

Campaign layout (all JSON written atomically, never overwritten):
  campaign.json                identity: manifest, pilot, configuration, frozen baseline, runtime, limits
  inputs/<item>.video-only.*   A1 inputs, with inputs/<item>.json identity records
  attempts/<UTC>_<item>_<config>_<uuid>/
      spec.json, observations.jsonl, record.json, summary.json   (worker)
      monitor.jsonl, monitor_summary.json, parent_summary.json   (parent; parent_summary only if it intervened)
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from evaluation.benchmark import versions
from evaluation.benchmark.atomic import write_atomic
from evaluation.benchmark.manifest import BenchmarkManifest, assert_disjoint_from_pilot, load_manifest, manifest_digest
from evaluation.benchmark.media import prepare_video_only_copy
from evaluation.benchmark.results import ResultsFile
from evaluation.pilot.manifest import canonical_digest, file_digest

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PIPELINE_VERSION = versions.DEFAULT_PIPELINE_VERSION
# Commit of the original experimental freeze (2026-10-19), the version of every unversioned campaign.
BASELINE = versions.PIPELINE_VERSIONS[versions.UNRECORDED_PIPELINE_VERSION]["commit"]
ANALYSIS_DIRS = versions.ANALYSIS_DIRS
CONFIGS = ("A2", "A1")
TERMINAL_OK = "completed"


@dataclass(frozen=True)
class Limits:
    min_available_bytes: int = int(2.5 * 2**30)
    min_commit_headroom_bytes: int = int(1.5 * 2**30)
    max_gpu_memory_mib: int = 7900
    gpu_breach_samples: int = 5
    attempt_timeout_seconds: float = 300.0
    cancel_grace_seconds: float = 60.0
    sample_interval_seconds: float = 1.0


# --------------------------------------------------------------------------- identity and provenance

def verify_identity(pipeline_version: str = DEFAULT_PIPELINE_VERSION):
    """Frozen analysis code must equal the commit of the pipeline version; returns runtime provenance."""
    from evaluation.pilot.runner import environment_metadata
    from evaluation.technical.benchmark import CONFIG_DIGEST, frozen_settings

    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    frozen = versions.version(pipeline_version)
    lineage = versions.verify_lineage(pipeline_version, git=git)
    subprocess.run(git + ["diff", "--exit-code", frozen["commit"], "--", *ANALYSIS_DIRS], cwd=ROOT, check=True,
                   capture_output=True)
    untracked = subprocess.run(git + ["ls-files", "--others", "--exclude-standard", "--", *ANALYSIS_DIRS],
                               cwd=ROOT, check=True, capture_output=True, text=True).stdout
    if untracked.strip():
        raise ValueError("untracked files in the frozen analysis code")
    if frozen["configuration_sha256"] != CONFIG_DIGEST:
        raise ValueError(f"{pipeline_version} ran with configuration {frozen['configuration_sha256'][:8]}, "
                         f"not the frozen configuration {CONFIG_DIGEST[:8]} of this checkout")
    settings = frozen_settings()
    env = environment_metadata()
    return {"commit": env["git_commit"], "frozen_baseline": frozen["commit"], "configuration_sha256": CONFIG_DIGEST,
            "pipeline_version": {"name": pipeline_version, "description": frozen["description"], **lineage},
            "model_revisions": {"qwen": f"{settings.model_id}@{settings.model_revision}",
                                "marqo": f"{settings.prefilter_model_id}@{settings.prefilter_model_revision}",
                                "whisper": f"{settings.whisper_model_id}@{settings.whisper_model_revision}"},
            "gpu": (env["hardware"].get("gpu") or "unknown"), "runtime_sha256": canonical_digest({
                "source": {k: v for k, v in env["source_sha256"].items() if k.startswith(ANALYSIS_DIRS)},
                "dependencies": env["dependencies"], "python": env["python"]}),
            "environment": env}


def evaluation_code_identity():
    """The benchmark harness itself is versioned per campaign (it may be uncommitted during development)."""
    files = {p.name: file_digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    dirty = subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", "status", "--porcelain", "--",
                            "evaluation"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"benchmark_sources_sha256": canonical_digest(files), "files": files,
            "uncommitted_evaluation_changes": bool(dirty)}


# --------------------------------------------------------------------------- resource monitoring

class _PerformanceInformation(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong)] + [(name, ctypes.c_size_t) for name in (
        "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache",
        "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")] + [
        (name, ctypes.c_ulong) for name in ("HandleCount", "ProcessCount", "ThreadCount")]


def commit_headroom_bytes():
    if os.name != "nt":
        return None
    info = _PerformanceInformation()
    info.cb = ctypes.sizeof(info)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        return None
    return (info.CommitLimit - info.CommitTotal) * info.PageSize


# psutil.Process objects keep the cpu_percent baseline between samples. They are keyed by (pid, creation
# time), not by pid: Windows reuses PIDs, and a cached object for an exited process whose PID now belongs
# to a new worker raises NoSuchProcess on every call (the 2026-10-20 campaign lost the process-tree
# samples of 22 attempts that way). Only members of the current tree are kept.
_PROCESSES = {}
_PRIMED = set()


def _identity(process):
    return process.pid, process.create_time()


def process_tree_usage(pid: int):
    """RSS and CPU of the worker process tree only (not system-wide), plus the reason when unmeasured.

    Returns (rss_bytes, cpu_percent, error); error is None when the tree was measured. CPU uses psutil's
    per-process convention: 100 = one fully busy logical CPU, so the tree can exceed 100; divide by the
    logical CPU count for a 0-100 % machine share. A process's first sample has no interval yet and is
    excluded; processes that exit between samples are skipped. Nothing is estimated when a sample fails.
    """
    import psutil
    try:
        root = psutil.Process(pid)
        members = {_identity(root): root}
        children = root.children(recursive=True)
    except psutil.Error as exc:
        return None, None, type(exc).__name__
    for child in children:
        try:
            members[_identity(child)] = child
        except psutil.Error:
            continue
    for stale in set(_PROCESSES) - set(members):
        del _PROCESSES[stale]
    _PRIMED.intersection_update(members)
    rss, cpu, measured = 0, 0.0, 0
    for key, member in members.items():
        process = _PROCESSES.setdefault(key, member)
        try:
            value = process.cpu_percent(None)
            rss += process.memory_info().rss
            if key in _PRIMED:
                cpu += value
                measured += 1
            _PRIMED.add(key)
        except psutil.Error:
            _PROCESSES.pop(key, None)
            _PRIMED.discard(key)
    if not rss:
        return None, None, "no_process_measured"
    return rss, (cpu if measured else None), None


def system_sample(pid: int):
    import psutil
    rss, cpu, error = process_tree_usage(pid)
    try:
        gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().split(",")
    except (OSError, subprocess.SubprocessError):
        gpu = []
    return {"process_tree_rss_bytes": rss, "process_tree_cpu_percent": cpu, "process_tree_error": error,
            "available_bytes": psutil.virtual_memory().available,
            "commit_headroom_bytes": commit_headroom_bytes(),
            "gpu_memory_mib": int(gpu[0]) if gpu and gpu[0].strip().isdigit() else None,
            "gpu_utilization_percent": int(gpu[1]) if len(gpu) > 1 and gpu[1].strip().isdigit() else None}


def breach(sample, limits: Limits, gpu_streak: int):
    if sample.get("available_bytes") is not None and sample["available_bytes"] < limits.min_available_bytes:
        return "resource_limit:available_memory", gpu_streak
    headroom = sample.get("commit_headroom_bytes")
    if headroom is not None and headroom < limits.min_commit_headroom_bytes:
        return "resource_limit:commit_headroom", gpu_streak
    gpu = sample.get("gpu_memory_mib")
    gpu_streak = gpu_streak + 1 if gpu is not None and gpu >= limits.max_gpu_memory_mib else 0
    if gpu_streak >= limits.gpu_breach_samples:
        return "resource_limit:gpu_memory", gpu_streak
    return None, gpu_streak


# --------------------------------------------------------------------------- one supervised attempt

def subprocess_launcher(spec_path: Path):
    return subprocess.Popen([sys.executable, "-m", "evaluation.benchmark.worker", str(spec_path)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=(spec_path.parent / "worker_stderr.log").open("x"))


def supervise(directory: Path, launcher, sampler, limits: Limits, clock=time.monotonic, sleep=time.sleep):
    handle = launcher(directory / "spec.json")
    started, reason, gpu_streak, cancel_at, peaks, samples = clock(), None, 0, None, {}, 0
    cpu_values, tree_errors = [], {}
    monitor = (directory / "monitor.jsonl").open("x", encoding="utf-8")
    try:
        while handle.poll() is None:
            sample = sampler(handle.pid)
            samples += 1
            monitor.write(json.dumps({"t": round(clock() - started, 2), **sample}) + "\n")
            monitor.flush()
            for key in ("process_tree_rss_bytes", "process_tree_cpu_percent", "gpu_memory_mib",
                        "gpu_utilization_percent"):
                if sample.get(key) is not None:
                    peaks[key] = max(peaks.get(key, 0), sample[key])
            if sample.get("process_tree_cpu_percent") is not None:
                cpu_values.append(sample["process_tree_cpu_percent"])
            if sample.get("process_tree_rss_bytes") is None:
                error = sample.get("process_tree_error") or "unknown"
                tree_errors[error] = tree_errors.get(error, 0) + 1
            for key in ("available_bytes", "commit_headroom_bytes"):
                if sample.get(key) is not None:
                    peaks[f"min_{key}"] = min(peaks.get(f"min_{key}", sample[key]), sample[key])
            if reason is None:
                found, gpu_streak = breach(sample, limits, gpu_streak)
                if found is None and clock() - started > limits.attempt_timeout_seconds:
                    found = "timeout"
                if found is not None:
                    reason, cancel_at = found, clock()
                    (directory / "cancel").touch()
            elif clock() - cancel_at > limits.cancel_grace_seconds:
                handle.kill()
                reason += "|killed_after_grace"
                break
            sleep(limits.sample_interval_seconds)
    except KeyboardInterrupt:
        reason = "interrupted_by_user"
        (directory / "cancel").touch()
        try:
            handle.wait(timeout=limits.cancel_grace_seconds)
        except Exception:  # noqa: BLE001
            handle.kill()
        raise
    finally:
        monitor.close()
        wall = clock() - started
        write_atomic(directory / "monitor_summary.json", {
            "wall_seconds": wall, "samples": samples, "sample_interval_seconds": limits.sample_interval_seconds,
            "intervention": reason, **peaks,
            "cpu": {"convention": "process tree only; 100 = one logical CPU fully busy",
                    "logical_cpus": os.cpu_count(), "valid_samples": len(cpu_values),
                    "peak_percent": max(cpu_values) if cpu_values else None,
                    "mean_percent": sum(cpu_values) / len(cpu_values) if cpu_values else None},
            # Unmeasured samples are reported, never filled in; resource limits use system-wide values.
            "process_tree_monitoring": {"samples_without_rss": sum(tree_errors.values()),
                                        "errors": tree_errors}})
        if reason is not None or not (directory / "summary.json").exists():
            write_atomic(directory / "parent_summary.json", {
                "intervention": reason or "worker_exited_without_summary",
                "status": "cancelled" if reason else "failed"})
    return attempt_status(directory)


def attempt_status(directory: Path):
    """Status of one attempt, combining worker and parent views; unknown endings count as failures."""
    worker = directory / "summary.json"
    parent = directory / "parent_summary.json"
    summary = json.loads(worker.read_text(encoding="utf-8")) if worker.exists() else None
    intervention = json.loads(parent.read_text(encoding="utf-8")) if parent.exists() else None
    if summary is None:
        status = intervention["status"] if intervention else "failed"
        return {"status": status, "error_type": (intervention or {}).get("intervention", "interrupted_unknown"),
                "summary": None}
    if intervention and intervention.get("intervention"):
        # The parent's reason (resource limit, timeout, interruption) is the cause; a worker that still
        # reported "completed" after an intervention is not trustworthy.
        status = "failed" if summary["status"] == "completed" else summary["status"]
        return {"status": status, "error_type": intervention["intervention"],
                "worker_error_type": summary.get("error_type", ""), "summary": summary}
    return {"status": summary["status"], "error_type": summary.get("error_type") or "", "summary": summary}


# --------------------------------------------------------------------------- campaign

def _attempts(campaign: Path):
    rows = {}
    for directory in sorted((campaign / "attempts").glob("*")):
        spec = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
        rows.setdefault((spec["item_id"], spec["config"]), []).append(directory)
    return rows


def _executed_input(record: Path, identity: dict) -> Path:
    """Absolute path of a prepared A1 input. The copy always lives beside its identity record, so records
    written with a working-directory-relative path (first smoke campaign) are resolved by file name."""
    stored = Path(identity["path"])
    return stored if stored.is_absolute() else (record.parent / stored.name).resolve()


def _prepare_inputs(campaign: Path, item, source: Path, prepare):
    record = campaign / "inputs" / f"{item.item_id}.json"
    if record.exists():
        identity = json.loads(record.read_text(encoding="utf-8"))
        path = _executed_input(record, identity)
        if file_digest(path) != identity["sha256"]:
            raise ValueError(f"{item.item_id}: prepared A1 input changed on disk")
        return {**identity, "path": str(path)}
    record.parent.mkdir(parents=True, exist_ok=True)
    target = (record.parent / f"{item.item_id}.video-only{source.suffix}").resolve()
    identity = {**prepare(source, target), "path": str(target), "file_name": target.name}
    if identity["derived_from_sha256"] != item.sha256:
        raise ValueError(f"{item.item_id}: A1 input was not derived from the manifest media")
    write_atomic(record, identity)
    return identity


def _checked_configs(configs):
    configs = tuple(configs)
    if not configs or len(set(configs)) != len(configs) or set(configs) - set(CONFIGS) or "A2" not in configs:
        raise ValueError(f"configs must be distinct members of {CONFIGS} and include A2 (A0 is derived from it)")
    return configs


def campaign_configs(identity: dict):
    """Campaigns created before the configs option ran both configurations and do not record them."""
    return tuple(identity.get("configs", CONFIGS))


def run(manifest_path: Path, media_root: Path, campaign: Path, pilot_manifest: Path, *, allow_inference=False,
        retry_incomplete=False, limits: Limits = Limits(), launcher=subprocess_launcher, sampler=system_sample,
        identity_factory=verify_identity, prepare=None, preload_whisper_cuda12=True, split="test",
        configs=CONFIGS, accept_partial=False, pipeline_version=DEFAULT_PIPELINE_VERSION):
    """configs=("A2",) runs only the original input, e.g. for a corpus without audio, where A1 would repeat A2.

    accept_partial=True records a "partial" attempt (the pipeline returned an incomplete analysis, e.g. no
    visual frame could be sampled) as that item's outcome and continues; it is neither retried nor dropped,
    and is reported as a technical failure. Failed or cancelled attempts still stop the campaign.
    """
    from evaluation.technical.benchmark import campaign_lock

    if not allow_inference:
        raise PermissionError("running models requires explicit --allow-inference")
    configs = _checked_configs(configs)
    campaign, media_root = Path(campaign).resolve(), Path(media_root).resolve()
    manifest = load_manifest(manifest_path)
    disjoint = assert_disjoint_from_pilot(manifest, pilot_manifest)
    items = manifest.evaluable(split)
    missing = [i.item_id for i in items if i.sha256 is None or i.file_name is None]
    if missing:
        raise ValueError("every evaluable item needs file_name and sha256 before inference: " + ", ".join(missing[:10]))
    if prepare is None:
        vendor = ROOT / "vendor" / "ffmpeg" / "bin"
        prepare = lambda s, t: prepare_video_only_copy(s, t, ffmpeg=vendor / "ffmpeg.exe",  # noqa: E731
                                                       ffprobe=vendor / "ffprobe.exe")
    identity = identity_factory(pipeline_version)
    campaign_identity = {"benchmark_id": manifest.benchmark_id, "manifest_digest": manifest_digest(manifest),
                         "pilot_manifest_digest": disjoint["pilot_manifest_digest"], "split": split,
                         **{k: identity[k] for k in ("commit", "frozen_baseline", "configuration_sha256",
                                                     "model_revisions", "gpu", "runtime_sha256")},
                         "limits": asdict(limits), "preload_whisper_cuda12": preload_whisper_cuda12,
                         "evaluation_code": evaluation_code_identity()}
    if configs != CONFIGS:
        # Recorded only when non-default, so the identity of existing two-configuration campaigns is unchanged.
        campaign_identity["configs"] = list(configs)
    if pipeline_version != versions.UNRECORDED_PIPELINE_VERSION:
        # Recorded for every version but the original freeze, whose campaigns predate the registry and must keep
        # their identity; frozen_baseline above already holds the version's commit.
        campaign_identity["pipeline_version"] = identity["pipeline_version"]
    campaign.mkdir(parents=True, exist_ok=True)
    with campaign_lock(campaign):
        marker = campaign / "campaign.json"
        if marker.exists():
            if json.loads(marker.read_text(encoding="utf-8")) != campaign_identity:
                raise ValueError("campaign identity changed (manifest, code, configuration or limits); "
                                 "use a new campaign directory")
        else:
            write_atomic(marker, campaign_identity)
            write_atomic(campaign / "environment.json", identity["environment"])
        accepted = (TERMINAL_OK, "partial") if accept_partial else (TERMINAL_OK,)
        latest = {key: attempt_status(dirs[-1]) for key, dirs in _attempts(campaign).items()}
        unfinished = sorted(f"{k[0]}/{k[1]}" for k, v in latest.items() if v["status"] not in accepted)
        if unfinished and not retry_incomplete:
            raise ValueError("incomplete attempts retained (" + ", ".join(unfinished[:10]) +
                             "); rerun with --retry-incomplete after review")
        for index, item in enumerate(items):
            source = (Path(media_root) / item.file_name).resolve()
            if file_digest(source) != item.sha256:
                raise ValueError(f"{item.item_id}: media SHA-256 does not match the manifest")
            a1 = None
            order = configs if index % 2 == 0 else tuple(reversed(configs))
            for config in order:
                if latest.get((item.item_id, config), {}).get("status") in accepted:
                    continue
                if config == "A1" and a1 is None:
                    a1 = _prepare_inputs(campaign, item, source, prepare)
                directory = campaign / "attempts" / (
                    f"{datetime.now(UTC):%Y%m%dT%H%M%S%f}_{item.item_id}_{config}_{uuid.uuid4().hex[:8]}")
                directory.mkdir(parents=True)
                input_path, input_sha = (source, item.sha256) if config == "A2" else (Path(a1["path"]), a1["sha256"])
                write_atomic(directory / "spec.json", {
                    "item_id": item.item_id, "group_id": item.group_id, "config": config,
                    "input_path": str(input_path), "input_sha256": input_sha, "attempt_dir": str(directory),
                    "campaign_manifest_digest": campaign_identity["manifest_digest"],
                    "preload_whisper_cuda12": preload_whisper_cuda12, "start_mode": "cold_process",
                    "accepted_terminal_statuses": list(accepted)})
                outcome = supervise(directory, launcher, sampler, limits)
                if outcome["status"] not in accepted:
                    return {"stopped_at": f"{item.item_id}/{config}", **outcome, "summary": None}
        return {"stopped_at": None, "status": "all_attempted"}


# --------------------------------------------------------------------------- collection

def _marqo_scores(journal: Path):
    scores = []
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("kind") == "marqo_scores":
                scores += [{"timestamp_seconds": s["timestamp_seconds"], "probability": s["model_probability"]}
                           for s in entry["scores"]]
    return scores


def collect(manifest_path: Path, campaign: Path, pilot_manifest: Path, output: Path, *, split="test"):
    manifest: BenchmarkManifest = load_manifest(manifest_path)
    assert_disjoint_from_pilot(manifest, pilot_manifest)
    identity = json.loads((campaign / "campaign.json").read_text(encoding="utf-8"))
    digest = manifest_digest(manifest)
    if identity["manifest_digest"] != digest:
        raise ValueError("campaign was run with another manifest version")
    attempts = _attempts(campaign)
    rows = []
    for item in manifest.evaluable(split):
        for config in campaign_configs(identity):
            dirs = attempts.get((item.item_id, config))
            if not dirs:
                rows.append({"item_id": item.item_id, "config": config, "status": "not_run",
                             "start_mode": "cold_process"})
                continue
            latest = dirs[-1]
            outcome = attempt_status(latest)
            monitor = latest / "monitor_summary.json"
            monitor = json.loads(monitor.read_text(encoding="utf-8")) if monitor.exists() else {}
            summary = outcome["summary"] or {}
            status = outcome["status"] if outcome["status"] in ("completed", "partial", "failed", "cancelled") \
                else "failed"
            row = {"item_id": item.item_id, "config": config, "status": status,
                   "error_type": outcome["error_type"] or "", "start_mode": "cold_process",
                   "os_file_cache": "unknown", "pipeline_seconds": summary.get("pipeline_seconds"),
                   "wall_seconds": monitor.get("wall_seconds"),
                   "peak_process_rss_bytes": monitor.get("process_tree_rss_bytes"),
                   "peak_gpu_memory_mib": monitor.get("gpu_memory_mib"),
                   "marqo_scores": _marqo_scores(latest / "observations.jsonl")}
            if status == "completed" and config == "A2" and summary.get("whisper_backend") not in (
                    "cuda_float16", "not_applicable"):
                raise ValueError(f"{item.item_id}/A2 completed without Whisper CUDA float16")
            if status in ("completed", "partial"):
                if config == "A2":
                    row["input"] = {"sha256": item.sha256}
                else:
                    a1 = json.loads((campaign / "inputs" / f"{item.item_id}.json").read_text(encoding="utf-8"))
                    row["input"] = {k: a1[k] for k in ("sha256", "derived_from_sha256",
                                                       "video_packets_verified_identical")}
                record = json.loads((latest / "record.json").read_text(encoding="utf-8"))
                row["suggestions"] = [{k: s[k] for k in ("id", "start_seconds", "end_seconds", "category",
                                                         "final_confidence")} for s in record["suggestions"]]
            rows.append(row)
    results = ResultsFile.model_validate({
        "schema_version": 1, "benchmark_id": manifest.benchmark_id, "manifest_digest": digest,
        "environment": {"commit": identity["commit"], "model_revisions": identity["model_revisions"],
                        "whisper_backend": "cuda_float16", "gpu": identity["gpu"].split(",")[0].strip() or "unknown",
                        "driver": (identity["gpu"].split(",")[1].strip() if "," in identity["gpu"] else "unknown")},
        "results": rows})
    results.check_against(manifest, digest)
    write_atomic(output, None, serialized=results.model_dump_json(indent=2))
    return results
