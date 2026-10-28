"""Real FFmpeg regression tests for export safety defects D3 (Smart Cutting) and D4 (Fast Cutting).

Every completed export is decoded frame by frame: no source frame whose PTS lies in a removed
interval may appear, every kept frame must appear exactly once and in order, and audio clicks
must stay within one frame of the video. Exports run through the production bounded runner and
every other subprocess has a timeout, so the known encoder hang (D1) cannot block a run.
"""

import functools
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from evaluation import export_frame_accuracy as efa
from schemas.video_cut_schema import VideoCutRequest
from services.editing.cut_execution_service import CutExecutionService, FastCuttingAudioError
from services.export.smart_cutting_export_service import SmartCuttingExportService
from services.export.video_segment_renderer import VideoSegmentVerificationError
from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner
from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_ffprobe_path,
)

SUBPROCESS_TIMEOUT_SECONDS = 90
STALL_TIMEOUT_SECONDS = 20
FRAME_MS = 1000 / efa.FPS
TEN_HALF_SECOND_CUTS = [(1.0 + 2.5 * k, 1.5 + 2.5 * k) for k in range(10)]
TEN_OFF_GRID_CUTS = [(round(1.013 + 2.5 * k, 3), round(1.517 + 2.5 * k, 3)) for k in range(10)]
TEN_KEYFRAME_CUTS = [(1.0 + 2 * k, 2.0 + 2 * k) for k in range(10)]
D1_REASON = (
    "Defect D1: this FFmpeg build's native AAC encoder (mono, 192 kb/s) hangs on a tone burst after "
    "silence; bundle a stable FFmpeg release (8.1.1 validated) in vendor/ffmpeg/bin."
)
_original_run = subprocess.run


@functools.wraps(_original_run)
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", SUBPROCESS_TIMEOUT_SECONDS)
    return _original_run(*args, **kwargs)


_SHARED: dict = {}


def setUpModule():
    """Generate every synthetic fixture once for all test classes of this module."""
    try:
        ffmpeg, ffprobe = get_ffmpeg_path(), get_ffprobe_path()
    except FFmpegNotFoundError as exc:
        _SHARED["skip"] = str(exc)
        return
    _SHARED["timeout_patch"] = patch("subprocess.run", _run_with_timeout)
    _SHARED["timeout_patch"].start()
    root = Path(tempfile.mkdtemp(prefix="export-frame-accuracy-"))
    specs = {
        **efa.FIXTURES,
        "h264_noaudio_gop25_mp4": efa.FixtureSpec("h264_noaudio_gop25_mp4", audio=False, gop_frames=25),
        "h264_noaudio_opengop_mp4": efa.FixtureSpec("h264_noaudio_opengop_mp4", audio=False, open_gop=True),
        "h264_noaudio_mkv": efa.FixtureSpec("h264_noaudio_mkv", audio=False, container="mkv"),
        "marker_7.3_12.7_mp4": efa.FixtureSpec("marker_7.3_12.7_mp4", marker_intervals=((7.3, 12.7),)),
        "marker_7.3_12.7_mkv": efa.FixtureSpec("marker_7.3_12.7_mkv", container="mkv", marker_intervals=((7.3, 12.7),)),
        "h264_aac_opengop_mkv": efa.FixtureSpec("h264_aac_opengop_mkv", open_gop=True, container="mkv"),
        "h264_aac_offset_mkv": efa.FixtureSpec("h264_aac_offset_mkv", container="mkv", start_offset=1.5),
        "h264_aac_vfr_mkv": efa.FixtureSpec("h264_aac_vfr_mkv", container="mkv", variable_frame_rate=True),
        "h264_aac_2audio_mkv": efa.FixtureSpec("h264_aac_2audio_mkv", container="mkv", audio_tracks=2),
        "h264_aac_ts90k_mp4": efa.FixtureSpec("h264_aac_ts90k_mp4", video_timescale=90000),
    }
    fixtures = {name: efa.generate_fixture(ffmpeg, spec, root / "fixtures") for name, spec in specs.items()}
    data = fixtures["h264_aac_mkv"].read_bytes()
    fixtures["h264_aac_truncated_mkv"] = root / "fixtures" / "h264_aac_truncated.mkv"
    fixtures["h264_aac_truncated_mkv"].write_bytes(data[: int(len(data) * 0.4)])
    fixtures["garbage_mkv"] = root / "fixtures" / "garbage.mkv"
    fixtures["garbage_mkv"].write_bytes(b"not a matroska file" * 1000)
    _SHARED.update(ffmpeg=ffmpeg, ffprobe=ffprobe, root=root, fixtures=fixtures,
                   aac_encoder_hangs=efa.aac_encoder_hangs(ffmpeg, root / "d1"))


