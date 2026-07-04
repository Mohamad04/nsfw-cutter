from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QObject, Property, Signal, Slot
from PySide6.QtCore import QTranslator


class TranslationService(QObject):
    languageChanged = Signal()
    availableLanguagesChanged = Signal()

    def __init__(self, engine, translation_dir: str | Path, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._translation_dir = Path(translation_dir)
        self._translator: QTranslator | None = None
        self._default_language = "en"
        self._current_language = self._default_language
        self._file_prefix = "app_"
        self._language_name_overrides = {
            "en": "English",
        }
        self._available_languages = self._discover_languages()

    @Property(str, notify=languageChanged)
    def currentLanguage(self) -> str:
        return self._current_language

    @Property("QVariantList", notify=availableLanguagesChanged)
    def availableLanguages(self) -> list:
        return self._available_languages

    @Slot(str, result=bool)
    def setLanguage(self, language_code: str) -> bool:
        language_code = (language_code or self._default_language).strip()
        if not language_code:
            language_code = self._default_language

        if language_code == self._current_language:
            return True

        app = QCoreApplication.instance()

        if app is None:
            return False

        if language_code == self._default_language:
            self._remove_current_translator(app)
            self._current_language = self._default_language
            self._notify_language_changed()
            return True

        qm_path = self._qm_path_for_language(language_code)
        if qm_path is None:
            return False

        new_translator = QTranslator()
        if not new_translator.load(str(qm_path)):
            return False
        self._remove_current_translator(app)
        app.installTranslator(new_translator)
        self._translator = new_translator
        self._current_language = language_code

        self._notify_language_changed()

        return True

    @Slot(str, result=bool)
    def SetLanguage(self, language_code: str) -> bool:
        return self.setLanguage(language_code)

    @Slot()
    def refreshAvailableLanguages(self) -> None:
        self._available_languages = self._discover_languages()
        self.availableLanguagesChanged.emit()

    def _discover_languages(self) -> list[dict]:
        languages = [
            {
                "code": self._default_language,
                "name": self._language_name(self._default_language),
            }
        ]

        if not self._translation_dir.exists():
            return languages

        qm_files = sorted(self._translation_dir.glob(f"{self._file_prefix}*.qm"))

        for qm_file in qm_files:
            language_code = qm_file.stem.removeprefix(self._file_prefix)
            if not language_code:
                continue
            if language_code == self._default_language:
                continue
            languages.append({
                "code": language_code,
                "name": self._language_name(language_code),
            })

        return languages

    def _qm_path_for_language(self, language_code: str) -> Path | None:
        qm_path = self._translation_dir / f"{self._file_prefix}{language_code}.qm"
        if not qm_path.exists():
            return None
        return qm_path

    def _remove_current_translator(self, app: QCoreApplication) -> None:
        if self._translator is not None:
            app.removeTranslator(self._translator)
            self._translator = None

    def _notify_language_changed(self) -> None:
        self.languageChanged.emit()
        self._engine.retranslate()

    def _language_name(self, language_code: str) -> str:
        if language_code in self._language_name_overrides:
            return self._language_name_overrides[language_code]

        locale = QLocale(language_code)
        native_name = locale.nativeLanguageName()

        if native_name:
            return native_name[0].upper() + native_name[1:]
        return language_code

