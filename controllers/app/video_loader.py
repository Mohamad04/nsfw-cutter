class VideoLoader:
    def __init__(self, video_import_service, settings_service):
        self._video_import_service = video_import_service
        self._settings_service = settings_service

    def list_folder_videos(self, folder: str) -> list[dict]:
        return self._video_import_service.list_importable_videos(folder)

    def import_video_file(self, file_path: str) -> dict:
        return self._video_import_service.import_video_file(file_path)

    def get_last_video(self):
        return self._settings_service.get_last_video()

    def save_last_video(self, path: str) -> None:
        self._settings_service.save_last_video(path)
