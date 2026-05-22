import sys

from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from controllers.app_controller import AppController
from controllers.settings_controller import SettingsController
from core.paths import get_resource_path
from database.init_db import init_database
from services.settings_service import SettingsService


def main():
    # Force a deterministic controls style to avoid platform hover artifacts.
    QQuickStyle.setStyle("Basic")
    init_database()
    app = QApplication(sys.argv)

    engine = QQmlApplicationEngine()

    settings_service = SettingsService()
    controller = AppController(settings_service=settings_service)
    controller.setParent(app)
    engine.rootContext().setContextProperty("appController", controller)

    settings_controller = SettingsController(settings_service=settings_service)
    settings_controller.setParent(app)
    engine.rootContext().setContextProperty("settingsController", settings_controller)

    controller.restoreLastVideo()

    qml_file = get_resource_path("vue/qml/Main.qml")
    engine.load(str(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
