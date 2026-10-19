"""Translation catalogs cover the texts added by the export-settings, video-loading and D8/D9 fixes."""

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "vue" / "qml" / "WindowsApplication"
NEW_TEXTS = {
    "SettingsDialog": [
        "Export Clean Video removes every cut in the list and keeps the rest of the video.",
    ],
    "CleanShellPage": ["Checking %1…", "Dismiss"],
}
REMOVED_TEXTS = {"SettingsDialog": ["Remove intervals", "Export clips separately", "Export merged clips"]}


def _messages(language: str) -> dict[tuple[str, str], ET.Element]:
    root = ET.parse(ROOT / "resources" / "i18n" / f"app_{language}.ts").getroot()
    return {
        (context.findtext("name"), message.findtext("source")): message.find("translation")
        for context in root.iter("context")
        for message in context.iter("message")
    }


class TranslationCatalogTests(unittest.TestCase):
    def test_new_texts_are_used_by_the_qml(self):
        sources = {
            "SettingsDialog": (QML / "Settings" / "SettingsDialog.qml").read_text(encoding="utf-8"),
            "CleanShellPage": (QML / "AppShell" / "CleanShellPage.qml").read_text(encoding="utf-8"),
        }
        for context, texts in NEW_TEXTS.items():
            for text in texts:
                self.assertIn(f'qsTr("{text}")', sources[context])
        for context, texts in REMOVED_TEXTS.items():
            for text in texts:
                self.assertNotIn(f'qsTr("{text}")', sources[context])

    def test_new_texts_are_translated_in_french_and_arabic(self):
        for language in ("fr", "ar"):
            messages = _messages(language)
            for context, texts in NEW_TEXTS.items():
                for text in texts:
                    with self.subTest(language=language, text=text):
                        translation = messages.get((context, text))
                        self.assertIsNotNone(translation, "missing from the catalog")
                        self.assertIsNone(translation.get("type"), "must be a finished translation")
                        self.assertTrue((translation.text or "").strip())
                        self.assertNotEqual(translation.text, text)
                        self.assertEqual(re.findall(r"%\d", translation.text), re.findall(r"%\d", text))

    def test_removed_export_modes_are_marked_vanished(self):
        for language in ("fr", "ar"):
            messages = _messages(language)
            for context, texts in REMOVED_TEXTS.items():
                for text in texts:
                    with self.subTest(language=language, text=text):
                        self.assertEqual(messages[(context, text)].get("type"), "vanished")


if __name__ == "__main__":
    unittest.main()
