class AppearanceSettings:
    def __init__(self, accessor):
        self._accessor = accessor

    def get_theme(self) -> str:
        return str(self._accessor.settings.theme)

    def set_theme(self, theme: str):
        return self._accessor.update(theme=theme)

    def get_language(self) -> str:
        return str(self._accessor.reload().language)

    def set_language(self, language: str):
        return self._accessor.update(language=language)
