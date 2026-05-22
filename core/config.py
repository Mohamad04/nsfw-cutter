from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
JSON_DATA_DIR = DATA_DIR / "json"
DATABASE_PATH = DATA_DIR / "nsfw_app.db"

METADATA_JSON_DIR = JSON_DATA_DIR / "metadata"
SUBTITLES_JSON_DIR = JSON_DATA_DIR / "subtitles"
EXPORT_JOBS_JSON_DIR = JSON_DATA_DIR / "export_jobs"

LOCAL_FFPROBE_PATH = PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
