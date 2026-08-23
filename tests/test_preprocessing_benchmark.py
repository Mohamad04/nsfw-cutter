import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from scripts.benchmark_preprocessing import (
    build_argument_parser,
    configurations_from_args,
    main,
)
from services.analysis.preprocessing_benchmark import (
    BenchmarkCaseResult,
    BenchmarkConfiguration,
    BenchmarkCorrectness,
    BenchmarkCounts,
    BenchmarkDataVolume,
    BenchmarkInvariantCheck,
    BenchmarkResourceMetrics,
    BenchmarkRunResult,
    BenchmarkSourceInfo,
    BenchmarkStageTimings,
    BenchmarkSuiteResult,
    aggregate_benchmark_runs,
    calculate_performance_rates,
    run_benchmark_suite,
    summarize_wall_times,
    verify_preprocessing_result,
)
from services.analysis.preprocessing_contracts import (
    PreprocessingConfig,
    PreprocessingResult,
    PreprocessingStatistics,
    ProcessingChunk,
)
from services.analysis.preprocessing_instrumentation import InstrumentationSnapshot


class BenchmarkArgumentTests(unittest.TestCase):
    def test_cli_parses_sampling_and_chunk_matrices(self):
        parser = build_argument_parser()
        args = parser.parse_args(
            [
                "--video",
                "movie.mkv",
                "--sampling-gap-matrix",
                "1.0",
                "1.5",
                "2.0",
                "--chunk-duration-matrix",
                "120",
                "240",
                "--chunk-overlap",
                "2",
                "--target-width",
                "320",
                "--target-height",
                "192",
                "--runs",
                "3",
            ]
        )

        configurations = configurations_from_args(args)

        self.assertEqual(args.runs, 3)
        self.assertEqual(len(configurations), 6)
        self.assertEqual(
            [
                (config.max_sampling_gap_seconds, config.chunk_duration_seconds)
                for config in configurations
            ],
            [
                (1.0, 120.0),
                (1.0, 240.0),
                (1.5, 120.0),
                (1.5, 240.0),
                (2.0, 120.0),
                (2.0, 240.0),
            ],
        )
        self.assertTrue(
            all(
                config.target_width == 320 and config.target_height == 192
                for config in configurations
            )
        )

    def test_invalid_movie_path_fails_before_ffmpeg_resolution(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing.mkv"
            with self.assertRaisesRegex(FileNotFoundError, "Video does not exist"):
                run_benchmark_suite(
                    missing_path,
                    [PreprocessingConfig()],
                    monitor_resources=False,
                )

    def test_cli_returns_nonzero_for_invalid_movie_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing.mp4"
            error_output = io.StringIO()
            with redirect_stderr(error_output):
                return_code = main(["--video", str(missing_path)])

        self.assertEqual(return_code, 2)
        self.assertIn("Video does not exist", error_output.getvalue())

    def test_json_output_cannot_overwrite_source_video(self):
        source_path = Path("movie.mp4")
        error_output = io.StringIO()
        with redirect_stderr(error_output):
            return_code = main(
                [
                    "--video",
                    str(source_path),
                    "--json-output",
                    str(source_path),
                ]
            )

        self.assertEqual(return_code, 2)
        self.assertIn("must not overwrite", error_output.getvalue())


class BenchmarkCalculationTests(unittest.TestCase):
    def test_throughput_and_realtime_factor(self):
        throughput, realtime_factor = calculate_performance_rates(120.0, 10.0)

        self.assertEqual(throughput, 12.0)
        self.assertAlmostEqual(realtime_factor, 0.0833333333)

    def test_wall_time_summary_uses_median_minimum_and_maximum(self):
        median, minimum, maximum = summarize_wall_times([8.0, 3.0, 5.0])

        self.assertEqual(median, 5.0)
        self.assertEqual(minimum, 3.0)
        self.assertEqual(maximum, 8.0)

    def test_repeated_run_aggregate_excludes_invalid_runs(self):
        runs = (
            _benchmark_run(3.0),
            _benchmark_run(1.0),
            _benchmark_run(9.0, valid=False),
        )

        aggregate = aggregate_benchmark_runs(runs)

        self.assertEqual(aggregate.valid_runs, 2)
        self.assertEqual(aggregate.invalid_runs, 1)
        self.assertEqual(aggregate.median_wall_seconds, 2.0)
        self.assertEqual(aggregate.minimum_wall_seconds, 1.0)
        self.assertEqual(aggregate.maximum_wall_seconds, 3.0)

    def test_json_result_has_versioned_nested_measurements(self):
        run = _benchmark_run(2.0)
        case = BenchmarkCaseResult(
            configuration=run.configuration,
            runs=(run,),
            aggregate=aggregate_benchmark_runs((run,)),
        )
        suite = BenchmarkSuiteResult(
            generated_at_utc="2026-08-18T00:00:00+00:00",
            video_path="movie.mkv",
            cases=(case,),
            notes=("test",),
        )

        payload = json.loads(suite.model_dump_json())

        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["valid"])
        self.assertIn("source", payload["cases"][0]["runs"][0])
        self.assertIn("timings", payload["cases"][0]["runs"][0])
        self.assertIn("data_volume", payload["cases"][0]["runs"][0])
        self.assertIn("correctness", payload["cases"][0]["runs"][0])


