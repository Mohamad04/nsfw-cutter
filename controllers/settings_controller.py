from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from services.settings_service import SettingsService


class SettingsController(QObject):
    settingsChanged = Signal()
    themeChanged = Signal()

    def __init__(self, settings_service: SettingsService | None = None):
        super().__init__()
        self._service = settings_service or SettingsService()
        self._settings = self._service.load()

    @Property(str, notify=themeChanged)
    def theme(self) -> str:
        return str(self._settings.theme)

    @Slot(result=str)
    def getTheme(self) -> str:
        return self.theme

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        self._update(theme=theme, theme_changed=True)

    @Slot(result=str)
    def getLanguage(self) -> str:
        return str(self._reload().language)

    @Slot(str)
    def setLanguage(self, language: str) -> None:
        self._update(language=language)

    @Slot(result=str)
    def getUserPrompt(self) -> str:
        return self._reload().user_prompt

    @Slot(str)
    def setUserPrompt(self, prompt: str) -> None:
        self._update(user_prompt=prompt)

    @Slot(result=str)
    def getAIProvider(self) -> str:
        return str(self._reload().ai_provider)

    @Slot(str)
    def setAIProvider(self, provider: str) -> None:
        self._update(ai_provider=provider)

    @Slot(result=str)
    def getAIModelName(self) -> str:
        return self._reload().ai_model_name

    @Slot(str)
    def setAIModelName(self, model_name: str) -> None:
        self._update(ai_model_name=model_name)

    @Slot(result=int)
    def getBatchSize(self) -> int:
        return self._reload().batch_size

    @Slot(int)
    def setBatchSize(self, batch_size: int) -> None:
        self._update(batch_size=batch_size)

    @Slot(result=bool)
    def getEnableGpu(self) -> bool:
        return self._reload().enable_gpu

    @Slot(bool)
    def setEnableGpu(self, enabled: bool) -> None:
        self._update(enable_gpu=enabled)

    @Slot(result=float)
    def getConfidenceThreshold(self) -> float:
        return self._reload().confidence_threshold

    @Slot(float)
    def setConfidenceThreshold(self, value: float) -> None:
        self._update(confidence_threshold=value)

    @Slot(result=str)
    def getExportDir(self) -> str:
        settings = self._reload()
        export_dir = settings.default_export_dir or settings.export_dir
        return str(export_dir) if export_dir else ""

    @Slot(str)
    def setExportDir(self, export_dir: str) -> None:
        path = Path(export_dir) if export_dir.strip() else None
        self._update(default_export_dir=path, export_dir=path)

    @Slot(result=str)
    def chooseExportDir(self) -> str:
        folder = QFileDialog.getExistingDirectory(None, "Select export folder", self.getExportDir())
        return folder or ""

    @Slot(result=str)
    def getLastExportMode(self) -> str:
        return self._reload().last_export_mode

    @Slot(str)
    def setLastExportMode(self, export_mode: str) -> None:
        self._update(last_export_mode=export_mode)

    @Slot(result=str)
    def getLastVideoPath(self) -> str:
        path = self._reload().last_video_path
        return str(path) if path else ""

    @Slot(result="QVariantList")
    def getRecentVideos(self):
        return [str(path) for path in self._reload().recent_videos]

    @Slot(str)
    def saveLastVideo(self, path: str) -> None:
        if not path:
            return
        self._settings = self._service.save_last_video(path)
        self.settingsChanged.emit()

    @Slot(result=str)
    def getSettingsJsonPath(self) -> str:
        return str(self._service.settings_path)

    def _reload(self):
        self._settings = self._service.load()
        return self._settings

    def _update(self, *, theme_changed: bool = False, **changes) -> None:
        try:
            self._settings = self._service.update(**changes)
        except ValidationError:
            self._reload()
            return

        if theme_changed:
            self.themeChanged.emit()
        self.settingsChanged.emit()
