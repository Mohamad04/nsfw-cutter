from pathlib import Path

from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams


class SubtitleService:
    def __init__(
        self,
        external_discovery=None,
        embedded_inspection=None,
    ):
        self.external_discovery = external_discovery or find_matching_external_subtitles
        self.embedded_inspection = embedded_inspection or get_embedded_subtitle_streams

    def discover_subtitles(self, video_path: str | Path) -> list[dict]:
        embedded = self.embedded_inspection(video_path)
        external = self.external_discovery(video_path)
        return [*embedded, *external]

    def find_subtitle_for_video(self, video_path: str | Path) -> Path | None:
        for candidate in self.external_discovery(video_path):
            if candidate.get("is_text_readable") and candidate.get("file_path"):
                return Path(candidate["file_path"]).resolve()
        return None
