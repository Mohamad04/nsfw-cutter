import unittest
from pathlib import Path
from unittest.mock import patch

from services.ffmpeg_service import FFmpegService


class FFmpegServiceTests(unittest.TestCase):
    def test_windows_resolution_prefers_exe_over_command_wrapper(self):
        def fake_resource_path(relative_path):
            return Path("missing") / relative_path

        def fake_which(binary_name):
            paths = {
                "ffprobe": r"D:\Projet STAGE NSFW\NSFW\.venv\Scripts\ffprobe.CMD",
                "ffprobe.exe": r"C:\userenv\ffprobe.exe",
            }
            return paths.get(binary_name)

        with patch("services.ffmpeg_service.get_resource_path", fake_resource_path):
            with patch("services.ffmpeg_service.shutil.which", fake_which):
                with patch("services.ffmpeg_service.sys.platform", "win32"):
                    service = FFmpegService(ffmpeg_path="ffmpeg", ffprobe_path=None)

        self.assertEqual(service.ffprobe_path, Path(r"C:\userenv\ffprobe.exe"))


if __name__ == "__main__":
    unittest.main()
