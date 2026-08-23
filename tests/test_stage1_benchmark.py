from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from scripts.benchmark_stage1 import _print_result, build_argument_parser
from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    SampleReason,
)
from services.analysis.stage1_benchmark import run_stage1_throughput_benchmark
from services.analysis.stage1_safety import (
    CPU_EXECUTION_PROVIDER,
    INPUT_NAME,
    MODEL_SHA256,
    SafetyONNXSession,
)


class _ArtifactResolver:
    def __init__(self, path: Path):
        self.artifact = SimpleNamespace(path=path, sha256=MODEL_SHA256)
        self.local_files_only_values: list[bool] = []

    def resolve(self, *, local_files_only: bool = False):
        self.local_files_only_values.append(local_files_only)
        return self.artifact


class _RuntimeSession:
    def __init__(self):
        self.batch_sizes: list[int] = []

    def run(self, output_names, input_feed):
        self.assert_contract(output_names, input_feed)
        batch_size = input_feed[INPUT_NAME].shape[0]
        self.batch_sizes.append(batch_size)
        return [
            np.tile(
                np.array([[0.1, 0.2, 0.7]], dtype=np.float32),
                (batch_size, 1),
            )
        ]

    @staticmethod
    def assert_contract(output_names, input_feed):
        if output_names != ["probabilities"] or set(input_feed) != {INPUT_NAME}:
            raise AssertionError("unexpected ONNX call contract")


class _SessionFactory:
    def __init__(self):
        self.sessions: list[SafetyONNXSession] = []

    def create(self, _artifact):
        session = SafetyONNXSession(
            session=_RuntimeSession(),
            onnxruntime_version="test-ort",
            execution_providers=(CPU_EXECUTION_PROVIDER,),
        )
        self.sessions.append(session)
        return session


class _PreprocessingService:
    def preprocess(self, _video_path, *, config, representative_callback):
        del config
        token = CancellationToken()
        samples = []
        colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255))
        for index, color in enumerate(colors):
            image = Image.new("RGB", (4, 4), color)
            frame = ExtractedFrame(
                timestamp_us=index,
                source_pts=index,
                source_time_base="1/1000000",
                processing_chunk_index=0,
                sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
                width=4,
                height=4,
                content_rect=(0, 0, 4, 4),
                scene_score=None,
                rgb_bytes=image.tobytes(),
            )
            sample = FrameSample(
                timestamp_us=index,
                source_pts=index,
                source_time_base="1/1000000",
                owning_chunk_index=0,
                sample_reasons=frame.sample_reasons,
                width=4,
                height=4,
                content_rect=(0, 0, 4, 4),
                disposition=FrameDisposition.REPRESENTATIVE,
            )
            samples.append(sample)
            representative_callback(frame, sample, token)
        representative_callback.flush(token)
        return SimpleNamespace(
            representative_frames=tuple(samples),
            statistics=SimpleNamespace(movie_duration_seconds=10.0),
        )


class Stage1BenchmarkTests(unittest.TestCase):
    def test_benchmark_measures_true_batch_calls_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "input.mp4"
            video_path.write_bytes(b"test fixture placeholder")
            resolver = _ArtifactResolver(Path(directory) / "model.onnx")
            factory = _SessionFactory()

            result = run_stage1_throughput_benchmark(
                video_path,
                [2],
                isolated_iterations=3,
                warmup_runs=1,
                monitor_memory=False,
                local_files_only=True,
                artifact_resolver=resolver,
                session_factory=factory,
                preprocessing_service_factory=_PreprocessingService,
            )

        isolated = result.isolated_inference[0]
        combined = result.preprocessing_plus_stage1[0]
        self.assertEqual(resolver.local_files_only_values, [True])
        self.assertEqual(isolated.frames_measured, 6)
        self.assertGreater(isolated.frames_per_onnx_second, 0.0)
        self.assertEqual(combined.observed_batch_sizes, (2, 2, 1))
        self.assertEqual(combined.onnx_inference_calls, 3)
        self.assertEqual(combined.inference_batch_count, 3)
        self.assertEqual(combined.full_batch_count, 2)
        self.assertEqual(combined.partial_batch_count, 1)
        self.assertAlmostEqual(combined.average_batch_occupancy, 5 / 6)
        self.assertEqual(combined.final_batch_size, 1)
        serialized_case = combined.model_dump()
        self.assertNotIn("observed_batch_sizes", serialized_case)
        self.assertEqual(serialized_case["inference_batch_count"], 3)
        self.assertEqual(serialized_case["full_batch_count"], 2)
        self.assertEqual(serialized_case["partial_batch_count"], 1)
        self.assertEqual(combined.representatives_classified, 5)
        self.assertTrue(combined.result_count_matches_representatives)
        self.assertTrue(combined.input_order_preserved)
        self.assertTrue(result.valid)
        self.assertEqual(factory.sessions[0].session.batch_sizes, [2, 2, 2, 2])
        self.assertEqual(factory.sessions[1].session.batch_sizes, [1, 2, 2, 1])

        output = StringIO()
        with redirect_stdout(output):
            _print_result(result)
        printed = output.getvalue()
        self.assertNotIn("batches=[", printed)
        self.assertIn("batches=3", printed)
        self.assertIn("full=2", printed)
        self.assertIn("partial=1", printed)
        self.assertIn("final=1", printed)

    def test_batch_matrix_is_required_and_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "input.mp4"
            video_path.write_bytes(b"fixture")
            for batch_sizes in ([], [0]):
                with self.subTest(batch_sizes=batch_sizes), self.assertRaises(ValueError):
                    run_stage1_throughput_benchmark(
                        video_path,
                        batch_sizes,
                        artifact_resolver=_ArtifactResolver(Path("model.onnx")),
                        session_factory=_SessionFactory(),
                        preprocessing_service_factory=_PreprocessingService,
                    )

    def test_cli_requires_an_explicit_batch_size_matrix(self):
        parser = build_argument_parser()

        args = parser.parse_args(
            ["--video", "movie.mp4", "--batch-sizes", "1", "4", "8"]
        )

        self.assertEqual(args.batch_sizes, [1, 4, 8])


if __name__ == "__main__":
    unittest.main()
