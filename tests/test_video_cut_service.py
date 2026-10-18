import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from schemas.video_cut_schema import VideoCutRequest, VideoCutSegment
from services.editing.cut_execution_service import (
    CutExecutionService,
    FastCuttingAudioError,
    FastCuttingPrecisionError,
    FastCuttingVerificationError,
    make_unique_path,
)
from services.export.video_packet_index import VideoPacket, packets_in_range
from services.infrastructure.ffmpeg.bounded_runner import ExportCancelledError
from services.infrastructure.ffmpeg.cutting import FFmpegCuttingService
from services.infrastructure.ffmpeg.runner import FFmpegNotFoundError, FFmpegService


class FakeFFmpegService:
    ffmpeg_path = Path("ffmpeg")
    ffprobe_path = Path("ffprobe")


class CutExecutionServiceTests(unittest.TestCase):
    def test_cut_command_uses_stream_copy_ss_and_duration(self):
        service = FFmpegCuttingService(ffmpeg_service=FakeFFmpegService(), command_runner=lambda *args, **kwargs: None)
        command = service.build_cut_command(Path("in.mp4"), Path("out.mp4"), 70.5, 150.75)

        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertEqual(command[command.index("-ss") + 1], "00:01:10.500")
        self.assertEqual(command[command.index("-t") + 1], "00:01:20.250")

    def test_tail_cut_command_runs_to_end_of_source(self):
        service = FFmpegCuttingService(ffmpeg_service=FakeFFmpegService(), command_runner=lambda *args, **kwargs: None)
        command = service.build_cut_command(Path("in.mp4"), Path("out.mp4"), 55, 72)

        self.assertEqual(command[command.index("-ss") + 1], "00:00:55.000")
        self.assertEqual(command[command.index("-t") + 1], "00:00:17.000")

    def test_export_segments_returns_unique_output_path(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            output_dir = temp_path / "cuts"
            output_dir.mkdir()
            (output_dir / "movie_clip_001_00-00-00_to_00-00-05.mp4").touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=output_dir,
                export_mode="export_clips_separate",
                cut_mode="stream_copy",
                segments=[VideoCutSegment(index=1, start_seconds=0, end_seconds=5)],
            )

            result = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {
                    "duration_seconds": 20 if Path(path) == input_path else 5,
                    "has_audio": True,
                },
                cache_dir=temp_path / "cache",
            ).export_segments(request)

            self.assertEqual(result.output_paths[0].name, "movie_clip_001_00-00-00_to_00-00-05_1.mp4")
            self.assertEqual(commands[0][-1], str(result.output_paths[0]))
            self.assertEqual(result.export_mode, "export_clips_separate")

    def test_stream_copy_remove_export_keeps_video_around_marked_cuts(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="remove_intervals",
                cut_mode="stream_copy",
                segments=[
                    VideoCutSegment(
                        index=1,
                        start_seconds=1,
                        end_seconds=2,
                        requested_start_seconds=1.2,
                        requested_end_seconds=1.8,
                    ),
                    VideoCutSegment(index=2, start_seconds=4, end_seconds=5),
                ],
            )

            result = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {
                    "duration_seconds": 10 if Path(path) == input_path else 8,
                    "has_audio": False,
                },
                cache_dir=temp_path / "cache",
                packet_probe=_intra_only_packet_probe(input_path, [(0.0, 1.0), (2.0, 4.0), (5.0, 10.0)]),
            ).export_segments(request)

            concat_command = commands[-1]
            self.assertEqual(len(commands), 4)
            self.assertEqual(commands[0][commands[0].index("-ss") + 1], "00:00:00.000")
            self.assertEqual(commands[0][commands[0].index("-t") + 1], "00:00:01.000")
            self.assertEqual([command[command.index("-frames:v") + 1] for command in commands[:3]], ["10", "20", "50"])
            self.assertEqual(commands[1][commands[1].index("-ss") + 1], "00:00:02.000")
            self.assertEqual(commands[1][commands[1].index("-t") + 1], "00:00:02.000")
            self.assertEqual(commands[2][commands[2].index("-ss") + 1], "00:00:05.000")
            self.assertEqual(commands[2][commands[2].index("-t") + 1], "00:00:05.000")
            self.assertEqual(concat_command[concat_command.index("-f") + 1], "concat")
            self.assertEqual(concat_command[concat_command.index("-c") + 1], "copy")
            self.assertEqual(result.merged_output_path.name, "movie_removed_intervals.mp4")
            self.assertEqual([segment.segment_index for segment in result.segments], [1, 2])
            self.assertTrue(all(segment.output_path == result.merged_output_path for segment in result.segments))
            self.assertEqual(result.segments[0].requested_start_seconds, 1.2)
            self.assertEqual(result.segments[0].requested_end_seconds, 1.8)
            self.assertEqual(result.normalized_intervals, [(1.0, 2.0), (4.0, 5.0)])
            self.assertEqual(result.kept_intervals, [(0.0, 1.0), (2.0, 4.0), (5.0, 10.0)])

    def test_merged_selected_clips_uses_only_stream_copy_commands(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="export_clips_merged",
                cut_mode="stream_copy",
                segments=[
                    VideoCutSegment(index=1, start_seconds=33, end_seconds=42),
                    VideoCutSegment(index=2, start_seconds=50, end_seconds=55),
                ],
            )

            result = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {
                    "duration_seconds": 72 if Path(path) == input_path else 14,
                    "has_audio": False,
                },
                cache_dir=temp_path / "cache",
                packet_probe=_intra_only_packet_probe(input_path, [(33.0, 42.0), (50.0, 55.0)], frame_count=720),
            ).export_segments(request)

            self.assertEqual(len(commands), 3)
            self.assertEqual([command[command.index("-frames:v") + 1] for command in commands[:2]], ["90", "50"])
            self.assertEqual(commands[0][commands[0].index("-ss") + 1], "00:00:33.000")
            self.assertEqual(commands[0][commands[0].index("-t") + 1], "00:00:09.000")
            self.assertEqual(commands[1][commands[1].index("-ss") + 1], "00:00:50.000")
            self.assertEqual(commands[1][commands[1].index("-t") + 1], "00:00:05.000")
            self.assertEqual(commands[2][commands[2].index("-f") + 1], "concat")
            self.assertEqual(result.merged_output_path.name, "movie_selected_clips_merged.mp4")
            self.assertEqual(result.expected_output_duration_seconds, 14.0)
            forbidden = {"libx264", "-c:v", "-c:a", "aac", "-crf", "-preset", "-filter_complex", "-vf", "-af"}
            for command in commands:
                self.assertEqual(command[command.index("-c") + 1], "copy")
                self.assertTrue(forbidden.isdisjoint(command))

    def test_merged_clips_export_the_union_of_overlapping_clips_once_in_source_order(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="export_clips_merged",
                cut_mode="stream_copy",
                segments=[
                    VideoCutSegment(index=1, start_seconds=6, end_seconds=8),
                    VideoCutSegment(index=2, start_seconds=1, end_seconds=4),
                    VideoCutSegment(index=3, start_seconds=3, end_seconds=5),
                    VideoCutSegment(index=4, start_seconds=7, end_seconds=8),
                ],
            )

            result = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": False},
                cache_dir=temp_path / "cache",
                packet_probe=_intra_only_packet_probe(input_path, [(1.0, 5.0), (6.0, 8.0)]),
            ).export_segments(request)

            self.assertEqual(result.normalized_intervals, [(1.0, 5.0), (6.0, 8.0)])
            self.assertEqual(result.expected_output_duration_seconds, 6.0)
            self.assertEqual([command[command.index("-ss") + 1] for command in commands[:2]], ["00:00:01.000", "00:00:06.000"])

    def test_merged_clip_starting_after_the_end_of_the_video_is_refused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="export_clips_merged",
                cut_mode="stream_copy",
                segments=[
                    VideoCutSegment(index=1, start_seconds=1, end_seconds=2),
                    VideoCutSegment(index=2, start_seconds=12, end_seconds=14),
                ],
            )
            service = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=lambda command, **_kwargs: self.fail("no FFmpeg command expected"),
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": False},
                cache_dir=temp_path / "cache",
                packet_probe=lambda path: self.fail("no packet probe expected"),
            )

            with self.assertRaisesRegex(ValueError, "Clip 2 starts at 00:00:12.000, after the end of the video"):
                service.export_segments(request)

    def test_fast_removal_off_keyframe_is_refused_before_any_ffmpeg_command(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="remove_intervals",
                cut_mode="stream_copy",
                segments=[VideoCutSegment(index=1, start_seconds=1.3, end_seconds=4.0)],
            )
            service = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": False},
                cache_dir=temp_path / "cache",
                packet_probe=lambda path: _gop_packets(keyframe_every=10),
            )

            with self.assertRaises(FastCuttingPrecisionError) as caught:
                service.export_segments(request)

            message = str(caught.exception)
            self.assertIn("00:00:01.300 (nearest keyframes 00:00:01.000 and 00:00:02.000)", message)
            self.assertNotIn("00:00:04.000 (", message)
            self.assertIn("Use Smart Cutting", message)
            self.assertEqual(commands, [])
            self.assertFalse((temp_path / "cuts" / "movie_removed_intervals.mp4").exists())

    def test_fast_removal_deletes_output_that_fails_verification(self):
        def command_runner(command, **_kwargs):
            Path(command[-1]).write_bytes(b"x")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            packets = _gop_packets(keyframe_every=10)
            kept = [packet for packet in packets if not 2.0 <= packet.pts_seconds < 4.0]

            def packet_probe(path):
                path = Path(path)
                if path == input_path:
                    return packets
                if "kept_ranges_001" in path.name:
                    return [packet for packet in packets if packet.pts_seconds < 2.0]
                if "kept_ranges_002" in path.name:
                    return [packet for packet in packets if packet.pts_seconds >= 4.0]
                return kept[:-1]  # joined output lost a frame

            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="remove_intervals",
                cut_mode="stream_copy",
                segments=[VideoCutSegment(index=1, start_seconds=2.0, end_seconds=4.0)],
            )
            service = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": False},
                cache_dir=temp_path / "cache",
                packet_probe=packet_probe,
            )

            with self.assertRaises(FastCuttingVerificationError):
                service.export_segments(request)

            self.assertFalse((temp_path / "cuts" / "movie_removed_intervals.mp4").exists())

    def test_fast_removal_with_audio_is_refused_before_any_ffmpeg_command(self):
        commands = []

        def command_runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.touch()
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=temp_path / "cuts",
                export_mode="remove_intervals",
                cut_mode="stream_copy",
                segments=[VideoCutSegment(index=1, start_seconds=2.0, end_seconds=4.0)],
            )
            service = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": True},
                cache_dir=temp_path / "cache",
                packet_probe=lambda path: self.fail("no packet probe expected"),
            )

            with self.assertRaises(FastCuttingAudioError) as caught:
                service.export_segments(request)

            self.assertIn("Use Smart Cutting", str(caught.exception))
            self.assertEqual(commands, [])
            self.assertFalse((temp_path / "cuts").exists() and any((temp_path / "cuts").iterdir()))

    def test_cancellation_removes_only_files_created_by_the_export(self):
        def command_runner(command, **_kwargs):
            output = Path(command[-1])
            output.write_bytes(b"partial")
            if "concat" in command:
                raise ExportCancelledError("Video export was cancelled. No output was kept.")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "movie.mp4"
            input_path.write_bytes(b"source")
            output_dir = temp_path / "cuts"
            output_dir.mkdir()
            existing = output_dir / "movie_removed_intervals.mp4"
            existing.write_bytes(b"older export")
            request = VideoCutRequest(
                input_path=input_path,
                output_dir=output_dir,
                export_mode="remove_intervals",
                cut_mode="stream_copy",
                segments=[VideoCutSegment(index=1, start_seconds=2.0, end_seconds=4.0)],
            )
            packets = _gop_packets(keyframe_every=10)

            def packet_probe(path):
                path = Path(path)
                if "kept_ranges_001" in path.name:
                    return [packet for packet in packets if packet.pts_seconds < 2.0]
                if "kept_ranges_002" in path.name:
                    return [packet for packet in packets if packet.pts_seconds >= 4.0]
                return packets

            service = CutExecutionService(
                ffmpeg_service=FakeFFmpegService(),
                command_runner=command_runner,
                metadata_probe=lambda path: {"duration_seconds": 10, "has_audio": False},
                cache_dir=temp_path / "cache",
                packet_probe=packet_probe,
            )

            with self.assertRaises(ExportCancelledError):
                service.export_segments(request)

            self.assertEqual(input_path.read_bytes(), b"source")
            self.assertEqual(existing.read_bytes(), b"older export")
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), ["movie_removed_intervals.mp4"])
            self.assertEqual(list((temp_path / "cache").iterdir()), [])

    def test_make_unique_path_adds_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clip.mp4"
            path.touch()
            self.assertEqual(make_unique_path(path).name, "clip_1.mp4")

    def test_ffmpeg_not_found_has_clear_error(self):
        with patch("services.infrastructure.ffmpeg.paths._runtime_roots", return_value=(Path("missing"),)):
            with patch("services.infrastructure.ffmpeg.paths.shutil.which", return_value=None):
                with self.assertRaisesRegex(FFmpegNotFoundError, "FFmpeg executable was not found"):
                    FFmpegService()


def _gop_packets(keyframe_every: int, frame_count: int = 100, fps: int = 10) -> list[VideoPacket]:
    return [VideoPacket(round(index / fps, 3), index % keyframe_every == 0, f"h{index}") for index in range(frame_count)]


def _intra_only_packet_probe(input_path: Path, kept_ranges: list[tuple[float, float]], frame_count: int = 100):
    packets = _gop_packets(keyframe_every=1, frame_count=frame_count)

    def probe(path):
        path = Path(path)
        if path == input_path:
            return packets
        chunk = re.search(r"_(?:kept_ranges|selected_clips)_(\d{3})$", path.stem)
        if chunk:
            start, end = kept_ranges[int(chunk.group(1)) - 1]
            return packets_in_range(packets, start, end)
        return [packet for start, end in kept_ranges for packet in packets_in_range(packets, start, end)]

    return probe


if __name__ == "__main__":
    unittest.main()
