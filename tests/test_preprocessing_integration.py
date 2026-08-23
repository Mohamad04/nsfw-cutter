import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from services.analysis.cancellation import CancellationToken
from services.analysis.chunking import owning_chunk_index, plan_processing_chunks
from services.analysis.frame_extraction import FFmpegHybridFrameExtractor
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_benchmark import run_benchmark_suite
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    PreprocessingConfig,
    SampleReason,
)
from services.export.media_probe_service import MediaProbeService
from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_ffprobe_path,
)
from services.infrastructure.ffmpeg.runner import FFmpegService


class GeneratedVideoPreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            ffmpeg_path = get_ffmpeg_path()
            ffprobe_path = get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc

        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls._temporary_directory.name)
        cls.video_path = cls.root / "preprocessing-fixture.mp4"
        cls.vfr_video_path = cls.root / "vfr-fixture.mp4"
        cls.ffmpeg_service = FFmpegService(ffmpeg_path, ffprobe_path)
        _generate_fixture(ffmpeg_path, cls.video_path)
        _generate_vfr_fixture(ffmpeg_path, cls.vfr_video_path)
        cls.config = PreprocessingConfig(
            chunk_duration_seconds=4.0,
            chunk_overlap_seconds=0.5,
            max_sampling_gap_seconds=0.5,
            scene_threshold=0.2,
            target_width=64,
            target_height=64,
            static_suppression_limit_seconds=2.0,
        )

    @classmethod
    def tearDownClass(cls):
        cls._temporary_directory.cleanup()

    def test_hybrid_extraction_has_global_real_timestamps_and_safety_coverage(self):
        media_info = MediaProbeService(ffmpeg_service=self.ffmpeg_service).probe(
            self.video_path
        )
        duration_us = round(media_info.duration_seconds * 1_000_000)
        chunks = plan_processing_chunks(duration_us, self.config)
        extractor = FFmpegHybridFrameExtractor(ffmpeg_service=self.ffmpeg_service)
        frames = []
        cancellation = CancellationToken()

        for chunk in chunks:
            for frame in extractor.extract(
                self.video_path,
                chunk,
                self.config,
                cancellation,
            ):
                if owning_chunk_index(chunks, frame.timestamp_us) == chunk.index:
                    frames.append(frame)

        timestamps = [frame.timestamp_us for frame in frames]
        temporal_timestamps = [
            frame.timestamp_us
            for frame in frames
            if SampleReason.TEMPORAL_SAFETY in frame.sample_reasons
        ]
        temporal_gaps = [
            right - left
            for left, right in zip(
                temporal_timestamps[:-1], temporal_timestamps[1:], strict=True
            )
        ]

        self.assertEqual(timestamps, sorted(timestamps))
        self.assertGreater(len(temporal_timestamps), 1)
        self.assertLessEqual(max(temporal_gaps), self.config.max_sampling_gap_us)
        self.assertLessEqual(temporal_timestamps[0], self.config.max_sampling_gap_us)
        self.assertLessEqual(
            duration_us - temporal_timestamps[-1],
            self.config.max_sampling_gap_us,
        )
        self.assertTrue(
            any(SampleReason.SCENE_TRANSITION in frame.sample_reasons for frame in frames)
        )
        self.assertTrue(
            any(
                frame.sample_reasons
                == frozenset(
                    {SampleReason.TEMPORAL_SAFETY, SampleReason.SCENE_TRANSITION}
                )
                for frame in frames
            )
        )
        self.assertTrue(
            any(
                frame.sample_reasons == frozenset({SampleReason.SCENE_TRANSITION})
                for frame in frames
            )
        )
        self.assertTrue(all(frame.source_pts is not None for frame in frames))
        self.assertTrue(all(frame.source_time_base for frame in frames))
        self.assertTrue(all(frame.content_rect[3] < frame.height for frame in frames))

    def test_full_slice_filters_black_static_and_overlap_conservatively(self):
        result = MoviePreprocessingService(
            ffmpeg_service=self.ffmpeg_service
        ).preprocess(
            self.video_path,
            config=self.config,
            cancellation=CancellationToken(),
        )

        statistics = result.statistics
        representatives = result.representative_frames
        timestamps = [sample.timestamp_us for sample in representatives]

        self.assertEqual(statistics.chunks_processed, 3)
        self.assertGreater(statistics.black_frames_removed, 0)
        self.assertGreater(statistics.static_frames_suppressed, 0)
        self.assertGreater(statistics.scene_samples, 0)
        self.assertEqual(statistics.representative_frames, len(representatives))
        self.assertEqual(
            statistics.samples_considered,
            statistics.black_frames_removed
            + statistics.duplicates_removed
            + statistics.static_frames_suppressed
            + statistics.representative_frames,
        )
        self.assertGreater(statistics.media_throughput, 0.0)
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertTrue(
            any(5_000_000 <= sample.timestamp_us < 7_900_000 for sample in representatives)
        )
        self.assertTrue(
            any(
                SampleReason.SCENE_TRANSITION in sample.sample_reasons
                and abs(sample.timestamp_us - 7_900_000) <= 200_000
                for sample in representatives
            )
        )
        self.assertTrue(
            all(sample.disposition is FrameDisposition.REPRESENTATIVE for sample in representatives)
        )
        for left, right in zip(representatives[:-1], representatives[1:], strict=True):
            same_visual = (
                left.perceptual_hash == right.perceptual_hash
                and left.regional_hashes == right.regional_hashes
            )
            self.assertFalse(
                same_visual and abs(right.timestamp_us - left.timestamp_us) <= 50_000
            )

    def test_variable_frame_rate_samples_use_source_pts_not_frame_index_math(self):
        config = PreprocessingConfig(
            chunk_duration_seconds=4.0,
            chunk_overlap_seconds=0.5,
            max_sampling_gap_seconds=0.5,
            scene_threshold=1.0,
            target_width=64,
            target_height=64,
        )
        media_info = MediaProbeService(ffmpeg_service=self.ffmpeg_service).probe(
            self.vfr_video_path
        )
        duration_us = round(media_info.duration_seconds * 1_000_000)
        chunk = plan_processing_chunks(duration_us, config)[0]
        frames = list(
            FFmpegHybridFrameExtractor(ffmpeg_service=self.ffmpeg_service).extract(
                self.vfr_video_path,
                chunk,
                config,
                CancellationToken(),
            )
        )
        timestamps = [frame.timestamp_us for frame in frames]
        gaps = [
            right - left
            for left, right in zip(timestamps[:-1], timestamps[1:], strict=True)
        ]

        self.assertEqual(timestamps, sorted(timestamps))
        self.assertGreater(len(set(gaps)), 1)
        self.assertLessEqual(max(gaps), config.max_sampling_gap_us)
        for frame in frames:
            numerator, denominator = map(int, frame.source_time_base.split("/"))
            expected = round(
                Fraction(frame.source_pts * numerator, denominator) * 1_000_000
            )
            self.assertEqual(frame.timestamp_us, expected)

    def test_benchmark_runs_the_production_pipeline_and_serializes_measurements(self):
        suite = run_benchmark_suite(
            self.video_path,
            [self.config],
            runs=1,
            monitor_resources=False,
            ffmpeg_service=self.ffmpeg_service,
        )

        run = suite.cases[0].runs[0]
        payload = suite.model_dump(mode="json")

        self.assertTrue(suite.valid)
        self.assertTrue(run.correctness.valid)
        self.assertEqual(run.counts.chunks, 3)
        self.assertEqual(run.counts.ffmpeg_process_launches, 3)
        self.assertGreater(run.data_volume.raw_rgb_bytes_received, 0)
        self.assertGreater(run.timings.ffmpeg_process_lifetime_seconds, 0.0)
        self.assertGreater(run.timings.python_filter_total_seconds, 0.0)
        self.assertIn("cases", payload)
        self.assertIn("valid", payload)


def _generate_fixture(ffmpeg_path: Path, output_path: Path) -> None:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=3:size=160x90:rate=10",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:duration=2:size=160x90:rate=10",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:duration=2.9:size=160x90:rate=10",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=4.1:size=160x90:rate=10",
        "-filter_complex",
        "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[fixture]",
        "-map",
        "[fixture]",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Unable to create FFmpeg integration fixture")


def _generate_vfr_fixture(ffmpeg_path: Path, output_path: Path) -> None:
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=1.5:size=160x90:rate=5",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=duration=1.5:size=160x90:rate=12",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0,settb=1/60000[vfr]",
        "-map",
        "[vfr]",
        "-fps_mode",
        "vfr",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        "-y",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Unable to create VFR integration fixture")


if __name__ == "__main__":
    unittest.main()
