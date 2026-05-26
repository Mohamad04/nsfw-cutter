from pathlib import Path

from PySide6.QtWidgets import QFileDialog


class ExportSettings:
    def __init__(self, accessor):
        self._accessor = accessor

    def get_export_dir(self) -> str:
        settings = self._accessor.reload()
        export_dir = settings.default_export_dir or settings.export_dir
        return str(export_dir) if export_dir else ""

    def set_export_dir(self, export_dir: str):
        path = Path(export_dir) if export_dir.strip() else None
        return self._accessor.update(default_export_dir=path, export_dir=path)

    def choose_export_dir(self) -> str:
        folder = QFileDialog.getExistingDirectory(None, "Select export folder", self.get_export_dir())
        return folder or ""

    def get_last_export_mode(self) -> str:
        return self._accessor.reload().last_export_mode

    def set_last_export_mode(self, export_mode: str):
        return self._accessor.update(last_export_mode=export_mode)
