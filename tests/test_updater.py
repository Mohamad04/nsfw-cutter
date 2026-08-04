import json
import unittest
from unittest.mock import MagicMock, patch

from services.infrastructure.update import updater


class UpdateReleaseContractTests(unittest.TestCase):
    def _response(self, payload):
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode("utf-8")
        response.__enter__.return_value = response
        return response

    def test_fetch_latest_release_requires_exact_zip_and_checksum_assets(self):
        tag = "v1.3.0"
        zip_name = f"NSFW-Cutter-{tag}-windows.zip"
        payload = {
            "tag_name": tag,
            "name": "NSFW Cutter 1.3.0",
            "body": "Release notes",
            "assets": [
                {
                    "name": zip_name,
                    "browser_download_url": "https://example.test/app.zip",
                },
                {
                    "name": f"{zip_name}.sha256",
                    "browser_download_url": "https://example.test/app.zip.sha256",
                },
                {
                    "name": "unrelated.zip",
                    "browser_download_url": "https://example.test/unrelated.zip",
                },
            ],
        }

        with patch.object(updater, "urlopen", return_value=self._response(payload)):
            release, error = updater.fetch_latest_release()

        self.assertIsNone(error)
        self.assertIsNotNone(release)
        self.assertEqual(release.tag, tag)
        self.assertEqual(release.asset_name, zip_name)
        self.assertEqual(release.download_url, "https://example.test/app.zip")
        self.assertEqual(
            release.checksum_url, "https://example.test/app.zip.sha256"
        )

    def test_fetch_latest_release_rejects_missing_checksum_asset(self):
        tag = "v1.3.0"
        zip_name = f"NSFW-Cutter-{tag}-windows.zip"
        payload = {
            "tag_name": tag,
            "assets": [
                {
                    "name": zip_name,
                    "browser_download_url": "https://example.test/app.zip",
                }
            ],
        }

        with patch.object(updater, "urlopen", return_value=self._response(payload)):
            release, error = updater.fetch_latest_release()

        self.assertIsNone(release)
        self.assertIn(f"{zip_name}.sha256", error)

    def test_fetch_latest_release_rejects_malformed_tag(self):
        payload = {"tag_name": "latest", "assets": []}

        with patch.object(updater, "urlopen", return_value=self._response(payload)):
            release, error = updater.fetch_latest_release()

        self.assertIsNone(release)
        self.assertEqual(error, "Unsupported release tag: latest")

    def test_launch_installer_passes_tag_pid_and_executable(self):
        process = MagicMock()
        with (
            patch.object(updater, "is_frozen", return_value=True),
            patch.object(updater, "_resolve_powershell", return_value="powershell.exe"),
            patch.object(updater.subprocess, "Popen", return_value=process) as popen,
            patch.object(updater.sys, "executable", r"C:\Program Files\NSFW\VideoCutter.exe"),
            patch.object(updater.os, "getpid", return_value=4321),
        ):
            launched_process, error = updater.launch_installer("v1.3.0")

        self.assertIs(launched_process, process)
        self.assertIsNone(error)
        command = popen.call_args.args[0][-1]
        self.assertIn("/main/scripts/install.ps1", command)
        self.assertIn("-ExpectedTag 'v1.3.0'", command)
        self.assertIn("-WaitForProcessId 4321", command)
        self.assertIn("VideoCutter.exe'", command)

    def test_launch_installer_rejects_invalid_expected_tag(self):
        with patch.object(updater, "is_frozen", return_value=True):
            launched_process, error = updater.launch_installer("latest")

        self.assertIsNone(launched_process)
        self.assertEqual(error, "Invalid release tag: latest")


if __name__ == "__main__":
    unittest.main()
