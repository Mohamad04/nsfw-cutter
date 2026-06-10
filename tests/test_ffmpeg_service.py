import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.infrastructure.ffmpeg import paths as ffmpeg_paths
from services.infrastructure.ffmpeg.probe import probe_media
from services.infrastructure.ffmpeg.runner import FFmpegNotFoundError


class FFmpegServiceTests(unittest.TestCase):
    def test_bundled_ffmpeg_path_detection(self):
        def fake_which(binary_name):
            self.fail(f"PATH fallback should not be used for {binary_name}")

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_root = Path(temp_dir)
            bundled_ffmpeg = bundle_root / "vendor" / "ffmpeg" / "bin" / "ffmpeg.exe"
            bundled_ffmpeg.parent.mkdir(parents=True)
            bundled_ffmpeg.touch()

            with patch("services.infrastructure.ffmpeg.paths._runtime_roots", return_value=(bundle_root,)):
                with patch("services.infrastructure.ffmpeg.paths.shutil.which", fake_which):
                    self.assertEqual(ffmpeg_paths.get_ffmpeg_path(), bundled_ffmpeg)

    def test_pyinstaller_onedir_runtime_path_detection(self):
        def fake_which(binary_name):
            self.fail(f"PATH fallback should not be used for {binary_name}")

        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            bundled_ffprobe = app_dir / "vendor" / "ffmpeg" / "bin" / "ffprobe.exe"
            bundled_ffprobe.parent.mkdir(parents=True)
            bundled_ffprobe.touch()

            with patch.object(ffmpeg_paths.sys, "frozen", True, create=True):
                with patch.object(ffmpeg_paths.sys, "executable", str(app_dir / "app.exe")):
                    with patch.object(ffmpeg_paths.sys, "_MEIPASS", str(app_dir / "_internal"), create=True):
                        with patch("services.infrastructure.ffmpeg.paths.PROJECT_ROOT", Path("missing")):
                            with patch("services.infrastructure.ffmpeg.paths.shutil.which", fake_which):
                                self.assertTrue(ffmpeg_paths.get_ffprobe_path().samefile(bundled_ffprobe))

    def test_path_fallback_uses_system_binary(self):
        system_ffmpeg = r"C:\ffmpeg\bin\ffmpeg.exe"

        def fake_which(binary_name):
            return system_ffmpeg if binary_name == "ffmpeg.exe" else None

        with patch("services.infrastructure.ffmpeg.paths._runtime_roots", return_value=(Path("missing"),)):
            with patch("services.infrastructure.ffmpeg.paths.shutil.which", fake_which):
                self.assertEqual(ffmpeg_paths.get_ffmpeg_path(), Path(system_ffmpeg))

    def test_missing_ffmpeg_has_clear_error(self):
        with patch("services.infrastructure.ffmpeg.paths._runtime_roots", return_value=(Path("missing"),)):
            with patch("services.infrastructure.ffmpeg.paths.shutil.which", return_value=None):
                with self.assertRaisesRegex(
                    FFmpegNotFoundError,
                    "vendor\\\\ffmpeg\\\\bin\\\\ffmpeg\\.exe|vendor/ffmpeg/bin/ffmpeg\\.exe",
                ):
                    ffmpeg_paths.get_ffmpeg_path()

    def test_probe_media_resolves_only_ffprobe(self):
        def fake_runner(command, **_kwargs):
            payload = {"format": {"duration": "12.5"}, "streams": []}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

        with patch(
            "services.infrastructure.ffmpeg.probe.get_ffprobe_path",
            return_value=Path("ffprobe"),
        ) as get_ffprobe_path:
            payload = probe_media("movie.mp4", probe_runner=fake_runner)

        get_ffprobe_path.assert_called_once_with()
        self.assertEqual(payload["format"]["duration"], "12.5")


if __name__ == "__main__":
    unittest.main()
