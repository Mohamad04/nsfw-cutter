import tempfile
import unittest
from pathlib import Path

from services.video_discovery_service import VideoDiscoveryService


class VideoDiscoveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = VideoDiscoveryService()

    def test_valid_folder_returns_mp4_and_mkv_videos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            mp4 = folder / "sample.mp4"
            mkv = folder / "movie.mkv"
            mp4.touch()
            mkv.touch()

            videos = self.service.find_videos_in_folder(folder)

            self.assertEqual(videos, sorted([mp4.resolve(), mkv.resolve()], key=lambda path: path.name.lower()))

    def test_uppercase_extensions_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            mp4 = folder / "sample.MP4"
            mkv = folder / "movie.MKV"
            mp4.touch()
            mkv.touch()

            videos = self.service.find_videos_in_folder(folder)

            self.assertEqual(len(videos), 2)
            self.assertIn(mp4.resolve(), videos)
            self.assertIn(mkv.resolve(), videos)

    def test_unsupported_extensions_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "sample.mov").touch()

            self.assertEqual(self.service.find_videos_in_folder(folder), [])

    def test_missing_folder_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"

            with self.assertRaises(ValueError):
                self.service.find_videos_in_folder(missing)

    def test_file_path_as_folder_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "sample.mp4"
            file_path.touch()

            with self.assertRaises(ValueError):
                self.service.find_videos_in_folder(file_path)

    def test_videos_are_returned_sorted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            second = folder / "b.mkv"
            first = folder / "a.mp4"
            second.touch()
            first.touch()

            self.assertEqual(self.service.find_videos_in_folder(folder), [first.resolve(), second.resolve()])

    def test_validate_video_file_accepts_supported_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "sample.mp4"
            video.touch()

            self.assertEqual(self.service.validate_video_file(video), video.resolve())

    def test_validate_video_file_rejects_unsupported_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "sample.mov"
            video.touch()

            with self.assertRaises(ValueError):
                self.service.validate_video_file(video)

    def test_subtitle_discovery_finds_plain_srt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "video.mp4"
            subtitle = folder / "video.srt"
            video.touch()
            subtitle.touch()

            self.assertEqual(self.service.find_subtitle_for_video(video), subtitle.resolve())

    def test_subtitle_discovery_finds_language_srt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            video = folder / "video.mp4"
            subtitle = folder / "video.en.srt"
            video.touch()
            subtitle.touch()

            self.assertEqual(self.service.find_subtitle_for_video(video), subtitle.resolve())

    def test_subtitle_discovery_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "video.mp4"
            video.touch()

            self.assertIsNone(self.service.find_subtitle_for_video(video))


if __name__ == "__main__":
    unittest.main()
