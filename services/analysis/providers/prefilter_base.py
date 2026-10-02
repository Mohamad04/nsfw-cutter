from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    PrefilterFrameScore,
    SampledFrame,
)

PrefilterProgressCallback = Callable[[int, str], None]


class PrefilterProviderError(RuntimeError):
    pass


class PrefilterProviderUnavailableError(PrefilterProviderError):
    """A run-level failure which cannot improve for a later frame chunk."""


class PrefilterDiagnostics(BaseModel):
    """Small, path-free summary suitable for logs, progress, and run metrics."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_revision: str
    device_mode: Literal["cuda", "cpu", "unavailable"] = "unavailable"
    device_name: str = ""
    precision: str = ""
    frame_count: int = Field(default=0, ge=0)
    successful_frame_count: int = Field(default=0, ge=0)
    failed_chunk_count: int = Field(default=0, ge=0)
    conservatively_included_count: int = Field(default=0, ge=0)


class NSFWPrefilter(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def warnings(self) -> Sequence[str]: ...

    @property
    def diagnostics(self) -> PrefilterDiagnostics: ...

    def check_ready(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None: ...

    def score_frames(
        self,
        frames: Sequence[SampledFrame],
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: PrefilterProgressCallback | None = None,
    ) -> list[PrefilterFrameScore]: ...

    def release(self) -> None: ...
