from pydantic import ValidationError
from PySide6.QtCore import QObject, Property, Signal, Slot

from controllers.settings.ai_settings import AISettings
from controllers.settings.appearance_settings import AppearanceSettings
from controllers.settings.export_settings import ExportSettings
from controllers.settings.recent_video_settings import RecentVideoSettings
from controllers.settings.settings_accessor import SettingsAccessor
from services.settings_service import SettingsService


class SettingsController(QObject):
    settingsChanged = Signal()
    themeChanged = Signal()

    def __init__(self, settings_service: SettingsService | None = None):
        super().__init__()
        self._service = settings_service or SettingsService()
        self._accessor = SettingsAccessor(self._service)
        self._settings = self._accessor.settings
        self._appearance = AppearanceSettings(self._accessor)
        self._ai = AISettings(self._accessor)
        self._export = ExportSettings(self._accessor)
        self._recent_videos = RecentVideoSettings(self._accessor)

    @Property(str, notify=themeChanged)
    def theme(self) -> str:
        return self._appearance.get_theme()

    @Slot(result=str)
    def getTheme(self) -> str:
        return self.theme

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        self._update_from(self._appearance.set_theme, theme, theme_changed=True)

    @Slot(result=str)
    def getLanguage(self) -> str:
        return self._appearance.get_language()

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        self._update_from(self._appearance.set_language, language)

    @Slot(result=str)
    def getUserPrompt(self) -> str:
        return self._ai.get_user_prompt()

    @Slot(str)
    def setUserPrompt(self, prompt: str) -> None:
        self._update_from(self._ai.set_user_prompt, prompt)

    @Slot(result=str)
    def getAIProvider(self) -> str:
        return self._ai.get_provider()

    @Slot(str)
    def setAIProvider(self, provider: str) -> None:
        self._update_from(self._ai.set_provider, provider)

    @Slot(result=str)
    def getAIModelName(self) -> str:
        return self._ai.get_model_name()

    @Slot(str)
    def setAIModelName(self, model_name: str) -> None:
        self._update_from(self._ai.set_model_name, model_name)

    @Slot(result=int)
    def getBatchSize(self) -> int:
        return self._ai.get_batch_size()

    @Slot(int)
    def setBatchSize(self, batch_size: int) -> None:
        self._update_from(self._ai.set_batch_size, batch_size)

    @Slot(result=bool)
    def getEnableGpu(self) -> bool:
        return self._ai.get_enable_gpu()

    @Slot(bool)
    def setEnableGpu(self, enabled: bool) -> None:
        self._update_from(self._ai.set_enable_gpu, enabled)

    @Slot(result=float)
    def getConfidenceThreshold(self) -> float:
        return self._ai.get_confidence_threshold()

    @Slot(float)
    def setConfidenceThreshold(self, value: float) -> None:
        self._update_from(self._ai.set_confidence_threshold, value)

    @Slot(result=str)
    def getExportDir(self) -> str:
        return self._export.get_export_dir()

    @Slot(str)
    def setExportDir(self, export_dir: str) -> None:
        self._update_from(self._export.set_export_dir, export_dir)

    @Slot(result=str)
    def chooseExportDir(self) -> str:
        return self._export.choose_export_dir()

    @Slot(result=str)
    def getLastExportMode(self) -> str:
        return self._export.get_last_export_mode()

    @Slot(str)
    def setLastExportMode(self, export_mode: str) -> None:
        self._update_from(self._export.set_last_export_mode, export_mode)

    @Slot(result=str)
    def getLastVideoPath(self) -> str:
        return self._recent_videos.get_last_video_path()

    @Slot(result="QVariantList")
    def getRecentVideos(self):
        return self._recent_videos.get_recent_videos()

    @Slot(str)
    def saveLastVideo(self, path: str) -> None:
        if not path:
            return
        self._settings = self._recent_videos.save_last_video(path)
        self.settingsChanged.emit()

    @Slot(result=str)
    def getSettingsJsonPath(self) -> str:
        return str(self._service.settings_path)

    def _reload(self):
        self._settings = self._accessor.reload()
        return self._settings

    def _update(self, *, theme_changed: bool = False, **changes) -> None:
        try:
            self._settings = self._accessor.update(**changes)
        except ValidationError:
            self._reload()
            return

        if theme_changed:
            self.themeChanged.emit()
        self.settingsChanged.emit()

    def _update_from(self, updater, *args, theme_changed: bool = False) -> None:
        try:
            self._settings = updater(*args)
        except ValidationError:
            self._reload()
            return

        if theme_changed:
            self.themeChanged.emit()
        self.settingsChanged.emit()
