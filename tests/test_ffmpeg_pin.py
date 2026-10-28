"""The bundled FFmpeg is pinned to one verified stable build (scripts/ffmpeg-pin.json)."""

import hashlib
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from services.infrastructure.ffmpeg import paths

ROOT = Path(__file__).resolve().parents[1]
PIN = json.loads((ROOT / "scripts" / "ffmpeg-pin.json").read_text(encoding="utf-8"))
VENDOR = ROOT / "vendor" / "ffmpeg"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class FFmpegPinTests(unittest.TestCase):
    def test_pin_describes_one_stable_build_with_both_executables(self):
        self.assertRegex(PIN["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(set(PIN["binaries"]), {"ffmpeg.exe", "ffprobe.exe"})
        for digest in PIN["binaries"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertIn("LICENSE", PIN["documents"])
        self.assertNotIn("latest", PIN["download_url"])

    def test_preparation_scripts_never_resolve_a_moving_latest_release(self):
        for script in ("prepare_ffmpeg.ps1",):
            text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            self.assertNotIn("releases/latest", text, script)
            self.assertNotIn("BtbN", text, script)

    def test_build_script_verifies_the_bundled_binaries_against_the_pin(self):
        text = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ffmpeg-pin.json", text)
        self.assertIn("is not the pinned FFmpeg", text)

    def test_project_local_ffmpeg_is_the_pinned_build_with_its_license(self):
        if not (VENDOR / "bin" / "ffmpeg.exe").is_file():
            self.skipTest("vendor/ffmpeg is not prepared (run scripts/prepare_ffmpeg.ps1)")
        for name, digest in PIN["binaries"].items():
            self.assertEqual(_sha256(VENDOR / "bin" / name), digest, f"{name} is not the pinned build")
        for document in PIN["documents"].values():
            self.assertEqual(_sha256(VENDOR / document["target"]), document["sha256"], document["target"])

    def test_fallback_to_an_ffmpeg_on_path_is_logged(self):
        with (
            patch.object(paths, "_runtime_roots", return_value=(ROOT / "missing-root",)),
            patch.object(paths.shutil, "which", return_value="C:/tools/ffmpeg.exe"),
            patch.object(paths, "_warned_system_binaries", set()),
            self.assertLogs(paths._logger.name, level="WARNING") as logs,
        ):
            self.assertEqual(paths.find_executable("ffmpeg"), Path("C:/tools/ffmpeg.exe"))
        self.assertIn("not the verified bundled FFmpeg build", logs.output[0])


if __name__ == "__main__":
    unittest.main()
