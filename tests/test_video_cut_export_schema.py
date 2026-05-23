import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from schemas.video_cut_schema import VideoCutRequest, VideoCutSegment


class VideoCutExportSchemaTests(unittest.TestCase):
    def test_segment_rejects_invalid_range(self):
        with self.assertRaises(ValidationError):
            VideoCutSegment(index=1, start_seconds=20, end_seconds=10)

    def test_request_requires_existing_input_and_segments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "input.mp4"
            video_path.touch()

            with self.assertRaises(ValidationError):
                VideoCutRequest(input_path=video_path, output_dir=Path(temp_dir), segments=[])

            with self.assertRaises(ValidationError):
                VideoCutRequest(
                    input_path=Path(temp_dir) / "missing.mp4",
                    output_dir=Path(temp_dir),
                    segments=[VideoCutSegment(index=1, start_seconds=0, end_seconds=1)],
                )

    def test_legacy_merged_mode_exports_selected_clips_merged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "input.mp4"
            video_path.touch()

            request = VideoCutRequest(
                input_path=video_path,
                output_dir=Path(temp_dir),
                segments=[VideoCutSegment(index=1, start_seconds=1, end_seconds=2)],
                export_mode="merged",
            )

            self.assertEqual(request.export_mode, "export_clips_merged")


if __name__ == "__main__":
    unittest.main()
