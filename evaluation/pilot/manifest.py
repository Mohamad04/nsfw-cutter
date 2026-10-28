"""Strict annotation contracts. Importing this module never opens media files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["nudity", "sexual_activity", "sexual_context"]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=128)]
NonEmpty = Annotated[str, Field(min_length=1, pattern=r"\S")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Interval(StrictModel):
    start_seconds: Seconds
    end_seconds: Seconds

    @model_validator(mode="after")
    def ordered(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be strictly greater than start_seconds ([start, end))")
        return self


class Uncertainty(StrictModel):
    start_tolerance_seconds: Seconds = 0.0
    end_tolerance_seconds: Seconds = 0.0
    notes: str = ""


class Event(Interval):
    event_id: Identifier
    categories: list[Category] = Field(min_length=1)
    notes: str
    uncertainty: Uncertainty | None = None

    @model_validator(mode="after")
    def unique_categories(self):
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("event categories must be unique; uncertain is not a ground-truth category")
        return self


class Exclusion(Interval):
    exclusion_id: Identifier
    kind: Literal["ambiguous", "excluded"]
    reason: NonEmpty


class Clip(StrictModel):
    clip_id: Identifier
    source_video_id: Identifier | None
    file_path: NonEmpty | None
    source_offset_seconds: Seconds | None
    split: Literal["tuning", "test"]
    duration_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None
    media_metadata: dict = Field(default_factory=dict)
    annotation_version: NonEmpty
    exhaustive: bool
    events: list[Event]
    excluded_intervals: list[Exclusion]

    @field_validator("file_path")
    @classmethod
    def local_path(cls, value):
        if value is not None and ("://" in value or "\x00" in value):
            raise ValueError("file_path must be a local file path, not a URL or NUL-containing string")
        return value

    @model_validator(mode="after")
    def valid_annotations(self):
        for name, items, key in (("events", self.events, "event_id"),
                                 ("excluded_intervals", self.excluded_intervals, "exclusion_id")):
            ids = [getattr(item, key) for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{self.clip_id}: duplicate identities in {name}")
            if items and self.duration_seconds is None:
                raise ValueError(f"{self.clip_id}: duration_seconds required before annotation")
            if any(item.end_seconds > self.duration_seconds for item in items):
                raise ValueError(f"{self.clip_id}: {name} extend beyond clip duration")
        if self.exhaustive:
            missing = [name for name in ("source_video_id", "file_path", "source_offset_seconds",
                                        "duration_seconds", "sha256") if getattr(self, name) is None]
            if missing:
                raise ValueError(f"{self.clip_id}: exhaustive annotation requires {', '.join(missing)}")
        return self


class Manifest(StrictModel):
    schema_version: Literal[1]
    dataset_id: Identifier
    synthetic: bool = False
    clips: list[Clip] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def no_leakage(self):
        ids = [clip.clip_id for clip in self.clips]
        if len(ids) != len(set(ids)):
            raise ValueError("clip_id must be unique")
        sources, hashes = {}, {}
        for clip in self.clips:
            for value, seen, label in ((clip.source_video_id, sources, "source_video_id"),
                                       (clip.sha256, hashes, "sha256")):
                if value is not None:
                    if value in seen and seen[value] != clip.split:
                        raise ValueError(f"{label} {value}: tuning/test leakage")
                    seen[value] = clip.split
        return self

    def require_ready(self):
        unfinished = [clip.clip_id for clip in self.clips if not clip.exhaustive]
        if unfinished:
            raise ValueError("Non-exhaustive/draft clips: " + ", ".join(unfinished))
        return self


def load_manifest(path: str | Path, *, allow_draft: bool = False) -> Manifest:
    manifest = Manifest.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))
    return manifest if allow_draft else manifest.require_ready()


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_digest(path: Path, cancellation=None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            digest.update(block)
    return digest.hexdigest()


def clip_path(clip: Clip, manifest_path: Path) -> Path:
    return (manifest_path.resolve().parent / clip.file_path).resolve()
