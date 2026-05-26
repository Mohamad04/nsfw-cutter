class RecentVideoSettings:
    def __init__(self, accessor):
        self._accessor = accessor

    def get_last_video_path(self) -> str:
        path = self._accessor.reload().last_video_path
        return str(path) if path else ""

    def get_recent_videos(self):
        return [str(path) for path in self._accessor.reload().recent_videos]

    def save_last_video(self, path: str):
        return self._accessor.save_last_video(path)
