import tempfile
import threading
import unittest
from pathlib import Path

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.frame_extraction import FFmpegHybridFrameExtractor
from services.analysis.preprocessing_contracts import PreprocessingConfig, ProcessingChunk
from services.analysis.process import CancellableProcessRunner
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path
from services.infrastructure.ffmpeg.runner import FFmpegService


class FFmpegHybridFrameExtractorTests(unittest.TestCase):
    def test_command_uses_one_input_and_one_union_sampling_filter(self):
        extractor = FFmpegHybridFrameExtractor(
            ffmpeg_service=_PathOnlyFFmpegService(Path("ffmpeg"))
        )
        config = PreprocessingConfig(
            max_sampling_gap_seconds=1.0,
            target_width=384,
            target_height=384,
        )
        chunk = ProcessingChunk(
            index=1,
            core_start_us=4_000_000,
            core_end_us=8_000_000,
            decode_start_us=3_750_000,
            decode_end_us=8_250_000,
        )

        command = extractor.build_command("movie.mkv", chunk, config)
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertEqual(command.count("-i"), 1)
        self.assertIn("select=", str(filter_graph))
        self.assertIn("prev_t", str(filter_graph))
        self.assertIn("scene", str(filter_graph))
        self.assertNotIn("split", str(filter_graph))
        self.assertIn("scale=w=384:h=384", str(filter_graph))
        self.assertIn("reset_sar=1", str(filter_graph))
        self.assertIn("pad=384:384", str(filter_graph))
        self.assertEqual(command[-2:], ["rawvideo", "pipe:1"])

    def test_cancellation_stops_streaming_process_without_orphan(self):
        try:
            ffmpeg_path = get_ffmpeg_path()
        except FFmpegNotFoundError as exc:
            self.skipTest(str(exc))

        runner = CancellableProcessRunner()
        extractor = _InfiniteLavfiExtractor(
            ffmpeg_service=FFmpegService(ffmpeg_path=ffmpeg_path, ffprobe_path=ffmpeg_path),
            process_runner=runner,
        )
        config = PreprocessingConfig(target_width=64, target_height=64)
        chunk = ProcessingChunk(
            index=0,
            core_start_us=0,
            core_end_us=1_000_000,
            decode_start_us=0,
            decode_end_us=1_000_000,
        )
        cancellation = CancellationToken()
        timer = threading.Timer(0.2, cancellation.cancel)
        timer.start()
        try:
            with self.assertRaises(AnalysisCancelled):
                list(extractor.extract("unused.mp4", chunk, config, cancellation))
        finally:
            timer.cancel()

        self.assertEqual(runner.active_process_count, 0)

    def test_corrupt_input_propagates_ffmpeg_failure_and_reaps_process(self):
        try:
            ffmpeg_path = get_ffmpeg_path()
        except FFmpegNotFoundError as exc:
            self.skipTest(str(exc))

        runner = CancellableProcessRunner()
        extractor = FFmpegHybridFrameExtractor(
            ffmpeg_service=FFmpegService(ffmpeg_path=ffmpeg_path, ffprobe_path=ffmpeg_path),
            process_runner=runner,
        )
        config = PreprocessingConfig(target_width=64, target_height=64)
        chunk = ProcessingChunk(
            index=0,
            core_start_us=0,
            core_end_us=1_000_000,
            decode_start_us=0,
            decode_end_us=1_000_000,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            corrupt_path = Path(temp_dir) / "corrupt.mp4"
            corrupt_path.write_bytes(b"not a media container")

            with self.assertRaises(RuntimeError):
                list(extractor.extract(corrupt_path, chunk, config, CancellationToken()))

        self.assertEqual(runner.active_process_count, 0)


class _PathOnlyFFmpegService:
    def __init__(self, ffmpeg_path: Path):
        self.ffmpeg_path = ffmpeg_path


class _InfiniteLavfiExtractor(FFmpegHybridFrameExtractor):
    def build_command(self, video_path, chunk, config):
        return [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={config.target_width}x{config.target_height}:rate=30",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]


if __name__ == "__main__":
    unittest.main()
