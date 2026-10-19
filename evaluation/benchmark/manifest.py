"""Benchmark dataset contract v1. Importing this module never opens media files.

A benchmark manifest records where every video comes from (dataset, licence, access route),
which independence group it belongs to, and what the reference labels actually establish.
Labels are three-state: an unannotated category is "unknown", never a negative.

review_basis records how a video-level label was established:
- "unreviewed": no reference label (video_label must be "missing");
- "complete": part of an annotation that covers every evaluable item of the split;
- "alert_triggered": reviewed because at least one configuration alerted;
- "random_audit": reviewed as part of a pre-declared random sample of non-alerted items.
Only "complete" coverage supports specificity, recall or F1; the other designs are scored as
confirmed-alert reviews (see report.py), because the verified subset is not a random sample.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from evaluation.pilot.manifest import Category, Event, Exclusion, Identifier, NonEmpty, StrictModel

CATEGORIES: tuple[Category, ...] = ("nudity", "sexual_activity", "sexual_context")
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Url = Annotated[str, Field(pattern=r"^https://\S+$")]


class LicenseEvidence(StrictModel):
    url: Url
    retrieved: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    statement: NonEmpty


class DatasetInfo(StrictModel):
    dataset_id: Identifier
    name: NonEmpty
    publisher: NonEmpty
    homepage: Url
    version: NonEmpty
    license_id: NonEmpty
    license_evidence: list[LicenseEvidence] = Field(min_length=1)
    access: Literal["ungated", "click_through", "manual_approval", "signed_agreement"]
    permitted_use: NonEmpty
    redistribution_allowed: bool
    content: Literal["real", "synthetic", "mixed"]


class AnnotationInfo(StrictModel):
    version: NonEmpty
    source: Literal["project_annotators", "dataset_human", "dataset_model_generated", "dataset_mixed"]
    guideline: NonEmpty
    notes: str = ""


class TemporalAnnotation(StrictModel):
    """Events are scorable for binary detection only when binary_exhaustive is true, and for a
    category only when that category is listed in exhaustive_categories."""
    binary_exhaustive: bool
    exhaustive_categories: list[Category] = Field(default_factory=list)
    events: list[Event]
    excluded_intervals: list[Exclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.exhaustive_categories)) != len(self.exhaustive_categories):
            raise ValueError("exhaustive_categories must be unique")
        if self.exhaustive_categories and not self.binary_exhaustive:
            raise ValueError("a category cannot be exhaustive when binary detection is not")
        for name, items, key in (("events", self.events, "event_id"),
                                 ("excluded_intervals", self.excluded_intervals, "exclusion_id")):
            ids = [getattr(item, key) for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate identities in {name}")
        return self


class Item(StrictModel):
    item_id: Identifier
    group_id: Identifier
    split: Literal["tuning", "test"]
    file_name: NonEmpty | None = None
    sha256: Sha256 | None = None
    duration_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None
    has_audio: bool | None = None
    speech_language: Annotated[str, Field(pattern=r"^[a-z]{2,3}$")] | None = None
    video_label: Literal["positive", "negative", "uncertain", "missing"]
    review_basis: Literal["unreviewed", "complete", "alert_triggered", "random_audit"] = "unreviewed"
    category_labels: dict[Category, Literal["present", "absent", "unknown"]]
    temporal: TemporalAnnotation | None = None
    excluded: bool = False
    exclusion_reason: str = ""
    provenance: dict = Field(default_factory=dict)

    @field_validator("file_name")
    @classmethod
    def local_name(cls, value):
        if value is not None and ("://" in value or "\x00" in value):
            raise ValueError("file_name must be a local name, not a URL")
        return value

    @model_validator(mode="after")
    def coherent(self):
        if set(self.category_labels) != set(CATEGORIES):
            raise ValueError(f"{self.item_id}: category_labels must state all of {', '.join(CATEGORIES)}")
        if (self.video_label == "missing") != (self.review_basis == "unreviewed"):
            raise ValueError(f"{self.item_id}: a reference label needs a review basis, and only missing "
                             "labels may be unreviewed")
        present = [c for c, state in self.category_labels.items() if state == "present"]
        if self.video_label == "negative" and present:
            raise ValueError(f"{self.item_id}: a negative video cannot have a present category")
        if self.video_label == "positive" and all(s == "absent" for s in self.category_labels.values()):
            raise ValueError(f"{self.item_id}: a positive video cannot have every category absent")
        if self.excluded != bool(self.exclusion_reason.strip()):
            raise ValueError(f"{self.item_id}: excluded items need a reason, and only they may have one")
        if self.temporal is not None:
            if self.duration_seconds is None:
                raise ValueError(f"{self.item_id}: temporal annotations require duration_seconds")
            items = [*self.temporal.events, *self.temporal.excluded_intervals]
            if any(item.end_seconds > self.duration_seconds for item in items):
                raise ValueError(f"{self.item_id}: temporal annotation beyond the video duration")
            for category in self.temporal.exhaustive_categories:
                if self.category_labels[category] == "unknown":
                    raise ValueError(f"{self.item_id}: {category} is exhaustive but labelled unknown")
            for event in self.temporal.events:
                if any(self.category_labels[c] == "absent" for c in event.categories):
                    raise ValueError(f"{self.item_id}: event {event.event_id} uses an absent category")
            if self.temporal.binary_exhaustive and self.video_label == "negative" and self.temporal.events:
                raise ValueError(f"{self.item_id}: negative video with target events")
            if self.temporal.binary_exhaustive and self.video_label == "positive" and not self.temporal.events:
                raise ValueError(f"{self.item_id}: positive video without any target event")
        return self


class BenchmarkManifest(StrictModel):
    schema_version: Literal[1]
    benchmark_id: Identifier
    track: Literal["technical", "accuracy"]
    synthetic_fixture: bool = False
    dataset: DatasetInfo
    annotation: AnnotationInfo
    items: list[Item] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def independence(self):
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("item_id must be unique")
        hashes = [item.sha256 for item in self.items if item.sha256 is not None]
        if len(hashes) != len(set(hashes)):
            raise ValueError("duplicate media sha256: the same video cannot be two observations")
        splits = {}
        for item in self.items:
            if splits.setdefault(item.group_id, item.split) != item.split:
                raise ValueError(f"group {item.group_id}: tuning/test leakage")
        # A technical (negative-presumed) corpus has no positive references. NSFW content found during
        # review is kept as an excluded, counted item so the discovery is never silently dropped.
        if self.track == "technical" and any(item.video_label == "positive" and not item.excluded
                                             for item in self.items):
            raise ValueError("the technical track has no positive reference labels; exclude discovered NSFW "
                             "videos with a reason")
        return self

    def evaluable(self, split: str = "test") -> list[Item]:
        return [item for item in self.items if item.split == split and not item.excluded]

    def verification(self, split: str = "test"):
        items = self.evaluable(split)
        bases = [item.review_basis for item in items]
        return {"complete": bool(items) and all(basis == "complete" for basis in bases),
                "by_basis": {basis: bases.count(basis)
                             for basis in ("complete", "alert_triggered", "random_audit", "unreviewed")}}


def assert_disjoint_from_pilot(manifest: BenchmarkManifest, pilot_manifest_path: str | Path):
    """The development pilot (tuning data) must never reappear in an independent benchmark.

    Checks identical media (SHA-256) and shared source identity (pilot source_video_id equal to a
    benchmark group_id). It cannot detect re-encoded or trimmed copies of a pilot source.
    """
    from evaluation.pilot.manifest import load_manifest as load_pilot

    pilot = load_pilot(pilot_manifest_path, allow_draft=True)
    pilot_hashes = {clip.sha256 for clip in pilot.clips if clip.sha256}
    pilot_sources = {clip.source_video_id for clip in pilot.clips if clip.source_video_id}
    overlaps = sorted({item.item_id for item in manifest.items
                       if (item.sha256 and item.sha256 in pilot_hashes) or item.group_id in pilot_sources})
    if overlaps:
        raise ValueError("benchmark items overlap the development pilot: " + ", ".join(overlaps))
    return {"pilot_manifest_digest": canonical_digest(pilot.model_dump(mode="json")),
            "pilot_clips": len(pilot.clips), "checked_items": len(manifest.items),
            "items_without_sha256": sum(item.sha256 is None for item in manifest.items)}


def load_manifest(path: str | Path) -> BenchmarkManifest:
    return BenchmarkManifest.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def manifest_digest(manifest: BenchmarkManifest) -> str:
    return canonical_digest(manifest.model_dump(mode="json"))
