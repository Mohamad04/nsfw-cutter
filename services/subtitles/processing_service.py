import logging
from pathlib import Path

from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams


logger = logging.getLogger(__name__)


class SubtitleService:
    def __init__(
        self,
        external_discovery=None,
        embedded_inspection=None,
    ):
        self.external_discovery = external_discovery or find_matching_external_subtitles
        self.embedded_inspection = embedded_inspection or get_embedded_subtitle_streams

    def discover_subtitles(self, video_path: str | Path) -> list[dict]:
        embedded, embedded_error = self._discover_source("embedded", self.embedded_inspection, video_path)
        external, external_error = self._discover_source("external", self.external_discovery, video_path)
        candidates = [*embedded, *external]
        errors = [error for error in (embedded_error, external_error) if error]
        if not candidates and errors:
            raise RuntimeError("; ".join(errors))
        return candidates

    def find_subtitle_for_video(self, video_path: str | Path) -> Path | None:
        for candidate in self.external_discovery(video_path):
            if candidate.get("is_text_readable") and candidate.get("file_path"):
                return Path(candidate["file_path"]).resolve()
        return None

    def _discover_source(self, source_name: str, discovery, video_path: str | Path) -> tuple[list[dict], str]:
        try:
            candidates = discovery(video_path)
        except Exception as exc:
            logger.exception(
                "[Subtitles] %s subtitle discovery failed for %s",
                source_name.capitalize(),
                video_path,
            )
            return [], f"{source_name.capitalize()} subtitle discovery failed: {exc}"

        return candidates if isinstance(candidates, list) else [], ""
