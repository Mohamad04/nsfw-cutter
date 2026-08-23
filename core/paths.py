import os
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


def get_cuts_cache_dir() -> Path:
    path = get_cache_dir() / "cuts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_analysis_cache_dir() -> Path:
    """Return the per-user cache for VLM analysis records and intermediates."""
    path = get_cache_dir() / "vlm-analysis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_model_cache_dir() -> Path:
    """Return the configurable, per-user model cache outside the application."""
    configured_path = os.environ.get("NSFW_CUTTER_MODEL_CACHE", "").strip()
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if not candidate.is_absolute():
            raise ValueError("NSFW_CUTTER_MODEL_CACHE must be an absolute path")
        path = candidate.resolve()
        forbidden_roots = {PROJECT_ROOT.resolve()}
        bundle_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)).resolve()
        forbidden_roots.add(bundle_root)
        if getattr(sys, "frozen", False):
            forbidden_roots.add(Path(sys.executable).resolve().parent)
        if any(path == root or path.is_relative_to(root) for root in forbidden_roots):
            raise ValueError(
                "NSFW_CUTTER_MODEL_CACHE must be outside the application directory"
            )
    else:
        path = get_cache_dir() / "models"
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


def get_logs_dir() -> Path:
    path = get_data_dir().parent / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_resource_path(relative_path: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return bundle_root / relative_path
