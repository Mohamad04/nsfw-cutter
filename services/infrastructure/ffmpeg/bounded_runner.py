"""Bounded, cancellable execution of FFmpeg/ffprobe commands for exports.

``BoundedProcessRunner`` is a drop-in replacement for the ``subprocess.run`` calls made by the
export services (same call shape, returns ``subprocess.CompletedProcess``). It adds:

- a stall watchdog: a command whose progress does not advance for ``stall_timeout_seconds`` is
  terminated and raises ``FFmpegTimeoutError``. Progress is the ``time=`` value FFmpeg prints in its
  statistics, or new bytes on stdout (ffprobe). A hung encoder keeps printing statistics with a
  frozen ``time=``, so it is detected, while a long export that keeps advancing is never stopped;
- an optional absolute limit (``max_runtime_seconds``, off by default);
- cooperative cancellation through ``ExportCancellationToken``: the running process is terminated
  and ``ExportCancelledError`` is raised; commands started after cancellation are refused.
"""

import os
import re
import subprocess
import threading
import time
from pathlib import Path


STALL_TIMEOUT_ENV = "NSFW_CUTTER_FFMPEG_STALL_TIMEOUT_SECONDS"
DEFAULT_STALL_TIMEOUT_SECONDS = 180.0
POLL_INTERVAL_SECONDS = 0.1
_TIME_PATTERN = re.compile(rb"time=\s*(-?)(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


class ExportCancelledError(RuntimeError):
    pass


class FFmpegTimeoutError(RuntimeError):
    def __init__(self, command: list[str], reason: str, stderr: str):
        self.command = command
        self.reason = reason
        self.stderr = stderr
        super().__init__(
            f"FFmpeg was stopped: {reason}. The export was aborted and no output was kept. "
            f"Command: {Path(str(command[0])).name} … {Path(str(command[-1])).name}"
        )


class ExportCancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise ExportCancelledError("Video export was cancelled. No output was kept.")


def default_stall_timeout_seconds() -> float:
    value = os.environ.get(STALL_TIMEOUT_ENV, "")
    try:
        parsed = float(value)
    except ValueError:
        return DEFAULT_STALL_TIMEOUT_SECONDS
    return parsed if parsed > 0 else DEFAULT_STALL_TIMEOUT_SECONDS


class BoundedProcessRunner:
    def __init__(
        self,
        cancel_token: ExportCancellationToken | None = None,
        stall_timeout_seconds: float | None = None,
        max_runtime_seconds: float | None = None,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    ):
        self.cancel_token = cancel_token or ExportCancellationToken()
        self.stall_timeout_seconds = stall_timeout_seconds or default_stall_timeout_seconds()
        self.max_runtime_seconds = max_runtime_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.last_pid: int | None = None
        self.terminated_pids: list[int] = []

    def __call__(self, command, stdout=None, stderr=None, text=False, encoding=None, errors=None, **_kwargs):
        command = [str(part) for part in command]
        self.cancel_token.raise_if_cancelled()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.last_pid = process.pid
        out_reader = _StreamReader(process.stdout, track_time=False)
        err_reader = _StreamReader(process.stderr, track_time=True)
        started = time.monotonic()
        last_progress_at = started
        last_progress = (out_reader.size, err_reader.max_time)
        try:
            while True:
                try:
                    process.wait(timeout=self.poll_interval_seconds)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self.cancel_token.is_cancelled:
                    self._terminate(process)
                    raise ExportCancelledError("Video export was cancelled. No output was kept.")
                now = time.monotonic()
                progress = (out_reader.size, err_reader.max_time)
                if progress != last_progress:
                    last_progress, last_progress_at = progress, now
                elif now - last_progress_at > self.stall_timeout_seconds:
                    self._terminate(process)
                    raise FFmpegTimeoutError(
                        command,
                        f"no progress for {self.stall_timeout_seconds:g} s (stuck at {err_reader.max_time:.2f} s of output)",
                        err_reader.text(),
                    )
                if self.max_runtime_seconds is not None and now - started > self.max_runtime_seconds:
                    self._terminate(process)
                    raise FFmpegTimeoutError(
                        command,
                        f"running longer than the {self.max_runtime_seconds:g} s limit",
                        err_reader.text(),
                    )
        finally:
            out_reader.join()
            err_reader.join()
        return subprocess.CompletedProcess(
            command,
            process.returncode,
            _decode(out_reader.data(), text, encoding, errors),
            _decode(err_reader.data(), text, encoding, errors),
        )

    def _terminate(self, process: subprocess.Popen) -> None:
        self.terminated_pids.append(process.pid)
        _terminate(process)


class _StreamReader:
    def __init__(self, stream, track_time: bool):
        self._chunks: list[bytes] = []
        self._tail = b""
        self.size = 0
        self.max_time = -1.0
        self._track_time = track_time
        self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self._thread.start()

    def _read(self, stream) -> None:
        for chunk in iter(lambda: stream.read1(65536), b""):
            self._chunks.append(chunk)
            self.size += len(chunk)
            if self._track_time:
                window = self._tail + chunk
                for sign, hours, minutes, seconds in _TIME_PATTERN.findall(window):
                    value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    self.max_time = max(self.max_time, -value if sign else value)
                self._tail = window[-64:]
        stream.close()

    def join(self) -> None:
        self._thread.join(timeout=10)

    def data(self) -> bytes:
        return b"".join(self._chunks)

    def text(self) -> str:
        return self.data()[-2000:].decode("utf-8", errors="replace")


def _decode(data: bytes, text: bool, encoding: str | None, errors: str | None):
    if not text and encoding is None:
        return data
    # Same universal-newline translation as subprocess.run(text=True).
    text_value = data.decode(encoding or "utf-8", errors=errors or "strict")
    return text_value.replace("\r\n", "\n").replace("\r", "\n")


def _terminate(process: subprocess.Popen) -> None:
    """Stop FFmpeg and any child it started (FFmpeg normally starts none)."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
            check=False,
        )
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
