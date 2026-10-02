from __future__ import annotations

from threading import Event


class AnalysisCancelled(RuntimeError):
    """Raised when an analysis run is cooperatively cancelled."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise AnalysisCancelled("Video analysis was cancelled")
