from pathlib import Path


class VideoDiscoveryService:
    VIDEO_EXTENSIONS = {".mp4", ".mkv"}

    def find_videos_in_folder(self, folder: str | Path) -> list[Path]:
        folder_path = Path(folder).expanduser()
        if not folder_path.exists():
            raise ValueError("Selected folder does not exist")
        if not folder_path.is_dir():
            raise ValueError("Selected path is not a folder")

        videos = [
            path.resolve()
            for path in folder_path.iterdir()
            if path.is_file() and path.suffix.lower() in self.VIDEO_EXTENSIONS
        ]
        return sorted(videos, key=lambda path: path.name.lower())

    def validate_video_file(self, file_path: str | Path) -> Path:
        video_path = Path(file_path).expanduser()
        if not video_path.exists():
            raise ValueError("Selected video file does not exist")
        if not video_path.is_file():
            raise ValueError("Selected path is not a video file")
        if video_path.suffix.lower() not in self.VIDEO_EXTENSIONS:
            raise ValueError("Unsupported video format. Use .mp4 or .mkv")
        return video_path.resolve()

    def find_subtitle_for_video(self, video_path: str | Path) -> Path | None:
        validated_video_path = Path(video_path).expanduser()
        candidates = sorted(validated_video_path.parent.glob(f"{validated_video_path.stem}*.srt"))
        return candidates[0].resolve() if candidates else None
