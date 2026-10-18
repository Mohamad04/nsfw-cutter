import subprocess
import unittest
from pathlib import Path

from services.export.media_probe_service import AudioStreamInfo, MediaInfo
from services.export.source_normalization_service import (
    MkvNormalizationService,
    SourceNormalizationError,
    _first_mismatch,
    _require_complete_file,
    _require_constant_frame_rate,
    needs_normalization,
)
from services.export.video_packet_index import VideoPacket


class _FakeFFmpegService:
    ffmpeg_path = Path("ffmpeg")
    ffprobe_path = Path("ffprobe")


def _media(format_name="matroska,webm", audio_streams=1, duration=1.0) -> MediaInfo:
    return MediaInfo(
        path=Path("in.mkv"),
        format_name=format_name,
        duration_seconds=duration,
        audio_streams=[AudioStreamInfo(index, "aac", 2, 48000, duration) for index in range(1, audio_streams + 1)],
    )


def _packets(times, hashes=None) -> list[VideoPacket]:
    return [VideoPacket(t, i == 0, (hashes or {}).get(i, f"h{i}")) for i, t in enumerate(times)]


class SourceNormalizationTests(unittest.TestCase):
    def test_only_matroska_sources_are_normalized(self):
        self.assertTrue(needs_normalization(_media("matroska,webm")))
        self.assertFalse(needs_normalization(_media("mov,mp4,m4a,3gp,3g2,mj2")))

    def test_remux_copies_only_first_video_and_audio_streams(self):
        service = MkvNormalizationService(ffmpeg_service=_FakeFFmpegService(), packet_index_service=object())

        command = service.build_command(Path("in.mkv"), Path("out.mp4"), has_audio=True)

        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertEqual([command[i + 1] for i, part in enumerate(command) if part == "-map"], ["0:v:0", "0:a:0"])
        self.assertIn("-sn", command)
        self.assertNotIn("libx264", command)

    def test_multiple_audio_tracks_are_refused_before_any_command(self):
        def runner(command, **_kwargs):
            self.fail("no FFmpeg command expected")

        service = MkvNormalizationService(ffmpeg_service=_FakeFFmpegService(), command_runner=runner,
                                          packet_index_service=object())

        with self.assertRaisesRegex(SourceNormalizationError, "at most one audio track"):
            service.normalize(Path("in.mkv"), Path("out.mp4"), _media(audio_streams=2))

    def test_verification_rejects_changed_data_moved_timestamps_and_missing_packets(self):
        source = _packets([0.0, 0.04, 0.08])

        self.assertIsNone(_first_mismatch(source, _packets([0.0, 0.0403, 0.08]), 0.0005))
        self.assertIn("differs", _first_mismatch(source, _packets([0.0, 0.04, 0.08], {1: "other"}), 0.0005))
        self.assertIn("moved", _first_mismatch(source, _packets([0.0, 0.041, 0.08]), 0.0005))
        self.assertIn("2 packets instead of 3", _first_mismatch(source, _packets([0.0, 0.04]), 0.0005))

    def test_variable_frame_rate_is_refused_but_millisecond_rounding_is_accepted(self):
        _require_constant_frame_rate(_packets([0.0, 0.041, 0.083, 0.125, 0.166]))  # 23.976 fps in ms
        with self.assertRaisesRegex(SourceNormalizationError, "variable-frame-rate"):
            _require_constant_frame_rate(_packets([0.0, 0.04, 0.08, 0.113, 0.146]))

    def test_incomplete_file_is_refused(self):
        _require_complete_file(_packets([0.0, 0.04, 9.96]), _media(duration=10.0))
        with self.assertRaisesRegex(SourceNormalizationError, "incomplete or damaged"):
            _require_complete_file(_packets([0.0, 0.04, 4.0]), _media(duration=10.0))

    def test_declared_duration_including_a_start_offset_is_not_mistaken_for_truncation(self):
        media = _media(duration=11.5)
        media.raw["format"] = {"start_time": "1.500000"}

        _require_complete_file(_packets([0.0, 0.04, 9.96]), media)

    def test_failed_remux_is_reported_without_claiming_success(self):
        class _Index:
            def probe(self, _path, stream="v:0"):
                return _packets([0.0, 0.04])

        service = MkvNormalizationService(
            ffmpeg_service=_FakeFFmpegService(),
            command_runner=lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, "", "Invalid data"),
            packet_index_service=_Index(),
        )

        with self.assertRaisesRegex(SourceNormalizationError, "lossless remux failed"):
            service.normalize(Path("in.mkv"), Path("out.mp4"), _media(duration=0.08))


if __name__ == "__main__":
    unittest.main()
