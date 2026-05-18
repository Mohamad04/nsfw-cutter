import sys
from pathlib import Path

from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from controllers.app_controller import AppController
from database.init_db import init_database


def main():
    # Force a deterministic controls style to avoid platform hover artifacts.
    QQuickStyle.setStyle("Basic")
    init_database()
    app = QApplication(sys.argv)

    engine = QQmlApplicationEngine()

    controller = AppController()
    controller.setParent(app)
    engine.rootContext().setContextProperty("appController", controller)

    qml_file = Path(__file__).resolve().parent / "vue" / "qml" / "Main.qml"
    engine.load(str(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
