import json
import subprocess
from bisect import bisect_left, bisect_right
from pathlib import Path

from services.ffmpeg_service import FFmpegService


class KeyframeService:
    def __init__(self, ffmpeg_service: FFmpegService | None = None, probe_runner=None):
        self._ffmpeg_service = ffmpeg_service
        self.probe_runner = probe_runner or subprocess.run

    @property
    def ffmpeg_service(self) -> FFmpegService:
        if self._ffmpeg_service is None:
            self._ffmpeg_service = FFmpegService()
        return self._ffmpeg_service

    def extract_keyframes(self, input_path: str | Path) -> list[float]:
        command = [
            str(self.ffmpeg_service.ffprobe_path),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(input_path),
        ]
        completed = self.probe_runner(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Unable to read keyframes with ffprobe.")

        payload = json.loads(completed.stdout or "{}")
        keyframes = []
        for frame in payload.get("frames", []):
            value = frame.get("best_effort_timestamp_time")
            if value in (None, ""):
                continue
            keyframes.append(round(float(value), 3))
        return sorted(set(keyframes))

    def align_interval(
        self,
        keyframes: list[float],
        requested_start: float,
        requested_end: float,
        duration_seconds: float | None = None,
    ) -> dict:
        if requested_end <= requested_start:
            raise ValueError("End time must be after start time.")

        normalized_keyframes = sorted(set(round(float(value), 3) for value in keyframes if value is not None))
        if not normalized_keyframes:
            raise ValueError("Keyframe data unavailable. Safe stream-copy cut cannot be computed.")

        previous_start = previous_keyframe(normalized_keyframes, requested_start)
        next_start = next_keyframe(normalized_keyframes, requested_start, duration_seconds)
        previous_end = previous_keyframe(normalized_keyframes, requested_end)
        next_end = next_keyframe(normalized_keyframes, requested_end, duration_seconds)
        safe_start, safe_end = compute_safe_cut(
            requested_start,
            requested_end,
            normalized_keyframes,
            duration_seconds,
        )

        return {
            "valid": True,
            "requested_start": round(requested_start, 3),
            "requested_end": round(requested_end, 3),
            "safe_start": round(safe_start, 3),
            "safe_end": round(safe_end, 3),
            "previous_keyframe_start": previous_start,
            "next_keyframe_start": next_start,
            "previous_keyframe_end": previous_end,
            "next_keyframe_end": next_end,
            "extra_before": round(max(0.0, requested_start - safe_start), 3),
            "extra_after": round(max(0.0, safe_end - requested_end), 3),
        }


def previous_keyframe(keyframes: list[float], seconds: float) -> float | None:
    index = bisect_right(keyframes, seconds) - 1
    if index < 0:
        return None
    return keyframes[index]


def next_keyframe(keyframes: list[float], seconds: float, duration_seconds: float | None = None) -> float | None:
    index = bisect_left(keyframes, seconds)
    if index < len(keyframes):
        return keyframes[index]
    if duration_seconds is not None and duration_seconds > 0:
        return round(float(duration_seconds), 3)
    return None


def compute_safe_cut(
    requested_start: float,
    requested_end: float,
    keyframes: list[float],
    video_duration: float | None = None,
) -> tuple[float, float]:
    if requested_end <= requested_start:
        raise ValueError("End time must be after start time.")

    normalized_keyframes = sorted(set(round(float(value), 3) for value in keyframes if value is not None))
    if not normalized_keyframes:
        raise ValueError("Keyframe data unavailable. Safe stream-copy cut cannot be computed.")

    safe_start = previous_keyframe(normalized_keyframes, requested_start)
    if safe_start is None:
        safe_start = 0.0

    safe_end = next_keyframe(normalized_keyframes, requested_end, video_duration)
    if safe_end is None:
        raise ValueError("No next keyframe found after requested end. Safe stream-copy cut cannot be computed.")

    if video_duration is not None and video_duration > 0:
        duration = round(float(video_duration), 3)
        safe_start = max(0.0, min(round(float(safe_start), 3), duration))
        safe_end = max(0.0, min(round(float(safe_end), 3), duration))

    if safe_end <= safe_start:
        raise ValueError("Computed safe cut is invalid.")

    return round(float(safe_start), 3), round(float(safe_end), 3)