def tearDownModule():
    if "timeout_patch" in _SHARED:
        _SHARED["timeout_patch"].stop()
    if "root" in _SHARED:
        shutil.rmtree(_SHARED["root"], ignore_errors=True)


class _FrameAccuracyCase(unittest.TestCase):
    fixtures: ClassVar[dict[str, Path]] = {}

    @classmethod
    def setUpClass(cls):
        if _SHARED.get("skip"):
            raise unittest.SkipTest(_SHARED["skip"])
        cls.ffmpeg, cls.ffprobe = _SHARED["ffmpeg"], _SHARED["ffprobe"]
        cls._root = _SHARED["root"]
        cls.fixtures = _SHARED["fixtures"]
        cls.aac_encoder_hangs = _SHARED["aac_encoder_hangs"]

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self._root))
        self.output_dir = self.work / "out"
        self.cache_dir = self.work / "cache"

    def assert_frame_exact(self, output_path: Path, removed, *, audio: bool, check_duration: bool = True):
        frames = efa.decode_frames(self.ffmpeg, self.ffprobe, output_path)
        report = efa.removal_report(frames, removed)
        self.assertEqual(report["leaked_removed_frames"], 0, report["leaked_runs"])
        self.assertEqual(report["missing_kept_frames"], 0, report["missing_runs"])
        self.assertEqual(report["duplicate_frames"], 0, report)
        self.assertTrue(report["monotonic"], report)
        self.assertEqual(report["undecodable_frames"], 0, report)
        if check_duration:
            durations = efa.stream_durations(self.ffprobe, output_path)
            self.assertAlmostEqual(durations["video"], efa.expected_kept_duration(removed), delta=1.5 / efa.FPS)
        sync = efa.av_sync(self.ffmpeg, output_path, frames)
        if audio:
            self.assertTrue(sync["audio"], "exported file lost its audio stream")
            self.assertGreater(sync["measured_onsets"], 0)
            self.assertLessEqual(sync["max_abs_offset_ms"], FRAME_MS, sync)
        else:
            self.assertFalse(sync["audio"])
        return report

    def assert_no_files(self, *folders: Path):
        for folder in folders:
            leftovers = [path for path in folder.rglob("*") if path.is_file()] if folder.exists() else []
            self.assertEqual(leftovers, [], f"unexpected files left in {folder}")


class SmartCuttingFrameAccuracyTests(_FrameAccuracyCase):
    def smart_export(self, fixture: str, removed) -> dict:
        segments = [
            {"index": index, "requested_start_seconds": start, "requested_end_seconds": end}
            for index, (start, end) in enumerate(removed, start=1)
        ]
        service = SmartCuttingExportService(
            cache_dir=self.cache_dir,
            process_runner=BoundedProcessRunner(stall_timeout_seconds=STALL_TIMEOUT_SECONDS),
        )
        payload = service.export(
            {
                "input_path": str(self.fixtures[fixture]),
                "output_dir": str(self.output_dir),
                "segments": segments,
                "export_mode": "remove_intervals",
            }
        )
        return payload["result"]

    def check(self, fixture: str, removed, *, audio: bool = True) -> dict:
        result = self.smart_export(fixture, removed)
        self.assert_frame_exact(Path(result["merged_output_path"]), removed, audio=audio)
        self.assert_no_files(self.cache_dir)
        return result

    def test_non_keyframe_cut_is_frame_exact(self):
        self.check("h264_aac_mp4", [(7.3, 12.7)])

    def test_cut_starting_on_keyframe_does_not_leak_the_keyframe(self):
        self.check("h264_aac_mp4", [(6.0, 7.0)])

    def test_ten_cuts_are_frame_exact_and_in_sync(self):
        self.check("h264_aac_mp4", TEN_HALF_SECOND_CUTS)

    def test_ten_cuts_off_the_frame_grid_stay_in_sync(self):
        self.check("h264_aac_mp4", TEN_OFF_GRID_CUTS)

    def test_adjacent_and_overlapping_cuts(self):
        self.check("h264_aac_mp4", [(5.0, 6.0), (6.0, 7.3)])
        self.check("h264_aac_mp4", [(5.0, 8.0), (7.0, 9.3)])

    def test_cuts_at_beginning_and_end(self):
        self.check("h264_noaudio_mp4", [(0.0, 2.3), (27.7, 30.0)], audio=False)
        self.check("h264_aac_mp4", [(25.3, 40.0)])

    def test_cuts_at_beginning_and_end_with_audio(self):
        # Case S06: hung forever with the former nightly FFmpeg (D1); must complete frame-exact.
        self.check("h264_aac_mp4", [(0.0, 2.3), (27.7, 30.0)])

    def test_bundled_aac_encoder_does_not_hang(self):
        # Minimal D1 reproduction (tone burst after digital silence, mono, 192 kb/s).
        self.assertFalse(self.aac_encoder_hangs, D1_REASON)

    def test_removed_audio_is_absent_at_sample_level(self):
        # Marker fixture: the source audio is digital silence except a 3 kHz tone inside [7.3, 12.7).
        result = self.smart_export("marker_7.3_12.7_mp4", [(7.3, 12.7)])

        residual = efa.audible_runs(self.ffmpeg, Path(result["merged_output_path"]))
        self.assertEqual(residual["audible_ms"], 0, residual)

    def test_no_audio_source(self):
        self.check("h264_noaudio_mp4", [(7.3, 12.7)], audio=False)

    def test_open_gop_source_falls_back_to_reencoding_copy_segments(self):
        result = self.check("h264_aac_opengop_mp4", [(7.3, 12.7), (16.0, 17.0)])

        self.assertTrue(result["video_fallbacks"], "open-GOP copy segments must be re-encoded, not copied")
        self.assertTrue(all(item["reason"] for item in result["video_fallbacks"]))

    def test_verification_is_reported(self):
        result = self.check("h264_aac_mp4", [(7.3, 12.7)])

        self.assertEqual(result["video_fallbacks"], [])
        self.assertEqual(result["verification"]["final_video_packets"], result["verification"]["expected_video_frames"])

    def test_mp4_with_a_90k_video_timescale_keeps_frame_timing(self):
        # Copy chunks keep the source timescale; re-encoded chunks must use it too, or concat shifts them.
        self.check("h264_aac_ts90k_mp4", [(7.3, 12.7)])


