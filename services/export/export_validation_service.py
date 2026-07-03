from pathlib import Path

from core.time_intervals import intervals_duration, normalize_intervals
from core.time_utils import timecode_to_seconds
from services.export.media_probe_service import MediaInfo


SUPPORTED_SMART_CUTTING_EXTENSIONS = {".mp4", ".mkv"}
SUPPORTED_SMART_CUTTING_FORMATS = {"mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm", "matroska"}
SMART_CUTTING_EXPORT_MODE = "remove_intervals"
SMART_VIDEO_DURATION_TOLERANCE_SECONDS = 0.75
SMART_AV_DURATION_TOLERANCE_SECONDS = 0.75


def validate_smart_cutting_input(media_info: MediaInfo) -> None:
    if Path(media_info.path).suffix.lower() not in SUPPORTED_SMART_CUTTING_EXTENSIONS:
        raise ValueError("Smart Cutting supports MP4 and MKV sources.")
    if not media_info.video_streams:
        raise ValueError("Smart Cutting requires a video stream.")
    if len(media_info.video_streams) != 1:
        raise ValueError("Smart Cutting currently supports one video stream.")
    if media_info.duration_seconds <= 0:
        raise ValueError("Smart Cutting requires a positive source duration.")

    video_stream = media_info.video_stream
    codec_name = (video_stream.codec_name or "").casefold() if video_stream else ""
    if codec_name not in {"h264", "avc1"}:
        raise ValueError("Smart Cutting currently supports H.264 video for hybrid boundary re-encoding.")
    pix_fmt = (video_stream.pix_fmt or "").casefold() if video_stream else ""
    if pix_fmt and pix_fmt != "yuv420p":
        raise ValueError("Smart Cutting currently supports yuv420p H.264 video for compatible chunk concatenation.")
    if not video_stream or not video_stream.width or not video_stream.height:
        raise ValueError("Smart Cutting could not read the source video dimensions.")


def validate_smart_export_mode(export_mode: str) -> None:
    if (export_mode or SMART_CUTTING_EXPORT_MODE) != SMART_CUTTING_EXPORT_MODE:
        raise ValueError("Smart Cutting only supports removing selected intervals.")


def validate_keyframes(keyframes: list[float], duration_seconds: float) -> list[float]:
    if not keyframes:
        raise ValueError("Smart Cutting cannot compute exact cuts because keyframes are unavailable or still indexing.")
    normalized = sorted({round(float(value), 3) for value in keyframes if 0 <= float(value) <= duration_seconds})
    if not normalized:
        raise ValueError("Smart Cutting cannot compute exact cuts because keyframes are unavailable or still indexing.")
    if normalized[0] > 0.002:
        normalized.insert(0, 0.0)
    return normalized


def requested_delete_intervals(segments: list[dict], duration_seconds: float) -> list[tuple[float, float]]:
    intervals = []
    for segment in segments:
        start = _segment_seconds(
            segment,
            "requested_start_seconds",
            "requestedStartSeconds",
            "start_seconds",
            "startSeconds",
            "start",
        )
        end = _segment_seconds(
            segment,
            "requested_end_seconds",
            "requestedEndSeconds",
            "end_seconds",
            "endSeconds",
            "end",
        )
        if start is None:
            raise ValueError("Requested cut start is unavailable.")
        if end is None:
            raise ValueError("Requested cut end is unavailable.")
        intervals.append((start, end))
    return normalize_intervals(intervals, duration_seconds)


def validate_video_only_output(
    media_info: MediaInfo,
    expected_duration_seconds: float,
    tolerance_seconds: float = SMART_VIDEO_DURATION_TOLERANCE_SECONDS,
) -> None:
    if not media_info.video_streams:
        raise ValueError("Smart Cutting video intermediate does not contain a video stream.")
    if media_info.audio_streams:
        raise ValueError("Smart Cutting video intermediate unexpectedly contains audio.")
    if media_info.subtitle_streams:
        raise ValueError("Smart Cutting video intermediate unexpectedly contains subtitles.")
    _validate_duration(media_info.duration_seconds, expected_duration_seconds, tolerance_seconds)


def validate_final_output(
    media_info: MediaInfo,
    expected_duration_seconds: float,
    input_had_audio: bool,
    expected_subtitle_stream: bool,
    duration_tolerance_seconds: float = SMART_VIDEO_DURATION_TOLERANCE_SECONDS,
    av_tolerance_seconds: float = SMART_AV_DURATION_TOLERANCE_SECONDS,
) -> None:
    if not media_info.video_streams:
        raise ValueError("Smart Cutting final output does not contain a video stream.")
    if input_had_audio and not media_info.audio_streams:
        raise ValueError("Smart Cutting final output is missing audio.")
    if expected_subtitle_stream and not media_info.subtitle_streams:
        raise ValueError("Smart Cutting final output is missing rebuilt subtitles.")
    _validate_duration(media_info.duration_seconds, expected_duration_seconds, duration_tolerance_seconds)

    video_duration = media_info.video_stream.duration_seconds if media_info.video_stream else None
    if video_duration is None:
        video_duration = media_info.duration_seconds
    for audio_stream in media_info.audio_streams:
        if audio_stream.duration_seconds is None:
            continue
        if abs(video_duration - audio_stream.duration_seconds) > av_tolerance_seconds:
            raise ValueError("Smart Cutting final output audio duration does not match video duration.")


def expected_edited_duration(duration_seconds: float, delete_intervals: list[tuple[float, float]]) -> float:
    return round(float(duration_seconds) - intervals_duration(delete_intervals), 3)


def _validate_duration(actual_duration: float, expected_duration: float, tolerance_seconds: float) -> None:
    if abs(float(actual_duration) - float(expected_duration)) > tolerance_seconds:
        raise ValueError(
            f"Smart Cutting output duration is {actual_duration:.3f}s, expected about {expected_duration:.3f}s."
        )


def _segment_seconds(segment: dict, *keys: str) -> float | None:
    for key in keys:
        value = segment.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if ":" in text:
            return timecode_to_seconds(text)
        return float(text)
    return None
