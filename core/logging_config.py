import logging
from pathlib import Path

from core.paths import get_logs_dir


def configure_logging(log_path: str | Path | None = None) -> Path:
    resolved_log_path = Path(log_path) if log_path else get_logs_dir() / "video-cut.log"
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == resolved_log_path
        for handler in root_logger.handlers
    ):
        handler = logging.FileHandler(resolved_log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root_logger.addHandler(handler)

    return resolved_log_path
