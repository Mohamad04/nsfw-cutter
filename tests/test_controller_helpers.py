import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from controllers.app.cut_normalizer import normalize_cut
from controllers.video_cut.output_preferences import OutputPreferences
from controllers.video_cut.result_formatter import duration_text, format_cut_details
from controllers.video_cut.segment_mapper import segment_seconds, segment_to_payload


class CutNormalizerTests(unittest.TestCase):
    def test_valid_cut_with_start_and_end_gets_defaults(self):
        cut = normalize_cut({"start": "00:00:01", "end": "00:00:02"})

        self.assertEqual(cut["start"], "00:00:01")
        self.assertEqual(cut["end"], "00:00:02")
        self.assertEqual(cut["reason"], "Manual cut")
        self.assertEqual(cut["tags"], "manual")

    def test_invalid_cut_where_end_is_before_start_raises(self):
        with self.assertRaisesRegex(ValueError, "start before end"):
            normalize_cut({"start": "00:00:02", "end": "00:00:01"})

    def test_invalid_time_format_raises(self):
        with self.assertRaisesRegex(ValueError, "HH:MM:SS"):
            normalize_cut({"start": "1", "end": "00:00:02"})

    def test_keyframe_fields_with_snake_case_are_preserved_as_qml_names(self):
        cut = normalize_cut(
            {
                "start": "00:00:10",
                "end": "00:00:20",
                "safe_start": "00:00:09",
                "safe_end": "00:00:21",
                "previous_keyframe_start": "00:00:08",
                "next_keyframe_end": "00:00:22",
                "extra_before": "1.0s",
                "extra_after": "2.0s",
            }
        )

        self.assertEqual(cut["safeStart"], "00:00:09")
        self.assertEqual(cut["safeEnd"], "00:00:21")
        self.assertEqual(cut["previousKeyframeStart"], "00:00:08")
        self.assertEqual(cut["nextKeyframeEnd"], "00:00:22")
        self.assertEqual(cut["extraBefore"], "1.0s")
        self.assertEqual(cut["extraAfter"], "2.0s")

    def test_keyframe_fields_with_camel_case_are_preserved(self):
        cut = normalize_cut(
            {
                "start": "00:00:10",
                "end": "00:00:20",
                "safeStart": "00:00:09",
                "safeEnd": "00:00:21",
                "previousKeyframeEnd": "00:00:18",
                "nextKeyframeStart": "00:00:11",
            }
        )

        self.assertEqual(cut["safeStart"], "00:00:09")
        self.assertEqual(cut["safeEnd"], "00:00:21")
        self.assertEqual(cut["previousKeyframeEnd"], "00:00:18")
        self.assertEqual(cut["nextKeyframeStart"], "00:00:11")

    def test_requested_and_safe_seconds_are_preserved(self):
        cut = normalize_cut(
            {
                "start": "00:00:10",
                "end": "00:00:20",
                "safeStart": "00:00:09",
                "safeEnd": "00:00:21",
                "requested_start_seconds": 10.25,
                "requested_end_seconds": 20.5,
                "safe_start_seconds": 9.0,
                "safe_end_seconds": 21.0,
            }
        )

        self.assertEqual(cut["requestedStartSeconds"], 10.25)
        self.assertEqual(cut["requestedEndSeconds"], 20.5)
        self.assertEqual(cut["safeStartSeconds"], 9.0)
        self.assertEqual(cut["safeEndSeconds"], 21.0)


