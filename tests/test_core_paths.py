import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import paths


class CorePathTests(unittest.TestCase):
    def test_user_data_override_isolates_smoke_test_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with patch.dict(
                os.environ, {paths.USER_DATA_ROOT_ENV: str(root)}, clear=False
            ):
                self.assertEqual(paths.get_config_dir(), root / "settings")
                self.assertEqual(paths.get_data_dir(), root / "data")
                self.assertEqual(paths.get_cache_dir(), root / "Cache")
                self.assertEqual(paths.get_logs_dir(), root / "logs")


if __name__ == "__main__":
    unittest.main()
