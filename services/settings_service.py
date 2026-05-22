import json
from pathlib import Path

from pydantic import ValidationError

from core.paths import get_settings_path
from models.app_settings import AppSettings


class SettingsService:
    def __init__(self, settings_path: str | Path | None = None):
        self.settings_path = Path(settings_path) if settings_path else get_settings_path()

    def load(self) -> AppSettings:
        if not self.settings_path.exists():
            settings = AppSettings()
            self.save(settings)
            return settings

        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return AppSettings.model_validate(payload)
        except (json.JSONDecodeError, OSError, ValidationError, TypeError, ValueError):
            self._backup_invalid_settings()
            settings = AppSettings()
            self.save(settings)
            return settings

    def save(self, settings: AppSettings) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        payload = settings.model_dump(mode="json")
        self.settings_path.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_last_video(self, video_path: str | Path) -> AppSettings:
        settings = self.load()
        path = Path(video_path)
        settings.last_video_path = path

        recent = [recent_path for recent_path in settings.recent_videos if recent_path != path]
        recent.insert(0, path)
        settings.recent_videos = recent[:10]

        self.save(settings)
        return settings

    def get_last_video(self) -> Path | None:
        settings = self.load()
        if settings.last_video_path and settings.last_video_path.is_file():
            return settings.last_video_path
        return None

    def update(self, **kwargs) -> AppSettings:
        settings = self.load()
        updated_data = settings.model_dump()
        updated_data.update(kwargs)
        updated_settings = AppSettings.model_validate(updated_data)
        self.save(updated_settings)
        return updated_settings

    def _backup_invalid_settings(self) -> None:
        backup_path = self.settings_path.with_suffix(".invalid.json")
        try:
            self.settings_path.replace(backup_path)
        except OSError:
            pass
