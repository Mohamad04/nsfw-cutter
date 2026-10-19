"""Preliminary media validation, run before a video is reported as loaded (D9).

This is a bounded, quick check, not a guarantee that every frame decodes:

1. the file exists, is a regular file, is not empty and can be read;
2. ffprobe (the pinned project-local build) reads the container and stream metadata: the real
   container must match the extension (MP4 or MKV), there must be a usable video stream (not an
   audio-only file or a cover picture) with a codec name, a frame size and a positive duration;
3. ffprobe decodes the first video frame (the codec is decodable and the start is intact);
4. ffprobe reads, without decoding, the video packets of the last seconds: an incomplete file
   (interrupted download or copy) has none, or FFmpeg reports a partial file.

Damage in the middle of an otherwise complete file is not detected here; it surfaces later as an
analysis, playback or export error. Every ffprobe call has a timeout. Input files are only read.
"""

import json
import logging
import math
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner, ExportCancellationToken, FFmpegTimeoutError
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffprobe_path
from services.user_messages import english


logger = logging.getLogger(__name__)

SUPPORTED_CONTAINERS = {".mp4": "mov,mp4,m4a,3gp,3g2,mj2", ".mkv": "matroska,webm"}
CONTAINER_LABELS = {"mov,mp4,m4a,3gp,3g2,mj2": ("MP4", ".mp4"), "matroska,webm": ("MKV", ".mkv")}
HEADER_PROBE_TIMEOUT_SECONDS = 30.0
STREAM_CHECK_TIMEOUT_SECONDS = 60.0
TAIL_CHECK_SECONDS = 1.5
END_TOLERANCE_SECONDS = 1.0
DAMAGE_MARKERS = (
    "partial file",
    "file ended prematurely",
    "invalid data found",
    "moov atom not found",
    "error reading",
    "truncat",
)


class MediaValidationError(ValueError):
    """A file that cannot be loaded; ``str()`` is the user-facing message, ``detail`` is technical.

    ``code`` and ``params`` select the translated message shown in the interface
    (``services.user_messages``); without a code, ``message`` is shown as it is.
    """

    def __init__(self, category: str, message: str = "", detail: str = "", *, code: str = "", params=None):
        self.category = category
        self.detail = detail
        self.message_code = code
        self.message_params = dict(params or {})
        super().__init__(english(code, **self.message_params) if code else message)


def _rejected(category: str, code: str, detail: str = "", **params) -> MediaValidationError:
    return MediaValidationError(category, detail=detail, code=code, params=params)


@dataclass(frozen=True)
class MediaCheck:
    path: Path
    container: str
    duration_seconds: float
    video_codec: str
    width: int
    height: int
    has_audio: bool


def validate_media_file(
    file_path: str | Path,
    run=None,
    ffprobe_path: str | Path | None = None,
    cancel_token: ExportCancellationToken | None = None,
) -> MediaCheck:
    """Raises ``MediaValidationError``; with ``cancel_token``, a cancelled check stops its ffprobe and raises
    ``ExportCancelledError``."""
    run = run or (cancellable_run(cancel_token) if cancel_token is not None else subprocess.run)
    path = Path(file_path).expanduser()
    try:
        check = _validate(path, run, ffprobe_path)
    except MediaValidationError as exc:
        logger.warning("[Media validation] Rejected %s: %s (%s) %s", path, exc.category, exc, exc.detail)
        raise
    logger.info(
        "[Media validation] Accepted %s: %s %s %dx%d, %.3f s, audio=%s",
        path, check.container, check.video_codec, check.width, check.height, check.duration_seconds, check.has_audio,
    )
    return check


