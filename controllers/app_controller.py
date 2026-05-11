from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl
from PySide6.QtWidgets import QFileDialog


class AppController(QObject):
    videoUrlChanged = Signal()
    videoNameChanged = Signal()
    subtitleStatusChanged = Signal()
    projectStatusChanged = Signal()

    def __init__(self):
        super().__init__()
        self._video_url = ""
        self._video_name = "No video selected"
        self._subtitle_status = "Subtitle: not detected"
        self._project_status = "Ready"

    @Property(str, notify=videoUrlChanged)
    def videoUrl(self):
        return self._video_url

    @Property(str, notify=videoNameChanged)
    def videoName(self):
        return self._video_name

    @Property(str, notify=subtitleStatusChanged)
    def subtitleStatus(self):
        return self._subtitle_status

    @Property(str, notify=projectStatusChanged)
    def projectStatus(self):
        return self._project_status

    @Slot()
    def browseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, "Select video folder")

        if not folder:
            return

        folder_path = Path(folder)

        video_files = []
        for ext in ("*.mp4", "*.mkv", "*.avi", "*.mov"):
            video_files.extend(folder_path.glob(ext))

        if not video_files:
            self._project_status = "No video found in selected folder"
            self.projectStatusChanged.emit()
            return

        video_path = video_files[0]

        self._video_url = QUrl.fromLocalFile(str(video_path)).toString()
        self._video_name = video_path.name

        subtitle = self._find_subtitle(video_path)

        if subtitle:
            self._subtitle_status = f"Subtitle found: {subtitle.name}"
        else:
            self._subtitle_status = "Subtitle: not detected"

        self._project_status = "Video loaded"

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.subtitleStatusChanged.emit()
        self.projectStatusChanged.emit()

    @Slot()
    def clearVideo(self):
        self._video_url = ""
        self._video_name = "No video selected"
        self._subtitle_status = "Subtitle: not detected"
        self._project_status = "Ready"

        self.videoUrlChanged.emit()
        self.videoNameChanged.emit()
        self.subtitleStatusChanged.emit()
        self.projectStatusChanged.emit()

    def _find_subtitle(self, video_path: Path):
        """
        Convention examples:
        sample_video.fr.srt
        sample_video.en.srt
        sample_video.srt
        """
        folder = video_path.parent
        stem = video_path.stem

        candidates = list(folder.glob(f"{stem}*.srt"))

        if candidates:
            return candidates[0]

        return None