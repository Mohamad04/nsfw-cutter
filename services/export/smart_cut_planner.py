from dataclasses import dataclass
from math import isclose

from core.time_intervals import invert_removed_intervals, normalize_intervals


COPY_SEGMENT = "copy"
REENCODE_SEGMENT = "reencode"
DELETE_SEGMENT = "delete"
MIN_SEGMENT_DURATION_SECONDS = 0.001
KEYFRAME_TOLERANCE_SECONDS = 0.002


@dataclass(frozen=True)
class SmartCutPlanSegment:
    type: str
    start_seconds: float
    end_seconds: float
    decode_start_seconds: float | None = None

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)

    def to_dict(self) -> dict:
        payload = {
            "type": self.type,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "duration_seconds": self.duration_seconds,
        }
        if self.decode_start_seconds is not None:
            payload["decode_start_seconds"] = self.decode_start_seconds
        return payload


@dataclass(frozen=True)
class SmartCutPlan:
    duration_seconds: float
    keyframes: list[float]
    delete_intervals: list[tuple[float, float]]
    segments: list[SmartCutPlanSegment]

    def to_dict(self) -> dict:
        return {
            "duration_seconds": self.duration_seconds,
            "keyframes": self.keyframes,
            "delete_intervals": self.delete_intervals,
            "segments": [segment.to_dict() for segment in self.segments],
        }


class SmartCutPlanner:
    def build_plan(
        self,
        delete_intervals: list[tuple[float, float]],
        keyframes: list[float],
        duration_seconds: float,
    ) -> SmartCutPlan:
        duration = _round_time(duration_seconds)
        normalized_deletes = normalize_intervals(delete_intervals, duration)
        normalized_keyframes = _normalize_keyframes(keyframes, duration)
        kept_intervals = invert_removed_intervals(normalized_deletes, duration)
        if not kept_intervals:
            raise ValueError("Removed intervals cover the full video.")

        segments: list[SmartCutPlanSegment] = []
        for start_seconds, end_seconds in normalized_deletes:
            _append_segment(segments, DELETE_SEGMENT, start_seconds, end_seconds)

        delete_starts = {start for start, _ in normalized_deletes}
        delete_ends = {end for _, end in normalized_deletes}
        for kept_start, kept_end in kept_intervals:
            segments.extend(
                self._kept_segments(
                    kept_start,
                    kept_end,
                    normalized_keyframes,
                    delete_starts,
                    delete_ends,
                    duration,
                )
            )

        segments.sort(key=lambda segment: (segment.start_seconds, _segment_priority(segment), segment.end_seconds))
        return SmartCutPlan(
            duration_seconds=duration,
            keyframes=normalized_keyframes,
            delete_intervals=normalized_deletes,
            segments=segments,
        )

    def _kept_segments(
        self,
        kept_start: float,
        kept_end: float,
        keyframes: list[float],
        delete_starts: set[float],
        delete_ends: set[float],
        duration: float,
    ) -> list[SmartCutPlanSegment]:
        reencode_ranges: list[tuple[float, float, float]] = []

        if _touches_boundary(kept_end, delete_starts) and not _is_keyframe(kept_end, keyframes, duration):
            previous_keyframe = _previous_keyframe(keyframes, kept_end)
            reencode_start = max(kept_start, previous_keyframe)
            if reencode_start < kept_end:
                reencode_ranges.append((reencode_start, kept_end, previous_keyframe))

        if _touches_boundary(kept_start, delete_ends) and not _is_keyframe(kept_start, keyframes, duration):
            next_keyframe = _next_keyframe(keyframes, kept_start, duration)
            decode_start = _previous_keyframe(keyframes, kept_start)
            reencode_end = min(kept_end, next_keyframe)
            if kept_start < reencode_end:
                reencode_ranges.append((kept_start, reencode_end, decode_start))

        reencode_ranges = _merge_reencode_ranges(reencode_ranges)
        kept_segments: list[SmartCutPlanSegment] = []
        cursor = kept_start
        for reencode_start, reencode_end, decode_start in reencode_ranges:
            if cursor < reencode_start:
                _append_segment(kept_segments, COPY_SEGMENT, cursor, reencode_start)
            _append_segment(kept_segments, REENCODE_SEGMENT, reencode_start, reencode_end, decode_start)
            cursor = max(cursor, reencode_end)

        if cursor < kept_end:
            _append_segment(kept_segments, COPY_SEGMENT, cursor, kept_end)
        return kept_segments


def _normalize_keyframes(keyframes: list[float], duration: float) -> list[float]:
    normalized = sorted(
        {
            _round_time(keyframe)
            for keyframe in keyframes
            if 0 <= float(keyframe) <= duration
        }
    )
    if not normalized:
        raise ValueError("Smart Cutting cannot compute exact cuts because keyframes are unavailable.")
    if not _is_keyframe(0.0, normalized, duration):
        normalized.insert(0, 0.0)
    return normalized


def _previous_keyframe(keyframes: list[float], timestamp: float) -> float:
    previous = keyframes[0]
    for keyframe in keyframes:
        if keyframe - timestamp > KEYFRAME_TOLERANCE_SECONDS:
            break
        previous = keyframe
    return previous


def _next_keyframe(keyframes: list[float], timestamp: float, duration: float) -> float:
    for keyframe in keyframes:
        if keyframe - timestamp > KEYFRAME_TOLERANCE_SECONDS:
            return keyframe
    return duration


def _merge_reencode_ranges(ranges: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if not ranges:
        return []

    ranges = sorted(ranges, key=lambda item: (item[0], item[1]))
    merged: list[tuple[float, float, float]] = [ranges[0]]
    for start, end, decode_start in ranges[1:]:
        last_start, last_end, last_decode_start = merged[-1]
        if start <= last_end + KEYFRAME_TOLERANCE_SECONDS:
            merged[-1] = (last_start, max(last_end, end), min(last_decode_start, decode_start))
        else:
            merged.append((start, end, decode_start))
    return merged


def _append_segment(
    segments: list[SmartCutPlanSegment],
    segment_type: str,
    start_seconds: float,
    end_seconds: float,
    decode_start_seconds: float | None = None,
) -> None:
    start = _round_time(start_seconds)
    end = _round_time(end_seconds)
    if end - start < MIN_SEGMENT_DURATION_SECONDS:
        return
    decode_start = _round_time(decode_start_seconds) if decode_start_seconds is not None else None
    segments.append(SmartCutPlanSegment(segment_type, start, end, decode_start))


def _is_keyframe(timestamp: float, keyframes: list[float], duration: float) -> bool:
    if isclose(timestamp, duration, abs_tol=KEYFRAME_TOLERANCE_SECONDS):
        return True
    return any(isclose(timestamp, keyframe, abs_tol=KEYFRAME_TOLERANCE_SECONDS) for keyframe in keyframes)


def _touches_boundary(timestamp: float, boundaries: set[float]) -> bool:
    return any(isclose(timestamp, boundary, abs_tol=KEYFRAME_TOLERANCE_SECONDS) for boundary in boundaries)


def _round_time(value: float | None) -> float:
    return round(float(value), 3)


def _segment_priority(segment: SmartCutPlanSegment) -> int:
    return {
        COPY_SEGMENT: 0,
        REENCODE_SEGMENT: 1,
        DELETE_SEGMENT: 2,
    }.get(segment.type, 3)