class MkvSmartCuttingTests(_FrameAccuracyCase):
    """D2: MKV H.264 sources are normalized losslessly to MP4, verified, then cut by the same pipeline."""

    smart_export = SmartCuttingFrameAccuracyTests.smart_export
    check = SmartCuttingFrameAccuracyTests.check

    def test_mkv_non_keyframe_cut_is_frame_exact(self):
        result = self.check("h264_aac_mkv", [(7.3, 12.7)])

        self.assertTrue(Path(result["merged_output_path"]).name.endswith("_smart_cut.mkv"))
        normalization = result["source_normalization"]
        self.assertEqual(normalization["method"], "mkv_to_mp4_stream_copy")
        self.assertEqual(normalization["verified_video_packets"], efa.SOURCE_FRAMES)
        self.assertGreater(normalization["verified_audio_packets"], 0)

    def test_mkv_without_audio(self):
        self.check("h264_noaudio_mkv", [(7.3, 12.7)], audio=False)

    def test_mkv_cut_starting_on_a_keyframe(self):
        self.check("h264_aac_mkv", [(6.0, 7.0)])

    def test_mkv_ten_cuts_on_and_off_the_frame_grid(self):
        self.check("h264_aac_mkv", TEN_HALF_SECOND_CUTS)
        self.check("h264_aac_mkv", TEN_OFF_GRID_CUTS)

    def test_mkv_cuts_at_beginning_and_end(self):
        self.check("h264_aac_mkv", [(0.0, 2.3), (27.7, 30.0)])

    def test_mkv_open_gop(self):
        result = self.check("h264_aac_opengop_mkv", [(7.3, 12.7), (16.0, 17.0)])

        self.assertTrue(result["video_fallbacks"])

    def test_mkv_with_a_non_zero_start_time(self):
        # The container timeline starts at 1.5 s; cut times are relative to the start, like the player's.
        self.check("h264_aac_offset_mkv", [(7.3, 12.7)])

    def test_mkv_removed_audio_is_absent_at_sample_level(self):
        result = self.smart_export("marker_7.3_12.7_mkv", [(7.3, 12.7)])

        residual = efa.audible_runs(self.ffmpeg, Path(result["merged_output_path"]))
        self.assertEqual(residual["audible_ms"], 0, residual)

    def test_mismatched_chunk_timescales_are_detected(self):
        # Regression guard: without the shared track timescale, concat shifts re-encoded chunks.
        with patch("services.export.smart_cutting_export_service._track_timescale", return_value=None):
            with self.assertRaises(VideoSegmentVerificationError) as caught:
                self.smart_export("h264_aac_mkv", [(7.3, 12.7)])
        self.assertIn("frame timing", str(caught.exception))
        self.assert_no_files(self.output_dir, self.cache_dir)

    def assert_refused(self, fixture: str, *fragments: str):
        with self.assertRaises(ValueError) as caught:
            self.smart_export(fixture, [(7.3, 12.7)])
        for fragment in fragments:
            self.assertIn(fragment, str(caught.exception))
        self.assert_no_files(self.output_dir, self.cache_dir)

    def test_variable_frame_rate_mkv_is_refused(self):
        self.assert_refused("h264_aac_vfr_mkv", "variable-frame-rate", "Nothing was exported")

    def test_mkv_with_two_audio_tracks_is_refused(self):
        self.assert_refused("h264_aac_2audio_mkv", "at most one audio track")

    def test_truncated_mkv_is_refused(self):
        self.assert_refused("h264_aac_truncated_mkv", "incomplete or damaged")

    def test_corrupted_mkv_fails_without_output(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.smart_export("garbage_mkv", [(7.3, 12.7)])
        self.assert_no_files(self.output_dir, self.cache_dir)


class FastCuttingFrameAccuracyTests(_FrameAccuracyCase):
    def fast_export(self, fixture: str, removed):
        request = VideoCutRequest(
            input_path=self.fixtures[fixture],
            output_dir=self.output_dir,
            export_mode="remove_intervals",
            segments=[
                {"index": index, "start_seconds": start, "end_seconds": end}
                for index, (start, end) in enumerate(removed, start=1)
            ],
        )
        runner = BoundedProcessRunner(stall_timeout_seconds=STALL_TIMEOUT_SECONDS)
        service = CutExecutionService(cache_dir=self.cache_dir, command_runner=runner, probe_runner=runner)
        return service.export_segments(request)

    def check(self, fixture: str, removed):
        result = self.fast_export(fixture, removed)
        self.assert_frame_exact(result.merged_output_path, removed, audio=False)
        self.assertIsNone(result.duration_warning)
        return result

    def assert_refused(self, fixture: str, removed, *expected_fragments: str):
        with self.assertRaises(ValueError) as caught:
            self.fast_export(fixture, removed)
        message = str(caught.exception)
        for fragment in expected_fragments:
            self.assertIn(fragment, message)
        self.assert_no_files(self.output_dir)
        return caught.exception

    def test_source_with_audio_is_refused(self):
        # Stream-copied AAC keeps ~0.1 s of removed sound per splice (measured on decoded samples).
        error = self.assert_refused("h264_aac_mp4", [(8.0, 12.0)], "cannot remove audio exactly", "Smart Cutting")
        self.assertIsInstance(error, FastCuttingAudioError)

    def test_non_keyframe_cut_is_refused_with_actionable_message(self):
        self.assert_refused(
            "h264_noaudio_mp4",
            [(7.3, 12.7)],
            "00:00:07.300",
            "00:00:12.700",
            "00:00:06.000",
            "00:00:08.000",
            "Smart Cutting",
            "Nothing was exported",
        )

    def test_joined_output_duration_matches_kept_frames(self):
        # Defect D10 (~96 ms timestamp gap per splice) comes from the audio stream starting earlier than
        # the video in each stream-copied chunk. It is not fixed; it is unreachable because sources with
        # audio are refused. Video-only joins must keep the exact duration.
        removed = [(8.0, 12.0)]
        result = self.fast_export("h264_noaudio_mp4", removed)
        durations = efa.stream_durations(self.ffprobe, result.merged_output_path)
        self.assertAlmostEqual(durations["video"], efa.expected_kept_duration(removed), delta=1.5 / efa.FPS)

    def test_ten_unaligned_cuts_are_refused(self):
        self.assert_refused("h264_noaudio_mp4", TEN_HALF_SECOND_CUTS, "Smart Cutting")

    def test_keyframe_aligned_cut_is_frame_exact(self):
        self.check("h264_noaudio_mp4", [(8.0, 12.0)])

    def test_ten_keyframe_aligned_cuts_are_frame_exact(self):
        self.check("h264_noaudio_gop25_mp4", TEN_KEYFRAME_CUTS)

    def test_adjacent_and_overlapping_aligned_cuts(self):
        self.check("h264_noaudio_mp4", [(6.0, 8.0), (8.0, 10.0)])
        self.check("h264_noaudio_mp4", [(6.0, 10.0), (8.0, 12.0)])

    def test_cuts_at_beginning_and_end(self):
        self.check("h264_noaudio_mp4", [(0.0, 2.0), (28.0, 30.0)])
        self.check("h264_noaudio_mp4", [(26.0, 40.0)])

    def test_open_gop_keyframes_are_refused(self):
        self.assert_refused("h264_noaudio_opengop_mp4", [(8.0, 12.0)], "Smart Cutting")

    def test_mkv_source_is_exact_or_refused_without_output(self):
        removed = [(8.0, 12.0)]
        try:
            result = self.fast_export("h264_noaudio_mkv", removed)
        except ValueError as exc:
            self.assertIn("Smart Cutting", str(exc))
            self.assert_no_files(self.output_dir)
            return
        self.assert_frame_exact(result.merged_output_path, removed, audio=False)


if __name__ == "__main__":
    unittest.main()
