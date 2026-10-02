from __future__ import annotations

import os
import queue
import subprocess
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from services.analysis.cancellation import AnalysisCancelled, CancellationToken

if TYPE_CHECKING:
    from services.analysis.preprocessing_instrumentation import (
        PreprocessingInstrumentation,
    )


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class _MeasuredBinaryQueue(queue.Queue[bytes | object]):
    """Bounded queue that records exact occupancy while holding Queue's mutex."""

    def __init__(
        self,
        instrumentation: PreprocessingInstrumentation,
        *,
        maxsize: int,
    ) -> None:
        super().__init__(maxsize=maxsize)
        self.instrumentation = instrumentation
        self.queued_bytes = 0
        self.queued_items = 0

    def _put(self, item: bytes | object) -> None:
        super()._put(item)
        if isinstance(item, bytes):
            self.queued_bytes += len(item)
            self.queued_items += 1
            self.instrumentation.update_peak("stdout_queue_bytes", self.queued_bytes)
            self.instrumentation.update_peak("stdout_queue_items", self.queued_items)

    def _get(self) -> bytes | object:
        item = super()._get()
        if isinstance(item, bytes):
            self.queued_bytes = max(0, self.queued_bytes - len(item))
            self.queued_items = max(0, self.queued_items - 1)
        return item


class CancellableProcessRunner:
    """Run a child process without a shell and terminate it cooperatively."""

    def __init__(
        self,
        instrumentation: PreprocessingInstrumentation | None = None,
    ) -> None:
        self._active_processes: set[subprocess.Popen] = set()
        self._active_processes_lock = threading.Lock()
        self.instrumentation = instrumentation

    @property
    def active_process_count(self) -> int:
        with self._active_processes_lock:
            return len(self._active_processes)

    def run(
        self,
        command: list[str | Path],
        *,
        cancellation: CancellationToken,
        check: bool = True,
    ) -> ProcessResult:
        normalized_command = [str(part) for part in command]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                normalized_command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creation_flags,
            )
            self._register_process(process)
            try:
                while process.poll() is None:
                    if cancellation.is_cancelled:
                        _stop_process(process)
                        raise AnalysisCancelled("Video analysis was cancelled")
                    cancellation.wait(0.1)
            except BaseException:
                if process.poll() is None:
                    _stop_process(process)
                raise
            finally:
                self._unregister_process(process)

            stdout_file.seek(0)
            stderr_file.seek(0)
            result = ProcessResult(
                returncode=int(process.returncode or 0),
                stdout=stdout_file.read().decode("utf-8", errors="replace"),
                stderr=stderr_file.read().decode("utf-8", errors="replace"),
            )

        if check and result.returncode != 0:
            detail = _last_non_empty_line(result.stderr) or "Media processing command failed"
            raise RuntimeError(detail)
        return result

    def stream_stdout(
        self,
        command: list[str | Path],
        *,
        cancellation: CancellationToken,
        stderr_callback: Callable[[str], None] | None = None,
        chunk_size: int = 64 * 1024,
        check: bool = True,
    ) -> Iterator[bytes]:
        """Yield binary stdout while draining stderr and honoring cancellation.

        Small dedicated pipe-drain threads prevent FFmpeg from blocking when either
        pipe fills. They perform I/O only; preprocessing remains sequential.
        """
        if chunk_size <= 0:
            raise ValueError("stream chunk size must be positive")

        normalized_command = [str(part) for part in command]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process_started_at = (
            time.perf_counter() if self.instrumentation is not None else 0.0
        )
        process = subprocess.Popen(
            normalized_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
            bufsize=0,
        )
        self._register_process(process)
        if self.instrumentation is not None:
            process_launched_at = time.perf_counter()
            self.instrumentation.process_started(
                process.pid,
                process_launched_at - process_started_at,
            )

        if self.instrumentation is None:
            stdout_queue: queue.Queue[bytes | object] = queue.Queue(maxsize=8)
        else:
            stdout_queue = _MeasuredBinaryQueue(
                self.instrumentation,
                maxsize=8,
            )
        reader_errors: queue.Queue[BaseException] = queue.Queue()
        stderr_tail: deque[str] = deque(maxlen=100)
        stop_readers = threading.Event()
        stdout_finished = object()

        def put_stdout(value: bytes | object) -> None:
            while not stop_readers.is_set():
                try:
                    stdout_queue.put(value, timeout=0.05)
                    return
                except queue.Full:
                    continue

        def read_stdout() -> None:
            first_stdout = True
            try:
                assert process.stdout is not None
                while not stop_readers.is_set():
                    value = process.stdout.read(chunk_size)
                    if not value:
                        break
                    if self.instrumentation is not None:
                        if first_stdout:
                            self.instrumentation.process_first_stdout(
                                time.perf_counter() - process_started_at
                            )
                            first_stdout = False
                        self.instrumentation.increment(
                            "raw_rgb_bytes_received",
                            len(value),
                        )
                        self.instrumentation.increment("stdout_blocks_received")
                    put_stdout(value)
            except BaseException as exc:  # pragma: no cover - OS pipe failure
                reader_errors.put(exc)
            finally:
                put_stdout(stdout_finished)

        def read_stderr() -> None:
            try:
                assert process.stderr is not None
                while not stop_readers.is_set():
                    value = process.stderr.readline()
                    if not value:
                        break
                    line = value.decode("utf-8", errors="replace").rstrip("\r\n")
                    stderr_tail.append(line)
                    if stderr_callback is not None:
                        stderr_callback(line)
            except BaseException as exc:
                reader_errors.put(exc)

        stdout_thread = threading.Thread(
            target=read_stdout,
            name="analysis-stdout-drain",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stderr,
            name="analysis-stderr-drain",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            while True:
                if cancellation.is_cancelled:
                    _stop_process(process)
                    raise AnalysisCancelled("Video analysis was cancelled")
                _raise_reader_error(reader_errors)
                try:
                    value = stdout_queue.get(timeout=0.05)
                except queue.Empty:
                    if process.poll() is not None and not stdout_thread.is_alive():
                        break
                    continue
                if value is stdout_finished:
                    break
                if not isinstance(value, bytes):  # pragma: no cover - queue invariant
                    raise RuntimeError("Unexpected binary process stream value")
                yield value

            returncode = process.wait()
            stderr_thread.join(timeout=2.0)
            _raise_reader_error(reader_errors)
            if check and returncode != 0:
                detail = _last_non_empty_line("\n".join(stderr_tail))
                raise RuntimeError(detail or "Media processing command failed")
        except BaseException:
            if process.poll() is None:
                _stop_process(process)
            raise
        finally:
            stop_readers.set()
            if process.poll() is None:
                _stop_process(process)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)
            self._unregister_process(process)
            if self.instrumentation is not None:
                self.instrumentation.process_finished(
                    process.pid,
                    time.perf_counter() - process_started_at,
                )

    def _register_process(self, process: subprocess.Popen) -> None:
        with self._active_processes_lock:
            self._active_processes.add(process)

    def _unregister_process(self, process: subprocess.Popen) -> None:
        with self._active_processes_lock:
            self._active_processes.discard(process)


def _stop_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _last_non_empty_line(value: str) -> str:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _raise_reader_error(errors: queue.Queue[BaseException]) -> None:
    try:
        error = errors.get_nowait()
    except queue.Empty:
        return
    raise error
