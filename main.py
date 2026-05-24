import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from controllers.app_controller import AppController
from controllers.settings_controller import SettingsController
from controllers.video_cut_controller import VideoCutController
from core.logging_config import configure_logging
from core.paths import APP_AUTHOR, APP_NAME, get_resource_path
from database.init_db import init_database
from services.settings_service import SettingsService


WINDOWS_APP_USER_MODEL_ID = "com.nsfwcutter.desktop"


def set_windows_app_user_model_id() -> None:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )


def main():
    # Force a deterministic controls style to avoid platform hover artifacts.
    QQuickStyle.setStyle("Basic")
    set_windows_app_user_model_id()
    configure_logging()
    init_database()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_AUTHOR)
    app_icon = QIcon(str(get_resource_path("assets/icons/app.ico")))
    app.setWindowIcon(app_icon)

    engine = QQmlApplicationEngine()

    settings_service = SettingsService()
    controller = AppController(settings_service=settings_service)
    controller.setParent(app)
    engine.rootContext().setContextProperty("appController", controller)

    settings_controller = SettingsController(settings_service=settings_service)
    settings_controller.setParent(app)
    engine.rootContext().setContextProperty("settingsController", settings_controller)

    video_cut_controller = VideoCutController(settings_service=settings_service)
    video_cut_controller.setParent(app)
    engine.rootContext().setContextProperty("videoCutController", video_cut_controller)

    controller.restoreLastVideo()

    qml_file = get_resource_path("vue/qml/Main.qml")
    engine.load(str(qml_file))

    root_objects = engine.rootObjects()
    if not root_objects:
        sys.exit(-1)

    for root_object in root_objects:
        set_icon = getattr(root_object, "setIcon", None)
        if callable(set_icon):
            set_icon(app_icon)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