class BenchmarkInvariantTests(unittest.TestCase):
    def test_invariant_failures_mark_run_invalid(self):
        config = PreprocessingConfig(
            chunk_duration_seconds=1.0,
            chunk_overlap_seconds=0.0,
            max_sampling_gap_seconds=0.5,
        )
        result = PreprocessingResult(
            config=config,
            chunks=(
                ProcessingChunk(
                    index=0,
                    core_start_us=0,
                    core_end_us=1_000_000,
                    decode_start_us=0,
                    decode_end_us=1_000_000,
                ),
            ),
            representative_frames=(),
            statistics=PreprocessingStatistics(
                movie_duration_us=1_000_000,
                preprocessing_wall_seconds=0.1,
                chunks_processed=1,
                temporal_samples=0,
                scene_samples=0,
                samples_considered=0,
                black_frames_removed=0,
                duplicates_removed=0,
                static_frames_suppressed=0,
                representative_frames=0,
                media_throughput=10.0,
            ),
        )
        snapshot = InstrumentationSnapshot(
            durations={},
            counters={},
            peaks={},
            observations=(),
        )

        verification = verify_preprocessing_result(result, snapshot)
        failures = {check.name for check in verification.checks if not check.passed}

        self.assertFalse(verification.valid)
        self.assertIn("maximum_temporal_safety_gap", failures)
        self.assertIn("representatives_nonzero_and_consistent", failures)


def _benchmark_run(wall_seconds: float, *, valid: bool = True) -> BenchmarkRunResult:
    source = BenchmarkSourceInfo(
        filename="movie.mkv",
        path="movie.mkv",
        container="matroska,webm",
        duration_seconds=12.0,
        selected_video_stream_index=0,
        codec="h264",
        width=1920,
        height=1080,
        display_aspect_ratio="16:9",
        nominal_fps=24.0,
        frame_rate_mode="likely_cfr",
        frame_rate_evidence="test",
    )
    configuration = BenchmarkConfiguration(
        sampling_gap_seconds=1.0,
        chunk_duration_seconds=240.0,
        chunk_overlap_seconds=2.0,
        target_width=384,
        target_height=384,
        selected_video_stream_index=0,
        scene_threshold=0.35,
        black_pixel_luma_threshold=12,
        black_frame_ratio_threshold=0.995,
        black_mean_luma_threshold=8.0,
        perceptual_hash_algorithm="dhash-spatial-64",
        perceptual_hash_version=1,
        duplicate_hamming_threshold=3,
        static_suppression_limit_seconds=10.0,
    )
    timings = BenchmarkStageTimings(
        media_probe_seconds=0.01,
        process_popen_seconds=0.01,
        startup_seek_to_first_rgb_seconds=0.02,
        ffmpeg_process_lifetime_seconds=wall_seconds,
        frame_stream_wait_seconds=0.1,
        frame_assembly_seconds=0.01,
        python_frame_preparation_seconds=0.01,
        black_filtering_seconds=0.01,
        perceptual_hashing_seconds=0.01,
        duplicate_static_reduction_seconds=0.01,
        result_materialization_seconds=0.01,
        python_filter_total_seconds=0.05,
        chunk_merge_finalization_seconds=0.01,
        total_preprocessing_wall_seconds=wall_seconds,
        correctness_verification_seconds=0.001,
        measurement_notes=(),
    )
    correctness = BenchmarkCorrectness(
        valid=valid,
        checks=(
            BenchmarkInvariantCheck(name="synthetic", passed=valid, detail="test"),
        ),
    )
    return BenchmarkRunResult(
        run_index=1,
        source=source,
        configuration=configuration,
        timings=timings,
        media_throughput=12.0 / wall_seconds,
        realtime_factor=wall_seconds / 12.0,
        counts=BenchmarkCounts(
            chunks=1,
            ffmpeg_process_launches=1,
            temporal_samples=1,
            scene_samples=0,
            union_samples=1,
            overlap_context_samples_discarded=0,
            black_frames_removed=0,
            near_duplicates_removed=0,
            static_frames_suppressed=0,
            representatives_retained=1,
        ),
        data_volume=BenchmarkDataVolume(
            raw_rgb_bytes_received=1,
            approximate_python_rgb_bytes_processed=1,
            peak_stdout_queue_bytes=1,
            peak_stdout_queue_items=1,
        ),
        resources=BenchmarkResourceMetrics(
            monitoring_available=False,
            unavailable_reason="test",
            samples=0,
            measurement_note="test",
        ),
        correctness=correctness,
    )


if __name__ == "__main__":
    unittest.main()
