from pathlib import Path

from services.video_discovery_service import VideoDiscoveryService


class SubtitleService:
    def __init__(self, video_discovery_service: VideoDiscoveryService | None = None):
        self.video_discovery_service = video_discovery_service or VideoDiscoveryService()

    def find_subtitle_for_video(self, video_path: str | Path) -> Path | None:
        return self.video_discovery_service.find_subtitle_for_video(video_path)
