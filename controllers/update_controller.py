import logging
import threading

from PySide6.QtCore import Property, QCoreApplication, QObject, Signal, Slot

from services.infrastructure.update import (
    fetch_latest_release,
    is_frozen,
    is_newer,
    launch_installer,
)
from services.infrastructure.update.updater import current_version

logger = logging.getLogger(__name__)


class UpdateController(QObject):
    """Exposes app version and self-update actions to QML.

    The network check runs on a background thread; results are delivered to the
    QML/GUI thread through queued signal connections.
    """

    checkStarted = Signal()
    # available, latestVersion, releaseNotes, errorMessage
    checkFinished = Signal(bool, str, str, str)
    updateLaunched = Signal()
    updateFailed = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._checking = False
        self._latest_tag = ""

    @Property(str, constant=True)
    def currentVersion(self) -> str:
        return current_version()

    @Property(bool, constant=True)
    def canSelfUpdate(self) -> bool:
        """False when running from source — self-update needs the packaged app."""
        return is_frozen()

    @Slot()
    def checkForUpdates(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.checkStarted.emit()
        thread = threading.Thread(target=self._run_check, daemon=True)
        thread.start()

    def _run_check(self) -> None:
        try:
            release, error = fetch_latest_release()
            if error is not None or release is None:
                self.checkFinished.emit(False, "", "", error or "Unknown error")
                return

            self._latest_tag = release.tag
            available = is_newer(release)
            self.checkFinished.emit(
                available, release.version_str, release.release_notes, ""
            )
        except Exception as exc:  # noqa: BLE001 — never let the thread die silently
            logger.exception("Update check failed")
            self.checkFinished.emit(False, "", "", str(exc))
        finally:
            self._checking = False

    @Slot()
    def applyUpdate(self) -> None:
        ok, error = launch_installer()
        if not ok:
            self.updateFailed.emit(error or "Could not start the updater.")
            return

        self.updateLaunched.emit()
        # Quit so the installer can overwrite the locked application files.
        QCoreApplication.quit()
