import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from services.infrastructure.ffmpeg.probe import probe_media
from services.infrastructure.ffmpeg.runner import FFmpegService


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

        with patch("services.infrastructure.ffmpeg.runner.get_resource_path", fake_resource_path):
            with patch("services.infrastructure.ffmpeg.runner.shutil.which", fake_which):
                with patch("services.infrastructure.ffmpeg.runner.sys.platform", "win32"):
                    service = FFmpegService(ffmpeg_path="ffmpeg", ffprobe_path=None)

        self.assertEqual(service.ffprobe_path, Path(r"C:\userenv\ffprobe.exe"))

    def test_probe_media_resolves_only_ffprobe(self):
        def fake_runner(command, **_kwargs):
            payload = {"format": {"duration": "12.5"}, "streams": []}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with patch(
            "services.infrastructure.ffmpeg.probe.resolve_binary",
            return_value=Path("ffprobe"),
        ) as resolve_binary:
            payload = probe_media("movie.mp4", probe_runner=fake_runner)

        resolve_binary.assert_called_once_with("ffprobe")
        self.assertEqual(payload["format"]["duration"], "12.5")


if __name__ == "__main__":
    unittest.main()
