from __future__ import annotations

from typing import Protocol

from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import AnalysisSettings, VisualBatch, VLMReviewResult


class VLMProviderError(RuntimeError):
    """Base provider failure with local-only output attached for diagnostics.

    The raw model text is deliberately kept out of the exception message so normal
    application logs cannot accidentally copy prompts or sensitive model output.
    """

    def __init__(
        self,
        message: str,
        *,
        raw_output: str = "",
        repaired_output: str = "",
        stop_reason: str = "failed",
    ) -> None:
        super().__init__(message)
        self.raw_output = raw_output
        self.repaired_output = repaired_output
        self.stop_reason = stop_reason


class VLMProviderUnavailableError(VLMProviderError):
    """A run-level provider failure which cannot improve on a later batch."""


class VLMProviderInferenceError(VLMProviderError):
    """The model or processor failed while preparing or running inference."""


class VLMProviderTimeoutError(VLMProviderError):
    """Generation exceeded the cooperative per-batch monotonic deadline."""


class VLMStructuredOutputError(VLMProviderError):
    """The model output could not be validated against the strict wire contract."""


class VLMQuantizationError(VLMProviderUnavailableError):
    """The explicitly requested quantized GPU backend is unavailable or failed."""


class VLMProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def check_ready(
        self,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> None: ...

    def review_batch(
        self,
        batch: VisualBatch,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
    ) -> VLMReviewResult: ...
