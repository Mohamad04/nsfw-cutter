import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from models.app_settings import AppSettings
from services.settings_service import SettingsService


class SettingsServiceTests(unittest.TestCase):
    def test_missing_settings_file_creates_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings = SettingsService(settings_path).load()

            self.assertTrue(settings_path.exists())
            self.assertEqual(settings.theme, "dark")
            self.assertEqual(settings.batch_size, 8)

    def test_invalid_settings_file_is_backed_up_and_replaced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            settings_path.write_text("{broken json", encoding="utf-8")

            settings = SettingsService(settings_path).load()

            self.assertEqual(settings.theme, "dark")
            self.assertTrue(settings_path.with_suffix(".invalid.json").exists())
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["version"], 1)

    def test_recent_videos_are_unique_and_limited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SettingsService(Path(temp_dir) / "settings.json")

            for index in range(12):
                service.save_last_video(Path(temp_dir) / f"video-{index}.mp4")
            service.save_last_video(Path(temp_dir) / "video-5.mp4")

            settings = service.load()

            self.assertEqual(len(settings.recent_videos), 10)
            self.assertEqual(settings.recent_videos[0], Path(temp_dir) / "video-5.mp4")
            self.assertEqual(len(set(settings.recent_videos)), 10)

    def test_settings_model_rejects_invalid_preferences(self):
        with self.assertRaises(ValidationError):
            AppSettings.model_validate({"theme": "blue", "batch_size": -5})


if __name__ == "__main__":
    unittest.main()
