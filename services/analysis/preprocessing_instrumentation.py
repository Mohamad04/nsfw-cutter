from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from services.analysis.preprocessing_contracts import FrameDisposition, SampleReason


@dataclass(frozen=True)
class SampleObservation:
    """Minimal ephemeral evidence used to verify benchmark correctness."""

    timestamp_us: int
    owning_chunk_index: int
    sample_reasons: frozenset[SampleReason]
    disposition: FrameDisposition
    duplicate_of_timestamp_us: int | None


@dataclass(frozen=True)
class InstrumentationSnapshot:
    durations: dict[str, float]
    counters: dict[str, int]
    peaks: dict[str, float]
    observations: tuple[SampleObservation, ...]


class PreprocessingInstrumentation:
    """Optional, thread-safe measurements for preprocessing benchmarks.

    Production preprocessing does not require this collector. Components emit
    measurements only when one is supplied, keeping benchmark concerns out of
    the persisted preprocessing result contracts.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._durations: dict[str, float] = {}
        self._counters: dict[str, int] = {}
        self._peaks: dict[str, float] = {}
        self._active_process_ids: set[int] = set()
        self._observations: list[SampleObservation] = []

    def add_duration(self, name: str, seconds: float) -> None:
        with self._lock:
            self._durations[name] = self._durations.get(name, 0.0) + max(0.0, seconds)

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def update_peak(self, name: str, value: float) -> None:
        with self._lock:
            current = self._peaks.get(name)
            if current is None or value > current:
                self._peaks[name] = value

    def process_started(self, process_id: int, popen_seconds: float) -> None:
        with self._lock:
            self._active_process_ids.add(process_id)
            self._counters["ffmpeg_process_launches"] = (
                self._counters.get("ffmpeg_process_launches", 0) + 1
            )
            self._durations["process_popen_seconds"] = self._durations.get(
                "process_popen_seconds", 0.0
            ) + max(0.0, popen_seconds)

    def process_first_stdout(self, time_to_first_stdout_seconds: float) -> None:
        self.add_duration("time_to_first_rgb_seconds", time_to_first_stdout_seconds)

    def process_finished(self, process_id: int, process_wall_seconds: float) -> None:
        with self._lock:
            self._active_process_ids.discard(process_id)
            self._durations["ffmpeg_process_wall_seconds"] = self._durations.get(
                "ffmpeg_process_wall_seconds", 0.0
            ) + max(0.0, process_wall_seconds)

    def active_process_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._active_process_ids)

    def record_sample(self, observation: SampleObservation) -> None:
        with self._lock:
            self._observations.append(observation)

    def snapshot(self) -> InstrumentationSnapshot:
        with self._lock:
            return InstrumentationSnapshot(
                durations=dict(self._durations),
                counters=dict(self._counters),
                peaks=dict(self._peaks),
                observations=tuple(self._observations),
            )
