class SettingsAccessor:
    def __init__(self, service):
        self._service = service
        self._settings = self._service.load()

    @property
    def service(self):
        return self._service

    @property
    def settings(self):
        return self._settings

    def reload(self):
        self._settings = self._service.load()
        return self._settings

    def update(self, **changes):
        self._settings = self._service.update(**changes)
        return self._settings

    def save_last_video(self, path: str):
        self._settings = self._service.save_last_video(path)
        return self._settings
