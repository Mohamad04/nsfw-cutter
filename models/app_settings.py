from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Theme(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class Language(str, Enum):
    EN = "en"
    FR = "fr"


class AIProvider(str, Enum):
    LOCAL = "local"
    OPENAI = "openai"
    CUSTOM = "custom"


class AppSettings(BaseModel):
    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    version: int = 1

    theme: Theme = Theme.DARK
    language: Language = Language.EN
    window_width: int = Field(default=1280, ge=800, le=3840)
    window_height: int = Field(default=800, ge=600, le=2160)

    last_video_path: Path | None = None
    recent_videos: list[Path] = Field(default_factory=list)

    export_dir: Path | None = None
    default_export_format: str = "json"

    user_prompt: str = ""

    ai_provider: AIProvider = AIProvider.LOCAL
    ai_model_name: str = ""
    enable_gpu: bool = True
    batch_size: int = Field(default=8, ge=1, le=64)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("recent_videos")
    @classmethod
    def limit_recent_videos(cls, values: list[Path]) -> list[Path]:
        unique_paths = []
        for path in values:
            if path not in unique_paths:
                unique_paths.append(path)
        return unique_paths[:10]
