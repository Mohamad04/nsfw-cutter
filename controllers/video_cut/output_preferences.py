import logging
from pathlib import Path

from pydantic import ValidationError


logger = logging.getLogger(__name__)


class OutputPreferences:
    def __init__(self, settings_service):
        self._settings_service = settings_service

    def resolve_output_dir(self, input_file: Path, output_dir: str) -> Path:
        if output_dir and str(output_dir).strip():
            return Path(output_dir)

        settings = self._settings_service.load()
        if settings.default_export_dir or settings.export_dir:
            return settings.default_export_dir or settings.export_dir
        return input_file.parent / "cuts"

    def remember(self, output_dir: Path, export_mode: str) -> None:
        try:
            self._settings_service.update(
                default_export_dir=output_dir,
                export_dir=output_dir,
                last_export_mode=export_mode,
            )
        except (OSError, ValidationError):
            logger.exception("Unable to persist video export settings")
