import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from controllers.app_controller import AppController


def main():
    app = QGuiApplication(sys.argv)

    engine = QQmlApplicationEngine()

    controller = AppController()
    engine.rootContext().setContextProperty("appController", controller)

    qml_file = Path(__file__).resolve().parent / "frontend" / "qml" / "Main.qml"
    engine.load(str(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()