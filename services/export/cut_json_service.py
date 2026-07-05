import json
import math
from pathlib import Path

from core.time_utils import timecode_to_seconds


class CutJsonError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class CutJsonService:
    VERSION = 1

    INVALID_JSON = "invalid_json"
    INVALID_IMPORT = "invalid_import"
    INVALID_EXPORT = "invalid_export"
    NO_CUTS = "no_cuts"

    def export_to_path(
        self,
        cuts,
        file_path: str,
        *,
        video_filename: str,
        video_duration_seconds: float = 0.0,
    ) -> tuple[int, Path]:
        count, payload = self._export_payload(
            cuts,
            video_filename=video_filename,
            video_duration_seconds=video_duration_seconds,
        )

        output_path = Path(file_path)
        if output_path.suffix.lower() != ".json":
            output_path = output_path.with_suffix(".json")

        output_path.write_text(
            self._json_text(payload),
            encoding="utf-8",
        )
        return count, output_path

    def export_to_text(
        self,
        cuts,
        *,
        video_filename: str,
        video_duration_seconds: float = 0.0,
    ) -> str:
        _count, payload = self._export_payload(
            cuts,
            video_filename=video_filename,
            video_duration_seconds=video_duration_seconds,
        )
        return self._json_text(payload)

    def import_from_path(
        self,
        file_path: str,
        *,
        video_duration_seconds: float = 0.0,
    ) -> tuple[list[dict], Path]:
        input_path = Path(file_path)
        if not input_path.is_file():
            raise CutJsonError(self.INVALID_IMPORT, "Selected cuts JSON file does not exist")

        try:
            cuts = self.import_from_text(
                input_path.read_text(encoding="utf-8"),
                video_duration_seconds=video_duration_seconds,
            )
        except OSError as exc:
            raise CutJsonError(self.INVALID_IMPORT, str(exc)) from exc

        return cuts, input_path

    def import_from_text(
        self,
        json_text: str,
        *,
        video_duration_seconds: float = 0.0,
    ) -> list[dict]:
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise CutJsonError(self.INVALID_JSON, exc.msg) from exc

        if not isinstance(payload, dict):
            raise CutJsonError(self.INVALID_IMPORT, "Cuts JSON must be an object")

        raw_cuts = payload.get("cuts")
        if not isinstance(raw_cuts, list):
            raise CutJsonError(self.INVALID_IMPORT, "Cuts JSON must contain a cuts array")

        duration = self._effective_duration(video_duration_seconds, payload)
        intervals = self._merge_intervals(self._ranges_from_cuts(raw_cuts, duration))
        return [self._cut_for_qml(start, end) for start, end in intervals]

    def _export_payload(
        self,
        cuts,
        *,
        video_filename: str,
        video_duration_seconds: float = 0.0,
    ) -> tuple[int, dict]:
        intervals = self._ranges_from_cuts(cuts, video_duration_seconds)
        if not intervals:
            raise CutJsonError(self.NO_CUTS, "No cuts to export")

        payload = {
            "version": self.VERSION,
            "video": {
                "filename": video_filename,
                "duration": self._clean_seconds(video_duration_seconds),
            },
            "cuts": [
                {
                    "start": self._format_seconds(start),
                    "end": self._format_seconds(end),
                }
                for start, end in intervals
            ],
        }
        return len(intervals), payload

    def _json_text(self, payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _ranges_from_cuts(self, cuts, duration_seconds: float) -> list[tuple[float, float]]:
        intervals = []
        for cut in cuts or []:
            if not isinstance(cut, dict):
                raise CutJsonError(self.INVALID_IMPORT, "Each cut must be an object")

            start = self._cut_seconds(
                cut,
                "start",
                "requested_start_seconds",
                "requestedStartSeconds",
                "start_seconds",
                "startSeconds",
            )
            end = self._cut_seconds(
                cut,
                "end",
                "requested_end_seconds",
                "requestedEndSeconds",
                "end_seconds",
                "endSeconds",
            )
            self._validate_range(start, end, duration_seconds)
            intervals.append((start, end))

        intervals.sort(key=lambda interval: (interval[0], interval[1]))
        return intervals

    def _cut_seconds(self, cut: dict, primary_key: str, *fallback_keys: str) -> float:
        missing = object()
        value = cut.get(primary_key, missing)
        if value is missing or value in (None, ""):
            for key in fallback_keys:
                value = cut.get(key, missing)
                if value is not missing and value not in (None, ""):
                    break

        if value is missing or value in (None, ""):
            raise CutJsonError(self.INVALID_IMPORT, "Each cut must contain start and end")

        return self._seconds_value(value)

    def _seconds_value(self, value) -> float:
        if isinstance(value, bool):
            raise CutJsonError(self.INVALID_IMPORT, "Cut times must be numbers")

        if isinstance(value, (int, float)):
            seconds = float(value)
        else:
            text = str(value).strip()
            if ":" not in text:
                raise CutJsonError(self.INVALID_IMPORT, "Cut times must be numbers")
            try:
                seconds = timecode_to_seconds(text)
            except ValueError as exc:
                raise CutJsonError(self.INVALID_IMPORT, "Cut times must be numbers") from exc

        if not math.isfinite(seconds):
            raise CutJsonError(self.INVALID_IMPORT, "Cut times must be finite numbers")
        return round(seconds, 3)

    def _validate_range(self, start: float, end: float, duration_seconds: float) -> None:
        if start < 0:
            raise CutJsonError(self.INVALID_IMPORT, "Cut start must be greater than or equal to zero")
        if end <= start:
            raise CutJsonError(self.INVALID_IMPORT, "Cut end must be after start")
        if duration_seconds > 0 and end > duration_seconds:
            raise CutJsonError(self.INVALID_IMPORT, "Cut end must be within the loaded video duration")

    def _merge_intervals(self, intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if not intervals:
            return []

        merged = [intervals[0]]
        for start, end in intervals[1:]:
            previous_start, previous_end = merged[-1]
            if start <= previous_end:
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))
        return merged

    def _cut_for_qml(self, start: float, end: float) -> dict:
        return {
            "start": self._format_seconds(start),
            "end": self._format_seconds(end),
            "requestedStartSeconds": start,
            "requestedEndSeconds": end,
        }

    def _effective_duration(self, duration_seconds: float, payload: dict) -> float:
        current_duration = self._clean_seconds(duration_seconds)
        if current_duration > 0:
            return current_duration

        video = payload.get("video")
        if not isinstance(video, dict):
            return 0.0

        return self._clean_seconds(video.get("duration", 0.0))

    def _clean_seconds(self, value) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(seconds) or seconds < 0:
            return 0.0
        return round(seconds, 3)

    def _format_seconds(self, seconds: float) -> str:
        total_milliseconds = int(round(max(0.0, seconds) * 1000))
        total_seconds, milliseconds = divmod(total_milliseconds, 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, whole_seconds = divmod(remainder, 60)
        text = f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        if milliseconds:
            text += f".{milliseconds:03d}"
        return text
