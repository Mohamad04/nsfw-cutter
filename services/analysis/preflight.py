from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    MediaSummary,
    PreflightResult,
)
from services.infrastructure.ffmpeg.probe import probe_media
from services.media.validation_service import validate_input_video

ProgressCallback = Callable[[int, str], None]


class FileFingerprintService:
    """Compute a path-independent SHA-256 fingerprint with cooperative cancellation."""

    def __init__(self, chunk_size: int = 4 * 1024 * 1024) -> None:
        self.chunk_size = max(64 * 1024, int(chunk_size))

    def fingerprint(
        self,
        video_path: str | Path,
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        path = Path(video_path)
        total_size = path.stat().st_size
        if total_size <= 0:
            raise ValueError("Selected video file is empty")

        digest = hashlib.sha256()
        processed = 0
        with path.open("rb") as source:
            while True:
                cancellation.raise_if_cancelled()
                chunk = source.read(self.chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                processed += len(chunk)
                if progress_callback is not None:
                    percent = min(80, max(10, int(processed * 80 / total_size)))
                    progress_callback(percent, "Fingerprinting selected video")
        return f"sha256:{digest.hexdigest()}"


class PreflightService:
    def __init__(
        self,
        *,
        cache: AnalysisCache | None = None,
        fingerprint_service: FileFingerprintService | None = None,
        media_probe=None,
    ) -> None:
        self.cache = cache or AnalysisCache()
        self.fingerprint_service = fingerprint_service or FileFingerprintService()
        self.media_probe = media_probe or probe_media

    def run(
        self,
        video_path: str | Path,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
        *,
        selected_subtitle: dict | None = None,
    ) -> tuple[Path, PreflightResult]:
        cancellation.raise_if_cancelled()
        resolved_path = validate_input_video(video_path)
        if progress_callback is not None:
            progress_callback(0, "Validating selected video")

        fingerprint = self.fingerprint_service.fingerprint(
            resolved_path,
            cancellation,
            progress_callback,
        )
        cancellation.raise_if_cancelled()
        text_source_fingerprint = fingerprint_text_source(
            selected_subtitle,
            cancellation,
        )
        payload = self.media_probe(resolved_path)
        media = _media_summary(payload)
        cache_key = self.cache.make_key(
            fingerprint,
            settings,
            text_source_fingerprint,
        )
        if progress_callback is not None:
            progress_callback(100, "Video preflight complete")
        return resolved_path, PreflightResult(
            video_fingerprint=fingerprint,
            text_source_fingerprint=text_source_fingerprint,
            media=media,
            cache_key=cache_key,
        )


def fingerprint_text_source(
    selected_subtitle: dict | None,
    cancellation: CancellationToken,
) -> str:
    """Fingerprint selected text evidence without retaining a subtitle path."""
    if not selected_subtitle or not selected_subtitle.get("is_text_readable"):
        return "audio-fallback:v1"

    source = str(selected_subtitle.get("source") or "").strip().casefold()
    if source == "embedded":
        stream_index = selected_subtitle.get(
            "stream_index",
            selected_subtitle.get("index"),
        )
        if stream_index is None:
            return "audio-fallback:unreadable-subtitle:v1"
        selector = f"embedded-stream:{int(stream_index)}:v1"
        digest = hashlib.sha256(selector.encode("utf-8")).hexdigest()
        return f"embedded-sha256:{digest}"

    if source != "external":
        return "audio-fallback:unreadable-subtitle:v1"
    subtitle_path_value = selected_subtitle.get("file_path") or selected_subtitle.get("path")
    if not subtitle_path_value:
        return "audio-fallback:unreadable-subtitle:v1"

    subtitle_path = Path(subtitle_path_value).expanduser()
    try:
        if not subtitle_path.is_file():
            return "audio-fallback:unreadable-subtitle:v1"
        digest = hashlib.sha256()
        with subtitle_path.open("rb") as subtitle_file:
            while True:
                cancellation.raise_if_cancelled()
                chunk = subtitle_file.read(256 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return "audio-fallback:unreadable-subtitle:v1"
    return f"subtitle-sha256:{digest.hexdigest()}"


def _media_summary(payload: dict) -> MediaSummary:
    raw_streams = payload.get("streams") or []
    video_streams = [stream for stream in raw_streams if stream.get("codec_type") == "video"]
    if not video_streams:
        raise ValueError("Selected media has no readable video stream")

    format_payload = payload.get("format") or {}
    duration = _positive_float(format_payload.get("duration"))
    if duration is None:
        duration = next(
            (
                value
                for value in (_positive_float(stream.get("duration")) for stream in raw_streams)
                if value is not None
            ),
            None,
        )
    if duration is None:
        raise ValueError("Unable to determine video duration")

    primary_video = video_streams[0]
    fps = _parse_frame_rate(
        primary_video.get("avg_frame_rate") or primary_video.get("r_frame_rate")
    )
    stream_summaries = [_stream_summary(stream) for stream in raw_streams]
    return MediaSummary(
        duration_seconds=duration,
        fps=fps,
        format_name=str(format_payload.get("format_name") or ""),
        streams=stream_summaries,
    )


def _stream_summary(stream: dict) -> dict:
    tags = stream.get("tags") or {}
    allowed_fields = (
        "index",
        "codec_type",
        "codec_name",
        "width",
        "height",
        "sample_rate",
        "channels",
    )
    summary = {key: stream.get(key) for key in allowed_fields if stream.get(key) is not None}
    if tags.get("language"):
        summary["language"] = str(tags["language"])
    return summary


def _positive_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0.0 else None


def _parse_frame_rate(value) -> float:
    text = str(value or "").strip()
    if not text or text == "0/0":
        return 0.0
    if "/" not in text:
        return max(0.0, float(text))
    numerator, denominator = text.split("/", 1)
    denominator_value = float(denominator)
    if denominator_value == 0.0:
        return 0.0
    return max(0.0, float(numerator) / denominator_value)
