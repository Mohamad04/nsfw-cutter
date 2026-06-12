import tempfile
import unittest
from pathlib import Path

from services.subtitles.srt_preview_service import parse_srt_file
from services.subtitles.subtitle_loader_service import load_subtitle_events, subtitle_text_at_position


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

    def test_load_subtitle_events_can_load_simple_srt_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "movie.srt"
            subtitle.write_text(
                "1\n"
                "00:00:01,000 --> 00:00:02,500\n"
                "Loaded through pysubs2\n",
                encoding="utf-8",
            )

            cues = load_subtitle_events(subtitle)

        self.assertEqual(
            cues,
            [
                {
                    "start_ms": 1_000,
                    "end_ms": 2_500,
                    "text": "Loaded through pysubs2",
                }
            ],
        )

    def test_load_subtitle_events_can_load_ass_file_and_clean_tags(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            subtitle = Path(temp_dir) / "movie.ass"
            subtitle.write_text(
                "[Script Info]\n"
                "ScriptType: v4.00+\n"
                "\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
                "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
                "MarginR, MarginV, Encoding\n"
                "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
                "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1\n"
                "\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,"
                "{\\i1}Hello\\N<b>World</b>\n",
                encoding="utf-8",
            )

            cues = load_subtitle_events(subtitle)

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["start_ms"], 1_000)
        self.assertEqual(cues[0]["end_ms"], 3_000)
        self.assertEqual(cues[0]["text"], "Hello\nWorld")


if __name__ == "__main__":
    unittest.main()