def _validate(path: Path, run, ffprobe_path) -> MediaCheck:
    name = path.name or str(path)
    if not path.exists():
        raise _rejected("missing_file", "media.missing_file", name=name)
    if not path.is_file():
        raise _rejected("not_a_file", "media.not_a_file", name=name)
    if path.suffix.lower() not in SUPPORTED_CONTAINERS:
        raise _rejected("unsupported_format", "media.unsupported_extension", name=name)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.read(16)
    except OSError as exc:
        raise _rejected("access_denied", "media.access_denied", repr(exc), name=name) from exc
    if size == 0:
        raise _rejected("corrupted_media", "media.empty", name=name)

    try:
        ffprobe = str(ffprobe_path or get_ffprobe_path())
    except FFmpegNotFoundError as exc:
        raise _rejected("ffmpeg_unavailable", "media.ffmpeg_unavailable", str(exc)) from exc

    completed = _probe(run, [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                       HEADER_PROBE_TIMEOUT_SECONDS, name)
    if completed.returncode != 0:
        raise _damaged(name, completed.stderr)
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise _damaged(name, f"ffprobe returned invalid JSON: {exc}") from exc

    format_data = payload.get("format") or {}
    container = str(format_data.get("format_name") or "")
    expected = SUPPORTED_CONTAINERS[path.suffix.lower()]
    if container != expected:
        if container in CONTAINER_LABELS:
            label, extension = CONTAINER_LABELS[container]
            raise _rejected("wrong_extension", "media.wrong_extension", f"format_name={container}",
                            name=name, label=label, suffix=path.suffix.lower(), extension=extension)
        raise _rejected("unsupported_format", "media.unsupported_container", f"format_name={container}",
                        name=name, container=container or "unknown")

    streams = payload.get("streams") or []
    videos = [
        stream for stream in streams
        if stream.get("codec_type") == "video" and not (stream.get("disposition") or {}).get("attached_pic")
    ]
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    if not videos:
        if any(stream.get("codec_type") == "video" for stream in streams):
            code = "media.no_video_cover"
        else:
            code = "media.no_video_audio_only" if has_audio else "media.no_video_empty"
        raise _rejected("no_video", code, f"streams={_stream_summary(streams)}", name=name)

    video = videos[0]
    codec = str(video.get("codec_name") or "")
    if not codec or codec == "none":
        raise _rejected("unsupported_codec", "media.unknown_codec", f"stream={video}", name=name)
    width, height = _positive_int(video.get("width")), _positive_int(video.get("height"))
    duration = _positive_float(format_data.get("duration")) or _positive_float(video.get("duration"))
    if not width or not height or not duration:
        raise _rejected(
            "corrupted_media", "media.invalid_video_info",
            f"width={video.get('width')} height={video.get('height')} duration={format_data.get('duration')}",
            name=name,
        )

    stream_index = str(video.get("index", 0))
    tail_start = max(0.0, duration - TAIL_CHECK_SECONDS)
    head_command = [ffprobe, "-v", "error", "-select_streams", stream_index, "-read_intervals", "%+#1",
                    "-show_entries", "frame=pts_time", "-of", "json", str(path)]
    tail_command = [ffprobe, "-v", "error", "-select_streams", stream_index, "-read_intervals", f"{tail_start:.3f}%",
                    "-show_entries", "packet=pts_time,duration_time", "-of", "json", str(path)]
    # Both checks run at once: starting the bundled ffprobe alone costs about 0.5 s on Windows.
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(_probe, run, head_command, STREAM_CHECK_TIMEOUT_SECONDS, name)
        tail_future = pool.submit(_probe, run, tail_command, STREAM_CHECK_TIMEOUT_SECONDS, name)
        first, tail = first_future.result(), tail_future.result()

    if first.returncode != 0 or not _entries(first.stdout, "frames"):
        if first.returncode != 0 and _has_damage_marker(first.stderr):
            raise _damaged(name, first.stderr)
        raise _rejected("unsupported_codec", "media.undecodable", first.stderr.strip()[-500:], name=name, codec=codec)

    packets = _entries(tail.stdout, "packets")
    video_duration = _stream_duration(video)
    last_end = _last_packet_end(packets)
    incomplete = (
        tail.returncode != 0
        or not packets
        or _has_damage_marker(tail.stderr)
        or (video_duration is not None and last_end is not None and last_end < video_duration - END_TOLERANCE_SECONDS)
    )
    if incomplete:
        raise _rejected(
            "corrupted_media", "media.incomplete",
            f"tail packets={len(packets)} last_end={last_end} video_duration={video_duration} "
            f"stderr={tail.stderr.strip()[-500:]}",
            name=name,
        )

    return MediaCheck(path.resolve(), container, duration, codec, width, height, has_audio)


def cancellable_run(cancel_token: ExportCancellationToken):
    """``subprocess.run`` stand-in: same timeout, but cancelling the token terminates the running ffprobe."""

    def run(command, timeout=None, **_kwargs):
        runner = BoundedProcessRunner(cancel_token=cancel_token, stall_timeout_seconds=timeout,
                                      max_runtime_seconds=timeout)
        try:
            return runner(command, text=True, encoding="utf-8", errors="replace")
        except FFmpegTimeoutError as exc:
            raise subprocess.TimeoutExpired(command, timeout) from exc

    return run


def _probe(run, command: list[str], timeout: float, name: str) -> subprocess.CompletedProcess:
    try:
        return run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise _rejected("timeout", "media.timeout", " ".join(command), name=name, seconds=f"{timeout:g}") from exc
    except OSError as exc:
        raise _rejected("ffmpeg_unavailable", "media.ffmpeg_not_started", repr(exc)) from exc


def _damaged(name: str, stderr: str) -> MediaValidationError:
    return _rejected("corrupted_media", "media.damaged", (stderr or "").strip()[-500:], name=name)


def _has_damage_marker(stderr: str) -> bool:
    text = (stderr or "").casefold()
    return any(marker in text for marker in DAMAGE_MARKERS)


def _entries(stdout: str, key: str) -> list[dict]:
    try:
        return list((json.loads(stdout or "{}") or {}).get(key) or [])
    except json.JSONDecodeError:
        return []


def _last_packet_end(packets: list[dict]) -> float | None:
    ends = [
        start + (_positive_float(packet.get("duration_time")) or 0.0)
        for packet in packets
        if (start := _finite_float(packet.get("pts_time"))) is not None
    ]
    return max(ends) if ends else None


def _stream_duration(stream: dict) -> float | None:
    duration = _positive_float(stream.get("duration"))
    if duration:
        return duration
    tag = (stream.get("tags") or {}).get("DURATION")
    if not tag:
        return None
    try:
        hours, minutes, seconds = str(tag).split(":")
        return _positive_float(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
    except ValueError:
        return None


def _stream_summary(streams: list[dict]) -> list[tuple]:
    return [(s.get("codec_type"), s.get("codec_name"), (s.get("disposition") or {}).get("attached_pic")) for s in streams]


def _finite_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_float(value) -> float | None:
    parsed = _finite_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
