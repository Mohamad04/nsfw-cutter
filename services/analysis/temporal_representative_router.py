"""Bounded timestamp-based routing for expensive representative consumers."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    MICROSECONDS_PER_SECOND,
    FrameSample,
)


class TemporalRoutingMetrics(BaseModel):
    """Pixel-free routing measurements suitable for benchmarks and evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_representatives_observed: int = Field(ge=0)
    representatives_routed: int = Field(ge=0)
    representatives_skipped: int = Field(ge=0)
    semantic_workload_fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    configured_gap_seconds: float = Field(gt=0.0)
    configured_phase_seconds: float = Field(ge=0.0)
    first_routed_timestamp_us: int | None = Field(default=None, ge=0)
    last_routed_timestamp_us: int | None = Field(default=None, ge=0)
    minimum_routed_delta_us: int | None = Field(default=None, ge=0)
    maximum_routed_delta_us: int | None = Field(default=None, ge=0)
    average_routed_delta_us: float | None = Field(default=None, ge=0.0)
    routed_timestamp_sha256: str


class TemporalRepresentativeRouter:
    """Route the first ascending representative at or after ``phase + k * gap``.

    The wrapper holds no frames: an accepted representative is immediately sent
    downstream or immediately discarded from this specialist path.
    """

    def __init__(
        self,
        downstream: Any,
        *,
        gap_seconds: float,
        phase_seconds: float = 0.0,
    ) -> None:
        if not math.isfinite(gap_seconds) or gap_seconds <= 0.0:
            raise ValueError("Temporal routing gap must be finite and positive.")
        if not math.isfinite(phase_seconds) or phase_seconds < 0.0:
            raise ValueError("Temporal routing phase must be finite and non-negative.")
        self.downstream = downstream
        self.gap_seconds = gap_seconds
        self.phase_seconds = phase_seconds
        self._gap_us = round(gap_seconds * MICROSECONDS_PER_SECOND)
        self._next_target_us = round(phase_seconds * MICROSECONDS_PER_SECOND)
        if self._gap_us <= 0 or self._next_target_us >= self._gap_us:
            raise ValueError("Temporal routing phase must satisfy 0 <= phase < gap.")
        self._last_observed_timestamp_us: int | None = None
        self._first_routed_timestamp_us: int | None = None
        self._last_routed_timestamp_us: int | None = None
        self._total_observed = 0
        self._routed = 0
        self._delta_sum_us = 0
        self._minimum_delta_us: int | None = None
        self._maximum_delta_us: int | None = None
        self._timestamp_digest = hashlib.sha256()

    @property
    def metrics(self) -> TemporalRoutingMetrics:
        skipped = self._total_observed - self._routed
        delta_count = max(0, self._routed - 1)
        return TemporalRoutingMetrics(
            total_representatives_observed=self._total_observed,
            representatives_routed=self._routed,
            representatives_skipped=skipped,
            semantic_workload_fraction=(
                self._routed / self._total_observed if self._total_observed else None
            ),
            configured_gap_seconds=self.gap_seconds,
            configured_phase_seconds=self.phase_seconds,
            first_routed_timestamp_us=(
                self._first_routed_timestamp_us if self._routed else None
            ),
            last_routed_timestamp_us=self._last_routed_timestamp_us,
            minimum_routed_delta_us=self._minimum_delta_us,
            maximum_routed_delta_us=self._maximum_delta_us,
            average_routed_delta_us=(
                self._delta_sum_us / delta_count if delta_count else None
            ),
            routed_timestamp_sha256=self._timestamp_digest.hexdigest(),
        )

    def __call__(
        self,
        frame: ExtractedFrame,
        sample: FrameSample,
        cancellation: CancellationToken,
    ) -> None:
        cancellation.raise_if_cancelled()
        timestamp_us = sample.timestamp_us
        if (
            self._last_observed_timestamp_us is not None
            and timestamp_us < self._last_observed_timestamp_us
        ):
            raise ValueError("Temporal routing requires ascending global timestamps.")
        self._last_observed_timestamp_us = timestamp_us
        self._total_observed += 1
        if timestamp_us < self._next_target_us:
            return

        # One late representative can pass many temporal targets, but it is
        # delivered exactly once and advances the schedule beyond itself.
        self.downstream(frame, sample, cancellation)
        self._record_routed_timestamp(timestamp_us)
        while self._next_target_us <= timestamp_us:
            self._next_target_us += self._gap_us
        cancellation.raise_if_cancelled()

    def flush(self, cancellation: CancellationToken) -> None:
        cancellation.raise_if_cancelled()
        flush = getattr(self.downstream, "flush", None)
        if callable(flush):
            flush(cancellation)
        cancellation.raise_if_cancelled()

    def _record_routed_timestamp(self, timestamp_us: int) -> None:
        if self._routed == 0:
            self._first_routed_timestamp_us = timestamp_us
        elif self._last_routed_timestamp_us is not None:
            delta = timestamp_us - self._last_routed_timestamp_us
            self._delta_sum_us += delta
            self._minimum_delta_us = (
                delta
                if self._minimum_delta_us is None
                else min(self._minimum_delta_us, delta)
            )
            self._maximum_delta_us = (
                delta
                if self._maximum_delta_us is None
                else max(self._maximum_delta_us, delta)
            )
        self._timestamp_digest.update(f"{timestamp_us}\n".encode("ascii"))
        self._last_routed_timestamp_us = timestamp_us
        self._routed += 1
