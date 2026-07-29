import ctypes
import sys

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox

from controllers.app_controller import AppController
from controllers.settings_controller import SettingsController
from controllers.update_controller import UpdateController
from controllers.video_cut_controller import VideoCutController
from core.logging_config import configure_logging
from core.paths import APP_AUTHOR, APP_NAME, get_resource_path
from database.init_db import init_database
from services.editing.keyframe_service import KeyframeService
from services.i18n import TranslationService
from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_ffprobe_path,
)
from services.settings_service import SettingsService


WINDOWS_APP_USER_MODEL_ID = "com.nsfwcutter.desktop"
WINDOWS_UI_FONT_FILES = (
    "segoeui.ttf",
    "segoeuib.ttf",
    "segoeuii.ttf",
    "segoeuiz.ttf",
    "segoeuil.ttf",
    "seguili.ttf",
    "segoeuisl.ttf",
    "seguisli.ttf",
    "seguisb.ttf",
    "seguisbi.ttf",
    "seguibl.ttf",
    "seguibli.ttf",
)


def set_windows_app_user_model_id() -> None:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )


def load_windows_ui_font_family() -> str:
    if sys.platform != "win32":
        return "Segoe UI"

    loaded_family = ""
    for font_file in WINDOWS_UI_FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(f"C:/Windows/Fonts/{font_file}")
        if font_id < 0:
            continue
        if not loaded_family:
            font_families = QFontDatabase.applicationFontFamilies(font_id)
            if font_families:
                loaded_family = font_families[0]

    return loaded_family or "Segoe UI"


def check_ffmpeg_available() -> str:
    """Return an error message if ffmpeg/ffprobe cannot be located, else ""."""
    try:
        get_ffmpeg_path()
        get_ffprobe_path()
    except FFmpegNotFoundError as error:
        return str(error)
    return ""


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
    ui_font_family = load_windows_ui_font_family()
    app.setFont(QFont(ui_font_family, 9))
    app_icon = QIcon(str(get_resource_path("assets/icons/app.ico")))
    app.setWindowIcon(app_icon)

    ffmpeg_error = check_ffmpeg_available()
    if ffmpeg_error:
        QMessageBox.critical(
            None,
            f"{APP_NAME} — FFmpeg not found",
            f"{ffmpeg_error}\n\n"
            "The application cannot start without FFmpeg.\n"
            "Install it with this one command in PowerShell:\n\n"
            "irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/"
            "master/scripts/install_ffmpeg.ps1 | iex",
        )
        sys.exit(1)

    engine = QQmlApplicationEngine()

    settings_service = SettingsService()
    translation_service = TranslationService(
        engine,
        get_resource_path("resources/i18n"),
        parent=app,
    )
    engine.rootContext().setContextProperty("translationService", translation_service)

    keyframe_service = KeyframeService()
    controller = AppController(
        settings_service=settings_service,
        keyframe_service=keyframe_service,
    )
    controller.setParent(app)
    engine.rootContext().setContextProperty("appController", controller)

    settings_controller = SettingsController(
        settings_service=settings_service,
        translation_service=translation_service,
    )
    settings_controller.setParent(app)
    engine.rootContext().setContextProperty("settingsController", settings_controller)
    translation_service.setLanguage(settings_controller.getLanguage())

    video_cut_controller = VideoCutController(
        settings_service=settings_service,
        keyframe_service=keyframe_service,
    )
    video_cut_controller.setParent(app)
    engine.rootContext().setContextProperty("videoCutController", video_cut_controller)

    update_controller = UpdateController()
    update_controller.setParent(app)
    engine.rootContext().setContextProperty("updateController", update_controller)

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
