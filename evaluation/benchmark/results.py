"""Per-video result contract v1 for the A1/A2 pipeline runs (A0 is derived from A2's Marqo scores)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from evaluation.benchmark.manifest import BenchmarkManifest, Sha256
from evaluation.pilot.manifest import Identifier, NonEmpty, StrictModel

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PipelineConfig = Literal["A1", "A2"]


class Suggestion(StrictModel):
    id: NonEmpty
    start_seconds: Seconds
    end_seconds: Seconds
    category: Literal["nudity", "sexual_activity", "sexual_context", "uncertain"]
    final_confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class MarqoScore(StrictModel):
    timestamp_seconds: Seconds
    # None marks the pipeline's conservative fallback (no model probability was produced).
    probability: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None


class InputIdentity(StrictModel):
    sha256: Sha256
    derived_from_sha256: Sha256 | None = None
    video_packets_verified_identical: bool | None = None


class VideoResult(StrictModel):
    item_id: Identifier
    config: PipelineConfig
    status: Literal["completed", "partial", "failed", "cancelled", "not_run"]
    error_type: str = ""
    input: InputIdentity | None = None
    suggestions: list[Suggestion] = Field(default_factory=list)
    marqo_scores: list[MarqoScore] = Field(default_factory=list)
    pipeline_seconds: Seconds | None = None
    wall_seconds: Seconds | None = None
    start_mode: Literal["cold_process", "warm_process"]
    os_file_cache: Literal["unknown", "warm", "flushed"] = "unknown"
    peak_process_rss_bytes: Annotated[int, Field(ge=0)] | None = None
    peak_gpu_memory_mib: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "completed" and self.input is None:
            raise ValueError(f"{self.item_id}/{self.config}: completed runs must record the input identity")
        if self.status != "completed" and self.status != "partial" and self.suggestions:
            raise ValueError(f"{self.item_id}/{self.config}: suggestions without a usable run")
        if self.config == "A1" and self.input is not None and (
                self.input.derived_from_sha256 is None or self.input.video_packets_verified_identical is not True):
            raise ValueError(f"{self.item_id}/A1: the audio-free input must be verified against its source")
        if any(s.end_seconds <= s.start_seconds for s in self.suggestions):
            raise ValueError(f"{self.item_id}/{self.config}: empty or reversed suggestion interval")
        return self


class Environment(StrictModel):
    commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    model_revisions: dict[str, NonEmpty]
    whisper_backend: Literal["cuda_float16", "cpu_int8"]
    gpu: NonEmpty
    driver: NonEmpty


class ResultsFile(StrictModel):
    schema_version: Literal[1]
    benchmark_id: Identifier
    manifest_digest: Sha256
    environment: Environment
    results: list[VideoResult]

    @model_validator(mode="after")
    def unique(self):
        keys = [(r.item_id, r.config) for r in self.results]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate result for the same item and configuration")
        return self

    def check_against(self, manifest: BenchmarkManifest, digest: str):
        if self.benchmark_id != manifest.benchmark_id or self.manifest_digest != digest:
            raise ValueError("results do not belong to this manifest version")
        known = {item.item_id: item for item in manifest.items}
        unknown = sorted({r.item_id for r in self.results} - set(known))
        if unknown:
            raise ValueError("results for unknown items: " + ", ".join(unknown))
        for r in self.results:
            item = known[r.item_id]
            if r.input is not None and item.sha256 is not None:
                original = r.input.derived_from_sha256 if r.config == "A1" else r.input.sha256
                if original != item.sha256:
                    raise ValueError(f"{r.item_id}/{r.config}: input does not match the manifest sha256")
        return self


def load_results(path: str | Path) -> ResultsFile:
    return ResultsFile.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))
