import logging
from pathlib import Path

from core.time_utils import timecode_to_seconds


logger = logging.getLogger(__name__)


class KeyframeAlignmentController:
    def __init__(self, keyframe_service):
        self._keyframe_service = keyframe_service
        self._keyframe_cache: dict[str, list[float]] = {}

    def get_cut_info(
        self,
        input_path: str,
        requested_start: str,
        requested_end: str,
        duration_seconds: float = 0.0,
    ) -> dict:
        try:
            start_seconds = timecode_to_seconds(requested_start)
            end_seconds = timecode_to_seconds(requested_end)
            if end_seconds <= start_seconds:
                raise ValueError("End time must be after start time.")

            keyframes = self._keyframes_for_path(input_path)
            return self._keyframe_service.align_interval(
                keyframes,
                start_seconds,
                end_seconds,
                duration_seconds if duration_seconds > 0 else None,
            )
        except Exception as exc:
            logger.info("Unable to align keyframe interval: %s", exc)
            return fallback_keyframe_info(requested_start, requested_end, str(exc))

    def _keyframes_for_path(self, input_path: str) -> list[float]:
        video_path = Path(input_path)
        if not video_path.is_file():
            raise ValueError("Select a video before reading keyframes.")

        cache_key = str(video_path.resolve())
        if cache_key not in self._keyframe_cache:
            self._keyframe_cache[cache_key] = self._keyframe_service.extract_keyframes(video_path)
        return self._keyframe_cache[cache_key]


def fallback_keyframe_info(requested_start: str, requested_end: str, error: str) -> dict:
    try:
        start_seconds = timecode_to_seconds(requested_start)
        end_seconds = timecode_to_seconds(requested_end)
    except ValueError:
        start_seconds = 0.0
        end_seconds = 0.0

    return {
        "valid": False,
        "error": error,
        "requested_start": start_seconds,
        "requested_end": end_seconds,
        "safe_start": start_seconds,
        "safe_end": end_seconds,
        "previous_keyframe_start": start_seconds,
        "next_keyframe_start": start_seconds,
        "previous_keyframe_end": end_seconds,
        "next_keyframe_end": end_seconds,
        "extra_before": 0.0,
        "extra_after": 0.0,
    }
