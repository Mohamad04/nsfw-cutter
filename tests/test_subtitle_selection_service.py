import tempfile
import unittest
from pathlib import Path

from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams
from services.subtitles.selection_service import (
    OFF_SUBTITLE_OPTION_ID,
    analysis_subtitle_status_text,
    attach_candidate_ids,
    attach_player_subtitle_track_indexes,
    auto_select_analysis_subtitle_id,
    build_analysis_subtitle_options,
    preview_subtitle_track_index_for_selection,
)


class SubtitleSelectionServiceTests(unittest.TestCase):
    def test_external_french_candidate_label_uses_language_not_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Batman.Knight.2005.1080p.BRRip.x264.YIFY.mp4"
            subtitle = folder / "Batman.Knight.2005.1080p.BRRip.x264.YIFY.fra.srt"
            video.touch()
            subtitle.touch()

            candidates = attach_candidate_ids(str(video), find_matching_external_subtitles(video))
            options = build_analysis_subtitle_options(candidates)

        self.assertEqual(options[0]["label"], "French")
        self.assertNotIn("Batman.Knight", options[0]["label"])
        self.assertNotIn(".srt", options[0]["label"])

    def test_external_arabic_candidate_label_uses_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "movie.mp4"
            subtitle = folder / "movie.ara.srt"
            video.touch()
            subtitle.touch()

            candidates = attach_candidate_ids(str(video), find_matching_external_subtitles(video))
            options = build_analysis_subtitle_options(candidates)

        self.assertEqual(options[0]["label"], "Arabic")

    def test_embedded_english_candidate_label_uses_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mkv"
            video.touch()
            candidates = get_embedded_subtitle_streams(
                video,
                subtitle_probe=lambda _path: [
                    {
                        "index": 2,
                        "codec_type": "subtitle",
                        "codec_name": "subrip",
                        "tags": {"language": "eng"},
                    }
                ],
            )
            options = build_analysis_subtitle_options(attach_candidate_ids(str(video), candidates))

        self.assertEqual(options[0]["label"], "English")

    def test_unknown_language_label_is_generic(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "codec_name": "subrip",
                    "language_name": None,
                    "is_text_readable": True,
                }
            ],
        )

        options = build_analysis_subtitle_options(candidates)

        self.assertEqual(options[0]["label"], "Unknown language")

    def test_duplicate_embedded_and_external_languages_are_disambiguated(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "codec_name": "subrip",
                    "language_name": "English",
                    "is_text_readable": True,
                },
                {
                    "source": "external",
                    "file_path": "movie.eng.srt",
                    "language_name": "English",
                    "is_text_readable": True,
                },
            ],
        )

        options = build_analysis_subtitle_options(candidates)

        self.assertEqual([option["label"] for option in options], ["English · Embedded", "English · External"])

    def test_duplicate_embedded_languages_get_indexes(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "codec_name": "subrip",
                    "language_name": "English",
                    "is_text_readable": True,
                },
                {
                    "source": "embedded",
                    "stream_index": 3,
                    "codec_name": "ass",
                    "language_name": "English",
                    "is_text_readable": True,
                },
            ],
        )

        options = build_analysis_subtitle_options(candidates)

        self.assertEqual([option["label"] for option in options], ["English · Embedded 1", "English · Embedded 2"])

    def test_exactly_one_text_readable_candidate_is_auto_selected(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "codec_name": "subrip",
                    "language_name": "French",
                    "is_text_readable": True,
                }
            ],
        )

        selected_id = auto_select_analysis_subtitle_id(candidates)

        self.assertEqual(selected_id, candidates[0]["candidate_id"])
        self.assertEqual(
            analysis_subtitle_status_text(candidates, selected_id, auto_selected=True),
            "Analysis subtitle: French · Auto-selected",
        )

    def test_multiple_text_readable_candidates_require_selection(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {"source": "embedded", "stream_index": 2, "language_name": "French", "is_text_readable": True},
                {"source": "embedded", "stream_index": 3, "language_name": "English", "is_text_readable": True},
            ],
        )

        self.assertIsNone(auto_select_analysis_subtitle_id(candidates))
        self.assertEqual(
            analysis_subtitle_status_text(candidates, None),
            "Analysis subtitle: Select one · 2 available",
        )

    def test_unreadable_candidate_is_visible_but_disabled(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "language_name": "English",
                    "kind": "image",
                    "is_text_readable": False,
                }
            ],
        )

        options = build_analysis_subtitle_options(candidates)

        self.assertFalse(options[0]["enabled"])
        self.assertEqual(options[0]["capabilityLabel"], "Image subtitle · unavailable for analysis")
        self.assertEqual(
            analysis_subtitle_status_text(candidates, None),
            "Subtitles found · None text-readable",
        )

    def test_off_option_can_be_added_to_selector_options(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 2,
                    "language_name": "French",
                    "is_text_readable": True,
                }
            ],
        )

        options = build_analysis_subtitle_options(
            candidates,
            OFF_SUBTITLE_OPTION_ID,
            include_off=True,
        )

        self.assertEqual(options[0]["id"], OFF_SUBTITLE_OPTION_ID)
        self.assertEqual(options[0]["label"], "Off")
        self.assertTrue(options[0]["selected"])

    def test_player_track_index_mapping_does_not_use_ffprobe_stream_index(self):
        candidates = attach_candidate_ids(
            "movie.mkv",
            [
                {
                    "source": "embedded",
                    "stream_index": 3,
                    "codec_name": "subrip",
                    "language_name": "French",
                    "is_text_readable": True,
                }
            ],
        )
        mapped = attach_player_subtitle_track_indexes(candidates, 1)

        self.assertEqual(mapped[0]["stream_index"], 3)
        self.assertEqual(mapped[0]["player_subtitle_track_index"], 0)
        self.assertEqual(
            preview_subtitle_track_index_for_selection(mapped, mapped[0]["candidate_id"]),
            0,
        )

    def test_external_selection_has_no_preview_track_index(self):
        candidates = attach_player_subtitle_track_indexes(
            attach_candidate_ids(
                "movie.mkv",
                [
                    {
                        "source": "external",
                        "file_path": "movie.fra.srt",
                        "language_name": "French",
                        "is_text_readable": True,
                    }
                ],
            ),
            2,
        )

        self.assertIsNone(candidates[0]["player_subtitle_track_index"])
        self.assertEqual(
            preview_subtitle_track_index_for_selection(candidates, candidates[0]["candidate_id"]),
            -1,
        )


if __name__ == "__main__":
    unittest.main()
