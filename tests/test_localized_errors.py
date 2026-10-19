"""User-visible errors are shown in the interface language; the log keeps the English technical details.

The tracked catalogs are compiled with pyside6-lrelease and installed as the application does
(TranslationService installs a QTranslator on the QCoreApplication). Real controller, workers and
bundled FFmpeg on synthetic media.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QTranslator

from evaluation import export_frame_accuracy as efa
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path
from services.media.media_validation import MediaValidationError, validate_media_file
from services.user_errors import describe_error, technical_details
from services.user_messages import TEMPLATES, english, localized_text
# The module, not its TestCase class, so its tests are not collected a second time here.
from tests import test_user_errors

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "fr": {
        "damaged": "est endommagé ou incomplet et ne peut pas être ouvert",
        "output": "Le dossier de sortie ne peut pas être utilisé : « cues.srt » est un fichier existant",
        "keyframes": "La coupe rapide ne peut pas supprimer exactement les intervalles sélectionnés",
        "nearest": "images clés les plus proches",
        "audio": "La coupe rapide ne peut pas supprimer l'audio exactement",
    },
    "ar": {
        "damaged": "تالف أو غير مكتمل ولا يمكن فتحه",
        "output": "لا يمكن استخدام مجلد الإخراج: «cues.srt» ملف موجود وليس مجلدًا",
        "keyframes": "لا يستطيع القص السريع إزالة الفواصل المحددة بدقة",
        "nearest": "أقرب إطارات مفتاحية",
        "audio": "لا يستطيع القص السريع إزالة الصوت بدقة",
    },
}


class LocalizedErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lrelease = Path(sys.executable).parent / "pyside6-lrelease.exe"
        if not lrelease.is_file():
            raise unittest.SkipTest("pyside6-lrelease is not available")
        try:
            cls.ffmpeg = get_ffmpeg_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.root = Path(tempfile.mkdtemp(prefix="localized-errors-"))
        for language in EXPECTED:
            completed = subprocess.run(
                [str(lrelease), str(ROOT / "resources" / "i18n" / f"app_{language}.ts"),
                 "-qm", str(cls.root / f"app_{language}.qm")],
                capture_output=True, text=True, timeout=60, check=False,
            )
            assert completed.returncode == 0, completed.stderr
        cls._timeout_patch = patch("subprocess.run", test_user_errors._run_with_timeout)
        cls._timeout_patch.start()
        # Video only, keyframe every second (Fast Cutting refuses other boundaries), and the same with audio.
        cls.valid = cls.root / "valid.mp4"
        completed = subprocess.run(
            [str(cls.ffmpeg), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=6",
             "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", str(cls.valid)],
            capture_output=True, text=True, timeout=test_user_errors.SUBPROCESS_TIMEOUT_SECONDS, check=False,
        )
        assert completed.returncode == 0, completed.stderr
        cls.with_audio = efa.generate_fixture(cls.ffmpeg, efa.FIXTURES["h264_aac_mp4"], cls.root)
        cls.not_a_video = cls.root / "not_a_video.mp4"
        cls.not_a_video.write_text("plain text, not a video\n" * 50)

    @classmethod
    def tearDownClass(cls):
        cls._timeout_patch.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root))
        self.integration = test_user_errors.ExportErrorIntegrationTests()
        self.integration.work = self.work

    def install(self, language):
        translator = QTranslator()
        self.assertTrue(translator.load(str(self.root / f"app_{language}.qm")))
        QCoreApplication.installTranslator(translator)
        self.addCleanup(QCoreApplication.removeTranslator, translator)
        return translator

    def export(self, source, output_dir, timing_mode, start="00:00:02", end="00:00:03"):
        controller = self.integration.controller()
        segment = {"start": start, "end": end}
        if timing_mode:
            segment["timing_mode"] = timing_mode
        controller.exportSegments(str(source), [segment], str(output_dir), "remove_intervals")
        return controller

    def test_damaged_video_is_reported_in_the_interface_language_and_logged_in_english(self):
        for language, expected in EXPECTED.items():
            with self.subTest(language=language):
                self.install(language)
                with self.assertRaises(MediaValidationError) as caught:
                    validate_media_file(self.not_a_video)
                self.assertIn(expected["damaged"], localized_text(caught.exception))
                self.assertIn(expected["damaged"], describe_error(caught.exception).message)
                self.assertIn("not_a_video.mp4", localized_text(caught.exception))
                # The exception text and the technical details stay in English.
                self.assertIn("is damaged or incomplete", str(caught.exception))
                self.assertIn("is damaged or incomplete", technical_details(caught.exception))

    def test_invalid_output_location_is_translated_for_fast_and_smart(self):
        not_a_folder = self.work / "cues.srt"
        not_a_folder.write_text("1")
        for language, expected in EXPECTED.items():
            for timing_mode in ("requested", None):
                with self.subTest(language=language, timing_mode=timing_mode):
                    self.install(language)
                    controller = self.export(self.valid, not_a_folder, timing_mode)
                    self.assertEqual(controller.cutStatus, "Video export failed")
                    self.assertIn(expected["output"], controller.cutError)

    def test_refused_fast_export_is_translated_with_its_keyframe_details(self):
        for language, expected in EXPECTED.items():
            with self.subTest(language=language):
                self.install(language)
                with self.assertLogs("workers.video_cut_worker", level="ERROR") as logs:
                    controller = self.export(self.valid, self.work / f"out-{language}", "requested",
                                             start="00:00:02.500", end="00:00:03.200")
                self.assertIn(expected["keyframes"], controller.cutError)
                self.assertIn(expected["nearest"], controller.cutError)
                self.assertIn("00:00:02.500", controller.cutError)
                self.assertNotIn("Fast Cutting cannot", controller.cutError)
                self.assertIn("Fast Cutting cannot remove the selected intervals exactly", "\n".join(logs.output))
                self.assertFalse(any((self.work / f"out-{language}").glob("*")))

    def test_fast_export_of_a_source_with_audio_is_refused_in_the_interface_language(self):
        for language, expected in EXPECTED.items():
            with self.subTest(language=language):
                self.install(language)
                with self.assertLogs("workers.video_cut_worker", level="ERROR"):
                    controller = self.export(self.with_audio, self.work / f"audio-{language}", "requested")
                self.assertIn(expected["audio"], controller.cutError)

    def test_without_a_catalog_the_messages_are_the_english_ones(self):
        with self.assertRaises(MediaValidationError) as caught:
            validate_media_file(self.not_a_video)
        self.assertEqual(localized_text(caught.exception), english("media.damaged", name="not_a_video.mp4"))
        self.assertEqual(localized_text(caught.exception), str(caught.exception))


class CatalogCoverageTests(unittest.TestCase):
    def test_every_coded_message_is_translated_with_the_same_placeholders(self):
        import re
        import xml.etree.ElementTree as ET

        for language in ("fr", "ar"):
            root = ET.parse(ROOT / "resources" / "i18n" / f"app_{language}.ts").getroot()
            catalog = {
                message.findtext("source"): message.find("translation")
                for context in root.iter("context") if context.findtext("name") == "UserMessages"
                for message in context.iter("message")
            }
            for code, template in TEMPLATES.items():
                with self.subTest(language=language, code=code):
                    translation = catalog.get(template)
                    self.assertIsNotNone(translation, "missing from the catalog")
                    self.assertIsNone(translation.get("type"), "must be a finished translation")
                    self.assertNotEqual(translation.text, template)
                    self.assertEqual(sorted(re.findall(r"\{\w+\}", translation.text)),
                                     sorted(re.findall(r"\{\w+\}", template)))
                    if language == "ar" and not template.startswith("{time}"):
                        # Qt takes the paragraph direction from the first strong character: a message
                        # starting with a file name or "FFmpeg" would be laid out left-to-right.
                        import unicodedata

                        text = re.sub(r"\{\w+\}", "movie.mp4", translation.text)  # file names are Latin
                        first = next(char for char in text if unicodedata.bidirectional(char) in ("L", "R", "AL"))
                        self.assertIn(unicodedata.bidirectional(first), ("R", "AL"), translation.text)


if __name__ == "__main__":
    unittest.main()
