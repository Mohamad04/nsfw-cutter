import sys
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir


APP_NAME = "NSFW Cutter"
APP_AUTHOR = "MohamadElHajj"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_AUTHOR)) / "settings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR)) / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_dir() -> Path:
    path = Path(user_cache_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_settings_path() -> Path:
    return get_config_dir() / "settings.json"


def get_database_path() -> Path:
    return get_data_dir() / "nsfw_app.db"


def get_json_data_dir() -> Path:
    path = get_data_dir() / "json"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_resource_path(relative_path: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return bundle_root / relative_path
