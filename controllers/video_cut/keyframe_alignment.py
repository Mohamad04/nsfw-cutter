import logging
from pathlib import Path

from core.time_utils import timecode_to_seconds
from services.editing.cut_plan_service import CutPlanService


logger = logging.getLogger(__name__)


class KeyframeAlignmentController:
    def __init__(self, keyframe_service, cut_plan_service=None):
        self._keyframe_service = keyframe_service
        self._cut_plan_service = cut_plan_service or CutPlanService()

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
            return self._cut_plan_service.align_interval(
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
        keyframes = self._keyframe_service.get_cached_keyframes(video_path)
        if keyframes is not None:
            return keyframes

        if self._keyframe_service.active_media_path == cache_key:
            if self._keyframe_service.keyframe_state == "loading":
                raise ValueError("Keyframes are still being indexed. Try again shortly.")
            if self._keyframe_service.keyframe_state == "error":
                error = self._keyframe_service.keyframe_error or "Unknown FFprobe error."
                raise ValueError(f"Keyframe analysis failed: {error}")

        raise ValueError("Keyframe cache unavailable. Reload the video to index keyframes.")


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
        "safe_start": None,
        "safe_end": None,
        "previous_keyframe_start": None,
        "next_keyframe_start": None,
        "previous_keyframe_end": None,
        "next_keyframe_end": None,
        "extra_before": 0.0,
        "extra_after": 0.0,
    }
