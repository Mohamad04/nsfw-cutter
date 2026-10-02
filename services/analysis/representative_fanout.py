from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import FrameSample


class RepresentativeConsumerFailure(BaseModel):
    """Structured failure retained without preventing sibling consumers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    consumer_name: str
    phase: Literal["consume", "flush"]
    source_timestamp_us: int | None = None
    exception_type: str
    message: str


class RepresentativeFanoutError(RuntimeError):
    def __init__(self, failures: Sequence[RepresentativeConsumerFailure]) -> None:
        self.failures = tuple(failures)
        names = ", ".join(failure.consumer_name for failure in self.failures)
        super().__init__(f"Representative consumers failed: {names}.")


@dataclass
class _ConsumerState:
    name: str
    consumer: Any
    active: bool = True


class FinalizableRepresentativeFanout:
    """Fan out ephemeral representatives while isolating specialist failures."""

    def __init__(self, consumers: Sequence[tuple[str, Any]]) -> None:
        if not consumers:
            raise ValueError("Representative fan-out requires at least one consumer.")
        names = [name for name, _consumer in consumers]
        if any(not name.strip() for name in names):
            raise ValueError("Representative fan-out consumer names cannot be blank.")
        if len(names) != len(set(names)):
            raise ValueError("Representative fan-out consumer names must be unique.")
        self._consumers = [
            _ConsumerState(name=name, consumer=consumer)
            for name, consumer in consumers
        ]
        self.failures: list[RepresentativeConsumerFailure] = []

    def __call__(
        self,
        frame: ExtractedFrame,
        sample: FrameSample,
        cancellation: CancellationToken,
    ) -> None:
        cancellation.raise_if_cancelled()
        for state in self._consumers:
            if not state.active:
                continue
            try:
                state.consumer(frame, sample, cancellation)
            except Exception as exc:  # noqa: BLE001 - isolate arbitrary specialists
                state.active = False
                self.failures.append(
                    RepresentativeConsumerFailure(
                        consumer_name=state.name,
                        phase="consume",
                        source_timestamp_us=sample.timestamp_us,
                        exception_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
        cancellation.raise_if_cancelled()

    def flush(self, cancellation: CancellationToken) -> None:
        cancellation.raise_if_cancelled()
        for state in self._consumers:
            if not state.active:
                continue
            flush = getattr(state.consumer, "flush", None)
            if not callable(flush):
                continue
            try:
                flush(cancellation)
            except Exception as exc:  # noqa: BLE001 - isolate arbitrary specialists
                state.active = False
                self.failures.append(
                    RepresentativeConsumerFailure(
                        consumer_name=state.name,
                        phase="flush",
                        exception_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
        cancellation.raise_if_cancelled()

    def raise_if_failed(self) -> None:
        if self.failures:
            raise RepresentativeFanoutError(self.failures)

    def is_active(self, consumer_name: str) -> bool:
        for state in self._consumers:
            if state.name == consumer_name:
                return state.active
        raise KeyError(consumer_name)
