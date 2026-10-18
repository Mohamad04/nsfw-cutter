import logging
from pathlib import Path

from pydantic import ValidationError


logger = logging.getLogger(__name__)


class OutputPreferences:
    def __init__(self, settings_service):
        self._settings_service = settings_service

    def resolve_output_dir(self, input_file: Path, output_dir: str) -> Path:
        if output_dir and str(output_dir).strip():
            resolved = Path(output_dir)
        else:
            settings = self._settings_service.load()
            resolved = Path(settings.default_export_dir or settings.export_dir or input_file.parent / "cuts")
        _require_usable_output_dir(resolved)
        return resolved

    def remember(self, output_dir: Path, export_mode: str) -> None:
        try:
            self._settings_service.update(
                default_export_dir=output_dir,
                export_dir=output_dir,
                last_export_mode=export_mode,
            )
        except (OSError, ValidationError):
            logger.exception("Unable to persist video export settings")


def _require_usable_output_dir(output_dir: Path) -> None:
    """Refuse, before any FFmpeg command, an output folder that is an existing file or lies under one."""
    for candidate in (output_dir, *output_dir.parents):
        if candidate.exists():
            if not candidate.is_dir():
                raise ValueError(
                    f"The output folder cannot be used: \"{candidate.name}\" is an existing file, not a folder. "
                    "Choose another output folder."
                )
            return
