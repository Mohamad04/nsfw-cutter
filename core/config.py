from core.paths import get_database_path, get_json_data_dir, get_resource_path


DATA_DIR = get_database_path().parent
JSON_DATA_DIR = get_json_data_dir()
DATABASE_PATH = get_database_path()

METADATA_JSON_DIR = JSON_DATA_DIR / "metadata"
SUBTITLES_JSON_DIR = JSON_DATA_DIR / "subtitles"
EXPORT_JOBS_JSON_DIR = JSON_DATA_DIR / "export_jobs"

LOCAL_FFPROBE_PATH = get_resource_path("tools/ffmpeg/bin/ffprobe.exe")