class SegmentMapperTests(unittest.TestCase):
    def test_segment_with_start_and_end_requires_safe_bounds(self):
        with self.assertRaisesRegex(ValueError, "Safe cut start is unavailable"):
            segment_to_payload(1, {"start": "00:00:01", "end": "00:00:03"})

    def test_segment_with_start_end_and_safe_bounds(self):
        payload = segment_to_payload(
            1,
            {
                "start": "00:00:01",
                "end": "00:00:03",
                "safeStart": "00:00:00",
                "safeEnd": "00:00:05",
            },
        )

        self.assertEqual(payload["requested_start_seconds"], 1)
        self.assertEqual(payload["requested_end_seconds"], 3)
        self.assertEqual(payload["start_seconds"], 0)
        self.assertEqual(payload["end_seconds"], 5)

    def test_segment_with_safe_start_and_safe_end(self):
        payload = segment_to_payload(
            1,
            {
                "start": "00:00:01",
                "end": "00:00:03",
                "safeStart": "00:00:00",
                "safeEnd": "00:00:04",
            },
        )

        self.assertEqual(payload["start_seconds"], 0)
        self.assertEqual(payload["end_seconds"], 4)

    def test_segment_can_export_requested_timing_mode(self):
        payload = segment_to_payload(
            1,
            {
                "start": "00:00:01",
                "end": "00:00:03",
                "requestedStartSeconds": 1.0,
                "requestedEndSeconds": 3.0,
                "safeStart": "00:00:00",
                "safeEnd": "00:00:04",
                "timingMode": "requested",
            },
        )

        self.assertEqual(payload["start_seconds"], 1.0)
        self.assertEqual(payload["end_seconds"], 3.0)

    def test_fast_segment_with_numeric_seconds_uses_requested_bounds(self):
        payload = segment_to_payload(
            2,
            {
                "requested_start_seconds": 1.5,
                "requested_end_seconds": 3.5,
                "start_seconds": 1.0,
                "end_seconds": 4.0,
                "timingMode": "requested",
            },
        )

        self.assertEqual(payload["index"], 2)
        self.assertEqual(payload["requested_start_seconds"], 1.5)
        self.assertEqual(payload["start_seconds"], 1.5)
        self.assertEqual(payload["end_seconds"], 3.5)

    def test_smart_segment_rejects_raw_seconds_without_safe_bounds(self):
        with self.assertRaisesRegex(ValueError, "Safe cut start is unavailable"):
            segment_to_payload(
                2,
                {
                    "requested_start_seconds": 1.5,
                    "requested_end_seconds": 3.5,
                    "start_seconds": 1.0,
                    "end_seconds": 4.0,
                },
            )

    def test_invalid_segment_type_raises(self):
        with self.assertRaisesRegex(ValueError, "object"):
            segment_to_payload(1, "bad")

    def test_requested_vs_safe_seconds_priority(self):
        payload = segment_to_payload(
            1,
            {
                "requestedStartSeconds": 10.0,
                "requestedEndSeconds": 20.0,
                "safe_start_seconds": 9.0,
                "safe_end_seconds": 22.0,
            },
        )

        self.assertEqual(payload["requested_start_seconds"], 10.0)
        self.assertEqual(payload["requested_end_seconds"], 20.0)
        self.assertEqual(payload["start_seconds"], 9.0)
        self.assertEqual(payload["end_seconds"], 22.0)

    def test_segment_seconds_parses_first_available_key(self):
        self.assertEqual(segment_seconds({"a": "", "b": "00:00:05"}, "a", "b"), 5)


class ResultFormatterTests(unittest.TestCase):
    def test_empty_result_payload(self):
        self.assertEqual(format_cut_details({}), "")

    def test_result_with_output_paths_and_commands(self):
        details = format_cut_details(
            {
                "export_mode": "export_clips_merged",
                "cut_mode": "safe",
                "segments": [{"index": 1}],
                "output_paths": ["out.mp4"],
                "input_duration_seconds": 60,
                "expected_output_duration_seconds": 10,
                "actual_output_duration_seconds": 10.1,
                "duration_difference_seconds": 0.1,
                "ffmpeg_commands": [["ffmpeg", "-i", "in.mp4", "out.mp4"]],
            }
        )

        self.assertIn("Mode: export_clips_merged", details)
        self.assertIn("Selected intervals: 1", details)
        self.assertIn("FFmpeg commands: 1", details)
        self.assertIn("Final FFmpeg command: ffmpeg -i in.mp4 out.mp4", details)

    def test_duration_formatting(self):
        self.assertEqual(duration_text(None), "-")
        self.assertEqual(duration_text(1.23456), "1.235s")


class FakeSettingsService:
    def __init__(self, default_export_dir=None, export_dir=None):
        self.settings = SimpleNamespace(default_export_dir=default_export_dir, export_dir=export_dir)
        self.updates = []

    def load(self):
        return self.settings

    def update(self, **changes):
        self.updates.append(changes)
        return self.settings


class OutputPreferencesTests(unittest.TestCase):
    def test_explicit_output_directory_wins(self):
        preferences = OutputPreferences(FakeSettingsService(default_export_dir=Path("ignored")))

        output_dir = preferences.resolve_output_dir(Path("input.mp4"), "chosen")

        self.assertEqual(output_dir, Path("chosen"))

    def test_settings_default_export_directory_is_used(self):
        preferences = OutputPreferences(FakeSettingsService(default_export_dir=Path("settings-dir")))

        output_dir = preferences.resolve_output_dir(Path("input.mp4"), "")

        self.assertEqual(output_dir, Path("settings-dir"))

    def test_fallback_to_input_file_cuts_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_file = Path(tmp_dir) / "input.mp4"
            preferences = OutputPreferences(FakeSettingsService())

            output_dir = preferences.resolve_output_dir(input_file, "")

        self.assertEqual(output_dir, input_file.parent / "cuts")


if __name__ == "__main__":
    unittest.main()
