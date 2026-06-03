import tempfile
import unittest
from pathlib import Path

from services.subtitles.srt_preview_service import parse_srt_file, subtitle_text_at_position


class SrtPreviewServiceTests(unittest.TestCase):
    def test_parse_srt_file_and_find_active_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "movie.en.srt"
            subtitle.write_text(
                "\ufeff1\n"
                "00:00:48,840 --> 00:00:51,301\n"
                "<i>Rachel</i>, let me see.\n"
                "\n"
                "2\n"
                "00:00:57,390 --> 00:01:00,518\n"
                "- Can I see?\n"
                "- Finders keepers.\n",
                encoding="utf-8",
            )

            cues = parse_srt_file(subtitle)

        self.assertEqual(len(cues), 2)
        self.assertEqual(subtitle_text_at_position(cues, 48_840), "Rachel, let me see.")
        self.assertEqual(
            subtitle_text_at_position(cues, 58_000),
            "- Can I see?\n- Finders keepers.",
        )
        self.assertEqual(subtitle_text_at_position(cues, 52_000), "")

    def test_parse_arabic_srt_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "movie.ar.srt"
            subtitle.write_text(
                "1\n"
                "00:00:33,820 --> 00:00:36,030\n"
                "بداية الرّجل الوطوّاط\n",
                encoding="utf-8",
            )

            cues = parse_srt_file(subtitle)

        self.assertEqual(subtitle_text_at_position(cues, 34_000), "بداية الرّجل الوطوّاط")


if __name__ == "__main__":
    unittest.main()
