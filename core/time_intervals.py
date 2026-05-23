from collections.abc import Iterable

from core.time_utils import seconds_to_ffmpeg_time, timecode_to_seconds


def parse_time_to_seconds(value: str) -> float:
    return timecode_to_seconds(value)


def seconds_to_timestamp(seconds: float) -> str:
    return seconds_to_ffmpeg_time(seconds)


def normalize_intervals(
    intervals: Iterable[tuple[float, float]],
    video_duration: float,
) -> list[tuple[float, float]]:
    duration = _positive_duration(video_duration)
    normalized = []

    for start_seconds, end_seconds in intervals:
        start = max(0.0, min(float(start_seconds), duration))
        end = max(0.0, min(float(end_seconds), duration))
        if end <= start:
            raise ValueError("End time must be after start time.")
        normalized.append((start, end))

    normalized.sort(key=lambda interval: (interval[0], interval[1]))
    merged: list[tuple[float, float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))

    return merged


def invert_removed_intervals(
    removed_intervals: Iterable[tuple[float, float]],
    video_duration: float,
) -> list[tuple[float, float]]:
    duration = _positive_duration(video_duration)
    normalized_removed = normalize_intervals(removed_intervals, duration)
    kept = []
    keep_start = 0.0

    for remove_start, remove_end in normalized_removed:
        if remove_start > keep_start:
            kept.append((keep_start, remove_start))
        keep_start = max(keep_start, remove_end)

    if keep_start < duration:
        kept.append((keep_start, duration))
    return kept


def intervals_duration(intervals: Iterable[tuple[float, float]]) -> float:
    return sum(max(0.0, float(end) - float(start)) for start, end in intervals)


def _positive_duration(video_duration: float) -> float:
    duration = float(video_duration)
    if duration <= 0:
        raise ValueError("Video duration must be greater than zero.")
    return duration
