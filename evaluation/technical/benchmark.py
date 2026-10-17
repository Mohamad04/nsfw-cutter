"""Small, append-only benchmark around the frozen production pipeline.

The fixed proposal is an intentional allowlist, not a generic dataset schema.
No action labels are ever interpreted as NSFW annotations.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from evaluation.pilot.manifest import canonical_digest, file_digest
from evaluation.pilot.runner import (
    ROOT, effective_settings, environment_metadata, offline_environment,
    production_pipeline, write_new,
)

BASELINE = "ca7a6732aa0d4e153b06dada6d54c076a929db27"
PROPOSAL_DIGEST = "ff2e84d512bbf095a566ec4187ab7bde2bce0809deae1c6c65ad2565e9dd7b23"
CONFIG_DIGEST = "3348307d7491fc3406b8bac5aa3cb34fab7434fa316ce71d04d02d84bf85c5db"
RUNTIME_DIRS = ["services", "core", "models", "controllers/app", "workers", "evaluation/pilot"]
SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def proposal(path):
    value = read(path)
    if canonical_digest(value) != PROPOSAL_DIGEST:
        raise ValueError("Proposal differs from the reviewed fixed 25-clip selection")
    return value


def authorize(flag, clearance, operation):
    if not flag:
        raise ValueError(f"Explicit --allow-{operation} required")
    value = read(clearance) if clearance else {}
    required = {"dataset", "reviewed_by", "reviewed_at", "terms_source", "permitted_operations"}
    if (set(value) != required or value["dataset"] != "UCF101"
            or any(not isinstance(value[k], str) or not value[k].strip()
                   for k in required - {"permitted_operations"})
            or not isinstance(value["permitted_operations"], list)
            or operation not in value["permitted_operations"]
            or any(x not in {"download", "prepare", "inference"}
                   for x in value["permitted_operations"])):
        raise ValueError("A documented institutional usage clearance is required")
    return {"sha256": file_digest(Path(clearance)), **value}


def new_directory(root):
    directory = Path(root) / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "_" + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=False)
    return directory


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Packet(Strict):
    stream_index: Annotated[int, Field(ge=0)]
    pts_time: str
    data_hash: Annotated[str, Field(min_length=1)]

    @field_validator("pts_time")
    @classmethod
    def finite_pts(cls, value):
        if not math.isfinite(float(value)):
            raise ValueError("Nonfinite packet timestamp")
        return value


class Stream(Strict):
    codec_type: Annotated[str, Field(min_length=1)]
    codec_name: Annotated[str, Field(min_length=1)]
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    sample_rate: str | None = None
    channels: Annotated[int, Field(gt=0)] | None = None


class MediaMetadata(Strict):
    duration_seconds: Positive
    format_name: Annotated[str, Field(min_length=1)]
    streams: list[Stream] = Field(min_length=1)
    packets: list[Packet] = Field(min_length=1)


class PreparedClip(Strict):
    clip_id: str
    source_url: str
    original_path: str
    original_sha256: SHA
    evaluated_path: str
    evaluated_sha256: SHA
    duration_seconds: Positive
    media: dict
    original_media: dict
    operation: Literal["identity", "stream_copy_remux"]

    @field_validator("media", "original_media")
    @classmethod
    def strict_metadata(cls, value):
        parsed = MediaMetadata.model_validate(value)
        if not any(s.codec_type == "video" for s in parsed.streams):
            raise ValueError("No video stream")
        if any(p.stream_index >= len(parsed.streams) for p in parsed.packets):
            raise ValueError("Invalid packet stream identity")
        return value


class Prepared(Strict):
    schema_version: Literal[1]
    proposal_sha256: Literal[PROPOSAL_DIGEST]
    clearance: dict
    clips: list[PreparedClip] = Field(min_length=25, max_length=25)


def load_prepared(path, manifest, verify_files=True):
    data = Prepared.model_validate(read(path))
    if [c.clip_id for c in data.clips] != [c["clip_id"] for c in manifest["clips"]]:
        raise ValueError("Prepared identities/order differ from proposal")
    if len({c.original_sha256 for c in data.clips}) != len(data.clips):
        raise ValueError("Duplicate original media identities")
    for c, source in zip(data.clips, manifest["clips"]):
        if c.source_url != source["source_url"]:
            raise ValueError("Source URL mismatch")
        if c.duration_seconds != c.media.get("duration_seconds"):
            raise ValueError("Duration mismatch")
        verify_remux(c.original_media, c.media)
        if c.operation == "identity" and (c.original_path != c.evaluated_path or c.original_sha256 != c.evaluated_sha256):
            raise ValueError("Identity operation changed media")
        if not set(c.media["format_name"].split(",")) & {"matroska", "mp4", "mov"}:
            raise ValueError("Incompatible container metadata")
        for name, digest in ((c.original_path, c.original_sha256), (c.evaluated_path, c.evaluated_sha256)):
            if not Path(name).is_absolute():
                raise ValueError("Prepared paths must be absolute")
            if verify_files and file_digest(Path(name)) != digest:
                raise ValueError("Media SHA-256 mismatch")
        if Path(c.evaluated_path).suffix.lower() not in {".mp4", ".mkv"}:
            raise ValueError("Incompatible evaluated container")
    return data


def probe(path):
    from services.infrastructure.ffmpeg.paths import get_ffprobe_path
    result = subprocess.run([str(get_ffprobe_path()), "-v", "error", "-show_format", "-show_streams",
                             "-show_packets", "-show_data_hash", "sha256", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=180)
    raw = json.loads(result.stdout)
    duration = float(raw["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0 or not any(s["codec_type"] == "video" for s in raw["streams"]):
        raise ValueError("Invalid video metadata")
    return {"duration_seconds": duration, "format_name": raw["format"]["format_name"],
            "streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "sample_rate", "channels")}
                        for s in raw["streams"]],
            "packets": [{k: p.get(k) for k in ("stream_index", "pts_time", "data_hash")}
                        for p in raw.get("packets", [])]}


def remux(source, target):
    from services.infrastructure.ffmpeg.paths import get_ffmpeg_path
    subprocess.run([str(get_ffmpeg_path()), "-nostdin", "-v", "error", "-n", "-copyts", "-i", str(source),
                    "-map", "0", "-c", "copy", str(target)], check=True, capture_output=True, timeout=180)


def verify_remux(before, after):
    if before["streams"] != after["streams"] or abs(before["duration_seconds"] - after["duration_seconds"]) > .05:
        raise ValueError("Remux stream/duration mismatch")
    for index in range(len(before["streams"])):
        a = [p for p in before["packets"] if p["stream_index"] == index]
        b = [p for p in after["packets"] if p["stream_index"] == index]
        if not a or len(a) != len(b):
            raise ValueError("Remux packet count mismatch")
        for x, y in zip(a, b):
            if (not x["data_hash"] or x["data_hash"] != y["data_hash"]
                    or x["pts_time"] is None or y["pts_time"] is None
                    or abs(float(x["pts_time"]) - float(y["pts_time"])) > .002):
                raise ValueError("Remux changed packet payload or timeline; no automatic re-encoding")


def download(manifest, output, *, allow=False, clearance=None, opener=None):
    approved = authorize(allow, clearance, "download")
    from urllib.request import urlopen
    directory = new_directory(output)
    write_new(directory / "authorization.json", approved)
    for clip in manifest["clips"]:
        with (opener or urlopen)(clip["source_url"], timeout=60) as response:
            if response.geturl() != clip["source_url"]:
                raise ValueError("Unexpected redirect; review destination before downloading")
            size = 0
            with (directory / clip["source_filename"]).open("xb") as stream:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > clip["http_content_length_bytes"]:
                        raise ValueError("Download exceeds reviewed size")
                    stream.write(block)
            if size != clip["http_content_length_bytes"]:
                raise ValueError("Incomplete download; partial file retained")
    write_new(directory / "download.json", {"proposal_sha256": PROPOSAL_DIGEST,
              "files": {c["source_filename"]: file_digest(directory / c["source_filename"]) for c in manifest["clips"]}})
    return directory


def prepare(manifest, media_root, output, *, allow=False, clearance=None, probe_fn=probe, remux_fn=remux):
    approved = authorize(allow, clearance, "prepare")
    directory = new_directory(output)
    write_new(directory / "authorization.json", approved)
    if probe_fn is probe:
        from services.infrastructure.ffmpeg.paths import get_ffmpeg_path, get_ffprobe_path
        write_new(directory / "tools.json", {name: subprocess.run(
            [str(path), "-version"], check=True, capture_output=True, text=True, timeout=10).stdout
            for name, path in (("ffmpeg", get_ffmpeg_path()), ("ffprobe", get_ffprobe_path()))})
    clips = []
    for c in manifest["clips"]:
        source = (Path(media_root) / c["source_filename"]).resolve()
        if source.stat().st_size != c["http_content_length_bytes"]:
            raise ValueError("Original size differs from reviewed source")
        original_hash = file_digest(source)
        receipt = Path(media_root) / "download.json"
        if receipt.exists():
            downloaded = read(receipt)
            if (downloaded.get("proposal_sha256") != PROPOSAL_DIGEST
                    or downloaded.get("files", {}).get(c["source_filename"]) != original_hash):
                raise ValueError("Download receipt identity mismatch")
        before = probe_fn(source)
        target, operation = source, "identity"
        if source.suffix.lower() not in {".mp4", ".mkv"}:
            target = directory / (c["clip_id"] + ".mkv")
            remux_fn(source, target)
            operation = "stream_copy_remux"
        after = probe_fn(target)
        verify_remux(before, after)
        if not set(after["format_name"].split(",")) & {"matroska", "mp4", "mov"}:
            raise ValueError("Incompatible container metadata")
        if file_digest(source) != original_hash:
            raise ValueError("Original media changed during preparation")
        row = PreparedClip(clip_id=c["clip_id"], source_url=c["source_url"], original_path=str(source),
                           original_sha256=original_hash, evaluated_path=str(target.resolve()),
                           evaluated_sha256=file_digest(target), duration_seconds=after["duration_seconds"],
                           original_media=before, media=after, operation=operation)
        clips.append(row)
        write_new(directory / (c["clip_id"] + ".json"), row.model_dump())
    result = Prepared(schema_version=1, proposal_sha256=PROPOSAL_DIGEST, clearance=approved, clips=clips)
    write_new(directory / "prepared.json", result.model_dump())
    return directory


def frozen_settings():
    from services.analysis.contracts import AnalysisSettings
    config = read(Path(__file__).with_name("frozen_config.json"))
    if canonical_digest(config) != CONFIG_DIGEST:
        raise ValueError("Frozen configuration identity mismatch")
    settings = AnalysisSettings.model_validate(config["settings"])
    if effective_settings(settings) != config:
        raise ValueError("Effective production configuration drift")
    return settings


def verify_runtime():
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    subprocess.run(git + ["diff", "--exit-code", BASELINE, "--", *RUNTIME_DIRS], cwd=ROOT,
                   check=True, capture_output=True)
    untracked = subprocess.run(git + ["ls-files", "--others", "--exclude-standard", "--", *RUNTIME_DIRS],
                               cwd=ROOT, check=True, capture_output=True, text=True).stdout
    if untracked.strip():
        raise ValueError("Untracked runtime source files")
    env = environment_metadata()
    env["git_commit"] = subprocess.run(git + ["rev-parse", "HEAD"], cwd=ROOT, check=True,
                                       capture_output=True, text=True).stdout.strip()
    env["frozen_pipeline_baseline"] = BASELINE
    env["technical_source_sha256"] = {p.name: file_digest(p) for p in Path(__file__).parent.glob("*.py")}
    return env


@contextmanager
def campaign_lock(root):
    """OS lock is released on process death; never steal a live campaign lock."""
    Path(root).mkdir(parents=True, exist_ok=True)
    with (Path(root) / ".lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def flagged_seconds(suggestions, duration):
    end, total = 0.0, 0.0
    for item in sorted(suggestions, key=lambda s: s["start_seconds"]):
        a, b = item["start_seconds"], item["end_seconds"]
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b <= duration):
            raise ValueError("Invalid predicted interval")
        total += max(0.0, b - max(a, end))
        end = max(end, b)
    return total


def attempt(clip, settings, root, env, pipeline_factory=production_pipeline):
    from evaluation.pilot.observability import Journal, PrivateEvaluationCache
    from services.analysis.cancellation import CancellationToken, AnalysisCancelled
    from services.analysis.contracts import AnalysisRunRequest
    directory = new_directory(root)
    write_new(directory / "attempt.json", {"clip_id": clip.clip_id, "media": clip.model_dump(),
              "configuration_sha256": CONFIG_DIGEST, "environment_sha256": canonical_digest(env)})
    write_new(directory / "environment.json", env)
    write_new(directory / "config.json", effective_settings(settings))
    journal = Journal(directory / "observations.jsonl")
    token = CancellationToken()
    previous = signal.signal(signal.SIGINT, lambda *_: token.cancel())
    start, pipeline_start, pipeline_elapsed = perf_counter(), None, None
    summary = {"clip_id": clip.clip_id, "attempt_id": directory.name, "status": "failed",
               "duration_seconds": clip.duration_seconds, "error_type": None, "record_sha256": None}
    try:
        for path, digest in ((clip.original_path, clip.original_sha256), (clip.evaluated_path, clip.evaluated_sha256)):
            if file_digest(Path(path), cancellation=token) != digest:
                raise ValueError("Media identity mismatch")
        with offline_environment():
            pipeline = pipeline_factory(PrivateEvaluationCache(directory / "cache"), journal)
            pipeline_start = perf_counter()
            record = pipeline.run(AnalysisRunRequest(video_path=Path(clip.evaluated_path), settings=settings,
                                  force_reanalysis=True, selected_subtitle=None), cancellation=token,
                                  event_callback=journal.progress, job_id=directory.name)
            pipeline_elapsed = perf_counter() - pipeline_start
        write_new(directory / "record.json", record.model_dump(mode="json"))
        summary["record_sha256"] = file_digest(directory / "record.json")
        if (record.status.value == "running" or record.settings != settings.model_dump(mode="json")
                or record.video_fingerprint != "sha256:" + clip.evaluated_sha256):
            raise ValueError("Returned record identity/configuration mismatch")
        if record.status.value == "completed" and record.media is None:
            raise ValueError("Completed record lacks media")
        if record.media is not None and abs(record.media.duration_seconds - clip.duration_seconds) > .05:
            raise ValueError("Returned duration mismatch")
        suggestions = [s.model_dump(mode="json", exclude={"reason"}) for s in record.suggestions]
        summary.update(status=record.status.value, suggestions=suggestions, suggestion_count=len(suggestions),
                       candidate_windows=len(record.candidate_windows),
                       flagged_seconds=flagged_seconds(suggestions, clip.duration_seconds),
                       warnings=record.warnings, failures=record.errors)
    except (Exception, KeyboardInterrupt) as exc:
        summary.update(status="cancelled" if isinstance(exc, (AnalysisCancelled, KeyboardInterrupt)) else "failed",
                       error_type=type(exc).__name__)
        journal.emit("runner_failure", error_type=type(exc).__name__)
    finally:
        elapsed = pipeline_elapsed if pipeline_elapsed is not None else perf_counter() - pipeline_start if pipeline_start is not None else None
        summary.update(pipeline_seconds=elapsed, runner_seconds=perf_counter() - start,
                       real_time_factor=elapsed / clip.duration_seconds if elapsed is not None else None,
                       reliability=journal.reliability())
        signal.signal(signal.SIGINT, previous)
        journal.close()
        write_new(directory / "summary.json", summary)
    return summary


def history(root):
    rows = []
    prepared_path = Path(root) / "prepared.json"
    expected = {c["clip_id"]: c for c in read(prepared_path)["clips"]} if prepared_path.exists() else {}
    for directory in sorted((Path(root) / "attempts").glob("*")):
        if not (directory / "attempt.json").exists():
            raise ValueError("Orphan attempt without identity; preserve and review manually")
        meta = read(directory / "attempt.json")
        if expected and meta.get("media") != expected.get(meta["clip_id"]):
            raise ValueError("Attempt media provenance mismatch")
        if meta["configuration_sha256"] != CONFIG_DIGEST:
            raise ValueError("Mixed configurations")
        if (canonical_digest(read(directory / "config.json")) != CONFIG_DIGEST
                or canonical_digest(read(directory / "environment.json")) != meta["environment_sha256"]):
            raise ValueError("Attempt environment/configuration integrity mismatch")
        if not (directory / "summary.json").exists():
            rows.append({"clip_id": meta["clip_id"], "attempt_id": directory.name, "status": "interrupted_unknown"})
            continue
        try:
            row = read(directory / "summary.json")
        except (ValueError, UnicodeError):
            rows.append({"clip_id": meta["clip_id"], "attempt_id": directory.name,
                         "status": "interrupted_unknown", "summary_unreadable": True})
            continue
        if row["clip_id"] != meta["clip_id"] or row["attempt_id"] != directory.name:
            raise ValueError("Attempt identity mismatch")
        if row["record_sha256"] and file_digest(directory / "record.json") != row["record_sha256"]:
            raise ValueError("Record integrity mismatch")
        rows.append(row)
    return rows


def report(manifest, root):
    marker = read(Path(root) / "campaign.json")
    if marker["proposal_sha256"] != PROPOSAL_DIGEST or marker["configuration_sha256"] != CONFIG_DIGEST:
        raise ValueError("Campaign provenance mismatch")
    rows = history(root)
    latest = {r["clip_id"]: r for r in rows}
    ids = {c["clip_id"] for c in manifest["clips"]}
    if not set(latest) <= ids:
        raise ValueError("Foreign campaign clip")
    completed = [r for r in latest.values() if r["status"] == "completed"]
    duration = sum(r["duration_seconds"] for r in completed)
    pipeline = sum(r["pipeline_seconds"] for r in completed)
    suggestions = sum(len(r["suggestions"]) for r in completed)
    return {"ground_truth": "unavailable; all NSFW categories unknown", "attempt_count": len(rows),
            "attempted_clips": len(latest), "selected_clips": len(ids), "completed_clips": len(completed),
            "unattempted_clips": len(ids - set(latest)), "technical_success_rate": len(completed) / len(ids),
            "completed_per_attempted": len(completed) / len(latest) if latest else None,
            "completed_pipeline_seconds": pipeline, "completed_runner_seconds": sum(r["runner_seconds"] for r in completed),
            "all_attempts_recorded_runner_seconds": sum(r.get("runner_seconds", 0) for r in rows),
            "interrupted_runtime_unknown": any(r["status"] == "interrupted_unknown" for r in rows),
            "overall_rtf_completed": pipeline / duration if duration else None,
            "suggestions_per_video": suggestions / len(completed) if completed else None,
            "suggestions_per_video_hour": suggestions * 3600 / duration if duration else None,
            "fraction_video_duration_flagged": sum(r["flagged_seconds"] for r in completed) / duration if duration else None,
            "clips_with_alerts_fraction": sum(bool(r["suggestions"]) for r in completed) / len(completed) if completed else None,
            "completed_candidate_windows": sum(r["candidate_windows"] for r in completed),
            "completed_qwen_batches": {key: {
                "observed_total": (sum(r["reliability"][key] for r in completed if r["reliability"][key] is not None)
                                   if any(r["reliability"][key] is not None for r in completed) else None),
                "unknown_clips": sum(r["reliability"][key] is None for r in completed)}
                for key in ("planned_batches", "completed_batches", "failed_batches")},
            "status_counts": {s: sum(r["status"] == s for r in latest.values()) for s in
                              ("completed", "partial", "failed", "cancelled", "interrupted_unknown")},
            "latest_attempts": list(latest.values()), "all_attempts": rows}


def run(manifest, prepared_path, root, *, allow=False, clearance=None, retry_incomplete=False,
        pipeline_factory=production_pipeline, metadata_factory=verify_runtime):
    approved = authorize(allow, clearance, "inference")
    prepared = load_prepared(prepared_path, manifest)
    settings, env = frozen_settings(), metadata_factory()
    identity = {"proposal_sha256": PROPOSAL_DIGEST, "prepared_sha256": file_digest(Path(prepared_path)),
                "configuration_sha256": CONFIG_DIGEST, "runtime_sha256": canonical_digest({
                    k: env.get(k) for k in ("source_sha256", "dependencies", "technical_source_sha256", "hardware")})}
    with campaign_lock(root):
        marker = Path(root) / "campaign.json"
        if marker.exists():
            if read(marker) != identity:
                raise ValueError("Campaign provenance changed; use a new campaign directory")
        else:
            write_new(marker, identity)
            write_new(Path(root) / "proposal.json", manifest)
            write_new(Path(root) / "prepared.json", prepared.model_dump())
        write_new(Path(root) / ("authorization_" + uuid.uuid4().hex + ".json"), approved)
        latest = {r["clip_id"]: r for r in history(root)}
        if not retry_incomplete and any(r["status"] != "completed" for r in latest.values()):
            raise ValueError("Incomplete attempt retained; explicit --retry-incomplete required")
        for clip in prepared.clips:
            if clip.clip_id in latest and latest[clip.clip_id]["status"] == "completed":
                continue
            result = attempt(clip, settings, Path(root) / "attempts", env, pipeline_factory)
            if result["status"] != "completed":
                break
        return report(manifest, root)
