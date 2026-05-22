import json
import re
from pathlib import Path

from core.time_utils import utc_now_iso


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_filename_part(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", str(value).strip())
    return cleaned.strip("._") or "item"


def write_json_artifact(data: dict, folder: str | Path, prefix: str, stem: str) -> str:
    target_folder = Path(folder)
    target_folder.mkdir(parents=True, exist_ok=True)

    timestamp = utc_now_iso().replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
    filename = f"{_safe_filename_part(prefix)}_{timestamp}_{_safe_filename_part(stem)}.json"
    output_path = target_folder / filename

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)
