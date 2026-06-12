import tempfile
import unittest
from pathlib import Path

from services.subtitles.discovery_service import find_matching_external_subtitles
from services.subtitles.inspection_service import get_embedded_subtitle_streams
from services.subtitles.processing_service import SubtitleService


class SubtitleDetectionTests(unittest.TestCase):
    def test_embedded_subrip_stream_is_text_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mkv"
            video.touch()

            candidates = get_embedded_subtitle_streams(
                video,
                subtitle_probe=lambda _path: [
                    {
                        "index": 3,
                        "codec_type": "subtitle",
                        "codec_name": "subrip",
                        "tags": {"language": "fra", "title": "French"},
                    }
                ],
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "embedded")
        self.assertEqual(candidates[0]["kind"], "text")
        self.assertTrue(candidates[0]["is_text_readable"])
        self.assertEqual(candidates[0]["stream_index"], 3)
        self.assertEqual(candidates[0]["codec_name"], "subrip")
        self.assertEqual(candidates[0]["language_code"], "fra")
        self.assertEqual(candidates[0]["language_name"], "French")

    def test_embedded_pgs_stream_is_detected_but_not_text_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mkv"
            video.touch()

            candidates = get_embedded_subtitle_streams(
                video,
                subtitle_probe=lambda _path: [
                    {
                        "index": 4,
                        "codec_type": "subtitle",
                        "codec_name": "hdmv_pgs_subtitle",
                        "tags": {"language": "eng"},
                    }
                ],
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["kind"], "image")
        self.assertFalse(candidates[0]["is_text_readable"])
        self.assertIn("Image-based subtitle", candidates[0]["note"])

    def test_no_embedded_subtitle_streams_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mp4"
            video.touch()

            candidates = get_embedded_subtitle_streams(video, subtitle_probe=lambda _path: [])

        self.assertEqual(candidates, [])

    def test_missing_embedded_language_tag_keeps_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "movie.mkv"
            video.touch()

            candidates = get_embedded_subtitle_streams(
                video,
                subtitle_probe=lambda _path: [
                    {
                        "index": 5,
                        "codec_type": "subtitle",
                        "codec_name": "subrip",
                        "tags": {},
                    }
                ],
            )

        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0]["language_code"])
        self.assertIsNone(candidates[0]["language_name"])

    def test_external_exact_base_match_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.mkv"
            subtitle = folder / "Movie.Name.2005.srt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "external")
        self.assertEqual(candidates[0]["kind"], "text")
        self.assertTrue(candidates[0]["is_text_readable"])
        self.assertEqual(candidates[0]["filename"], "Movie.Name.2005.srt")
        self.assertEqual(candidates[0]["match_type"], "exact")
        self.assertIsNone(candidates[0]["filename_suffix"])

    def test_external_iso_639_1_language_suffix_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "movie.mkv"
            subtitle = folder / "movie.en.srt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["filename"], "movie.en.srt")
        self.assertEqual(candidates[0]["language_code"], "en")
        self.assertEqual(candidates[0]["language_name"], "English")

    def test_external_ass_subtitle_is_text_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "movie.mkv"
            subtitle = folder / "movie.ass"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["format"], "ass")
        self.assertEqual(candidates[0]["kind"], "text")
        self.assertTrue(candidates[0]["is_text_readable"])

    def test_external_vtt_subtitle_is_text_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "movie.mkv"
            subtitle = folder / "movie.vtt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["format"], "vtt")
        self.assertEqual(candidates[0]["kind"], "text")
        self.assertTrue(candidates[0]["is_text_readable"])

    def test_external_complete_base_with_language_suffix_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.1080p.YIFY.mp4"
            subtitle = folder / "Movie.Name.2005.1080p.YIFY.fra.srt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["match_type"], "video_base_with_suffix")
        self.assertEqual(candidates[0]["filename_suffix"], "fra")
        self.assertEqual(candidates[0]["language_code"], "fra")
        self.assertEqual(candidates[0]["language_name"], "French")

    def test_external_flag_suffix_is_preserved_without_language_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.1080p.YIFY.mp4"
            subtitle = folder / "Movie.Name.2005.1080p.YIFY.forced.srt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["filename_suffix"], "forced")
        self.assertEqual(candidates[0]["label"], "forced")
        self.assertIsNone(candidates[0]["language_code"])
        self.assertIsNone(candidates[0]["language_name"])

    def test_external_unknown_suffix_keeps_candidate_without_language_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.1080p.YIFY.mp4"
            subtitle = folder / "Movie.Name.2005.1080p.YIFY.xx.srt"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["filename_suffix"], "xx")
        self.assertIsNone(candidates[0]["language_code"])
        self.assertIsNone(candidates[0]["language_name"])

    def test_external_matching_supports_accented_unicode_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            subtitle = folder / "Nume\u0301ro 9 (2009) MULTI VFF.ara.srt"
            video = folder / "Num\u00e9ro 9 (2009) MULTI VFF.mkv"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["filename_suffix"], "ara")
        self.assertEqual(candidates[0]["language_name"], "Arabic")

    def test_external_unrelated_subtitle_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.mkv"
            unrelated = folder / "Different.Movie.2005.fra.srt"
            video.touch()
            unrelated.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(candidates, [])

    def test_external_matching_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.MP4"
            subtitle = folder / "movie.name.2005.FRA.SRT"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["format"], "srt")
        self.assertEqual(candidates[0]["language_code"], "fra")

    def test_vobsub_idx_sub_pair_is_one_non_text_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.mkv"
            idx = folder / "Movie.Name.2005.fra.idx"
            sub = folder / "Movie.Name.2005.fra.sub"
            video.touch()
            idx.touch()
            sub.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["format"], "vobsub")
        self.assertEqual(candidates[0]["kind"], "image")
        self.assertFalse(candidates[0]["is_text_readable"])
        self.assertEqual(Path(candidates[0]["file_path"]).name, "Movie.Name.2005.fra.idx")
        self.assertEqual(Path(candidates[0]["companion_path"]).name, "Movie.Name.2005.fra.sub")

    def test_sub_without_idx_pair_is_microdvd_text_candidate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "Movie.Name.2005.mkv"
            subtitle = folder / "Movie.Name.2005.sub"
            video.touch()
            subtitle.touch()

            candidates = find_matching_external_subtitles(video)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["format"], "microdvd")
        self.assertEqual(candidates[0]["kind"], "text")
        self.assertTrue(candidates[0]["is_text_readable"])
        self.assertIn("requires video fps", candidates[0]["note"])

    def test_embedded_and_external_candidates_are_both_retained(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "movie.mkv"
            subtitle = folder / "movie.eng.srt"
            video.touch()
            subtitle.touch()
            service = SubtitleService(
                embedded_inspection=lambda _path: [
                    {
                        "source": "embedded",
                        "kind": "text",
                        "is_text_readable": True,
                        "stream_index": 2,
                    }
                ]
            )

            candidates = service.discover_subtitles(video)

        self.assertEqual(len(candidates), 2)
        self.assertEqual([candidate["source"] for candidate in candidates], ["embedded", "external"])


if __name__ == "__main__":
    unittest.main()
