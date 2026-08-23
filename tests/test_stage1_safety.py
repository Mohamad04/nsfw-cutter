from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from services.analysis.cancellation import CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing import MoviePreprocessingService
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    PreprocessingConfig,
    SampleReason,
)
from services.analysis.stage1_safety import (
    CPU_EXECUTION_PROVIDER,
    INPUT_NAME,
    MODEL_SHA256,
    OUTPUT_NAME,
    ONNXSafetySessionFactory,
    ResolvedSafetyModelArtifact,
    SafetyImageAdapter,
    SafetyInferenceError,
    SafetyModelArtifactIntegrityError,
    SafetyModelArtifactResolver,
    SafetyModelArtifactUnavailableError,
    SafetyModelContractError,
    Stage1BatchConsumer,
    Stage1FrameInput,
    Stage1RepresentativeConsumer,
    Stage1SafetyClassifier,
    _SafetySession,
)


@dataclass
class _NodeArg:
    name: str
    type: str
    shape: list[object]


class _FakeSession:
    def __init__(
        self,
        *,
        inputs=None,
        outputs=None,
        providers=(CPU_EXECUTION_PROVIDER,),
        probabilities=None,
        run_error: Exception | None = None,
    ):
        self.inputs = inputs or [_NodeArg(INPUT_NAME, "tensor(float)", ["batch", 3, 224, 224])]
        self.outputs = outputs or [_NodeArg(OUTPUT_NAME, "tensor(float)", ["batch", 3])]
        self.providers = list(providers)
        self.probabilities = probabilities
        self.run_error = run_error
        self.calls = []

    def get_inputs(self):
        return self.inputs

    def get_outputs(self):
        return self.outputs

    def get_providers(self):
        return self.providers

    def run(self, output_names, input_feed):
        self.calls.append((output_names, input_feed))
        if self.run_error is not None:
            raise self.run_error
        return [self.probabilities]


class _FakeOrt:
    __version__ = "test-ort"

    def __init__(self, session):
        self.session = session
        self.calls = []

    def InferenceSession(self, path, *, providers):
        self.calls.append((path, providers))
        return self.session


class _StaticArtifactResolver:
    def __init__(self, artifact):
        self.artifact = artifact
        self.calls = 0

    def resolve(self):
        self.calls += 1
        return self.artifact


class _StaticSessionFactory:
    def __init__(self, session):
        self.session = session
        self.calls = 0

    def create(self, _artifact):
        self.calls += 1
        return _SafetySession(
            session=self.session,
            onnxruntime_version="test-ort",
            execution_providers=(CPU_EXECUTION_PROVIDER,),
        )


def _frame_input(
    sample_id="sample-1",
    *,
    color=(255, 0, 0),
    width=4,
    height=4,
    content_rect=None,
) -> Stage1FrameInput:
    image = Image.new("RGB", (width, height), color=color)
    return Stage1FrameInput(
        sample_id=sample_id,
        source_timestamp_us=123,
        rgb_bytes=image.tobytes(),
        width=width,
        height=height,
        content_rect=content_rect or (0, 0, width, height),
    )


def _extracted_frame(timestamp_us: int, color: tuple[int, int, int]) -> ExtractedFrame:
    return ExtractedFrame(
        timestamp_us=timestamp_us,
        source_pts=timestamp_us,
        source_time_base="1/1000000",
        processing_chunk_index=0,
        sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
        width=4,
        height=4,
        content_rect=(0, 0, 4, 4),
        scene_score=None,
        rgb_bytes=Image.new("RGB", (4, 4), color).tobytes(),
    )


def _representative_sample(frame: ExtractedFrame) -> FrameSample:
    return FrameSample(
        timestamp_us=frame.timestamp_us,
        source_pts=frame.source_pts,
        source_time_base=frame.source_time_base,
        owning_chunk_index=0,
        sample_reasons=frame.sample_reasons,
        width=frame.width,
        height=frame.height,
        content_rect=frame.content_rect,
        disposition=FrameDisposition.REPRESENTATIVE,
    )


class _RecordingBatchClassifier:
    def __init__(self):
        self.calls: list[list[Stage1FrameInput]] = []

    def classify(self, frames):
        ordered = list(frames)
        self.calls.append(ordered)
        return [SimpleNamespace(sample_id=frame.sample_id) for frame in ordered]


class ONNXSafetySessionFactoryTests(unittest.TestCase):
    def setUp(self):
        self.artifact = ResolvedSafetyModelArtifact(Path("model.onnx"), MODEL_SHA256)

    def test_cpu_provider_is_explicitly_requested(self):
        session = _FakeSession()
        ort = _FakeOrt(session)

        created = ONNXSafetySessionFactory(ort).create(self.artifact)

        self.assertEqual(ort.calls, [("model.onnx", [CPU_EXECUTION_PROVIDER])])
        self.assertEqual(created.execution_providers, (CPU_EXECUTION_PROVIDER,))

    def test_input_name_mismatch_is_rejected(self):
        session = _FakeSession(inputs=[_NodeArg("pixels", "tensor(float)", ["B", 3, 224, 224])])
        with self.assertRaises(SafetyModelContractError):
            ONNXSafetySessionFactory(_FakeOrt(session)).create(self.artifact)

    def test_input_type_rank_and_spatial_contract_are_rejected(self):
        bad_inputs = (
            _NodeArg(INPUT_NAME, "tensor(uint8)", ["B", 3, 224, 224]),
            _NodeArg(INPUT_NAME, "tensor(float)", ["B", 3, 224]),
            _NodeArg(INPUT_NAME, "tensor(float)", ["B", 3, 384, 384]),
        )
        for input_arg in bad_inputs:
            with self.subTest(input_arg=input_arg), self.assertRaises(SafetyModelContractError):
                ONNXSafetySessionFactory(
                    _FakeOrt(_FakeSession(inputs=[input_arg]))
                ).create(self.artifact)

    def test_output_name_and_three_class_contract_are_rejected(self):
        bad_outputs = (
            _NodeArg("scores", "tensor(float)", ["B", 3]),
            _NodeArg(OUTPUT_NAME, "tensor(float)", ["B", 2]),
        )
        for output_arg in bad_outputs:
            with self.subTest(output_arg=output_arg), self.assertRaises(SafetyModelContractError):
                ONNXSafetySessionFactory(
                    _FakeOrt(_FakeSession(outputs=[output_arg]))
                ).create(self.artifact)


class SafetyImageAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = SafetyImageAdapter()

    def test_rgb_order_dtype_shape_range_and_hwc_to_chw(self):
        tensor = self.adapter.prepare_batch([_frame_input(color=(12, 34, 56))])

        self.assertEqual(tensor.shape, (1, 3, 224, 224))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual(tensor[0, :, 0, 0].tolist(), [12.0, 34.0, 56.0])
        self.assertEqual(float(tensor.min()), 12.0)
        self.assertEqual(float(tensor.max()), 56.0)

    def test_content_rect_removes_black_padding_before_resize(self):
        image = Image.new("RGB", (4, 4), "black")
        for x in range(4):
            for y in (1, 2):
                image.putpixel((x, y), (255, 255, 255))
        frame = Stage1FrameInput(
            sample_id="cropped",
            source_timestamp_us=0,
            rgb_bytes=image.tobytes(),
            width=4,
            height=4,
            content_rect=(0, 1, 4, 2),
        )

        tensor = self.adapter.prepare_batch([frame])

        self.assertEqual(tensor.shape, (1, 3, 224, 224))
        self.assertTrue(np.all(tensor == 255.0))

    def test_batch_input_order_is_preserved(self):
        tensor = self.adapter.prepare_batch(
            [_frame_input("red", color=(255, 0, 0)), _frame_input("blue", color=(0, 0, 255))]
        )

        self.assertEqual(tensor[0, :, 0, 0].tolist(), [255.0, 0.0, 0.0])
        self.assertEqual(tensor[1, :, 0, 0].tolist(), [0.0, 0.0, 255.0])


class SafetyModelArtifactResolverTests(unittest.TestCase):
    def test_sha256_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "model.onnx"
            artifact_path.write_bytes(b"pinned artifact")
            expected = hashlib.sha256(b"pinned artifact").hexdigest()
            resolver = SafetyModelArtifactResolver(
                model_cache_dir=directory,
                hub_download=lambda **_kwargs: str(artifact_path),
            )

            with patch("services.analysis.stage1_safety.MODEL_SHA256", expected):
                artifact = resolver.resolve()

        self.assertEqual(artifact.path, artifact_path)
        self.assertEqual(artifact.sha256, expected)

    def test_bad_sha_raises_integrity_error(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "model.onnx"
            artifact_path.write_bytes(b"wrong artifact")
            resolver = SafetyModelArtifactResolver(
                model_cache_dir=directory,
                hub_download=lambda **_kwargs: str(artifact_path),
            )

            with self.assertRaises(SafetyModelArtifactIntegrityError):
                resolver.resolve()

    def test_download_failure_is_actionable(self):
        resolver = SafetyModelArtifactResolver(
            model_cache_dir="model-cache",
            hub_download=lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")),
        )

        with self.assertRaises(SafetyModelArtifactUnavailableError):
            resolver.resolve()


class Stage1SafetyClassifierTests(unittest.TestCase):
    def _classifier(self, probabilities, *, run_error=None):
        artifact = ResolvedSafetyModelArtifact(Path("model.onnx"), MODEL_SHA256)
        session = _FakeSession(probabilities=probabilities, run_error=run_error)
        return Stage1SafetyClassifier(
            artifact_resolver=_StaticArtifactResolver(artifact),
            session_factory=_StaticSessionFactory(session),
        ), session

    def test_batch_results_preserve_order_and_label_mapping(self):
        classifier, session = self._classifier(
            np.array([[0.8, 0.1, 0.1], [0.1, 0.7, 0.2]], dtype=np.float32)
        )

        results = classifier.classify([_frame_input("first"), _frame_input("second")])

        self.assertEqual([result.sample_id for result in results], ["first", "second"])
        self.assertEqual([result.selected_label for result in results], ["NSFL", "NSFW"])
        self.assertEqual(results[0].execution_providers, (CPU_EXECUTION_PROVIDER,))
        self.assertEqual(session.calls[0][0], [OUTPUT_NAME])
        self.assertEqual(session.calls[0][1][INPUT_NAME].shape, (2, 3, 224, 224))

    def test_output_count_and_probability_sanity_are_required(self):
        invalid_outputs = (
            np.array([[0.5, 0.5]], dtype=np.float32),
            np.array([[1.1, 0.0, -0.1]], dtype=np.float32),
            np.array([[0.5, 0.25, 0.1]], dtype=np.float32),
            np.array([[np.nan, 0.0, 1.0]], dtype=np.float32),
        )
        for output in invalid_outputs:
            with self.subTest(output=output):
                classifier, _session = self._classifier(output)
                with self.assertRaises(SafetyInferenceError):
                    classifier.classify([_frame_input()])

    def test_inference_failure_never_becomes_sfw(self):
        classifier, _session = self._classifier(None, run_error=RuntimeError("boom"))

        with self.assertRaises(SafetyInferenceError):
            classifier.classify([_frame_input()])


class Stage1RepresentativeConsumerTests(unittest.TestCase):
    def test_batch_consumer_uses_full_batches_and_flushes_final_partial_batch(self):
        classifier = _RecordingBatchClassifier()
        consumer = Stage1BatchConsumer(classifier, batch_size=2)
        token = CancellationToken()

        for index, color in enumerate(
            ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255))
        ):
            frame = _extracted_frame(index, color)
            consumer(frame, _representative_sample(frame), token)

        self.assertEqual([len(call) for call in classifier.calls], [2, 2])
        self.assertEqual(consumer.pending_count, 1)

        consumer.flush(token)

        self.assertEqual([len(call) for call in classifier.calls], [2, 2, 1])
        self.assertEqual(consumer.observed_batch_sizes, [2, 2, 1])
        self.assertEqual(consumer.inference_calls, 3)
        self.assertEqual(consumer.pending_count, 0)
        self.assertEqual(
            [result.sample_id for result in consumer.results],
            [
                "representative:0:0:0",
                "representative:0:1:1",
                "representative:0:2:2",
                "representative:0:3:3",
                "representative:0:4:4",
            ],
        )

    def test_batch_size_is_explicit_and_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            Stage1BatchConsumer(_RecordingBatchClassifier(), batch_size=0)

    def test_consumer_uses_only_the_accepted_representative_frame(self):
        frame = ExtractedFrame(
            timestamp_us=10,
            source_pts=5,
            source_time_base="1/1000000",
            processing_chunk_index=0,
            sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
            width=2,
            height=2,
            content_rect=(0, 0, 2, 2),
            scene_score=None,
            rgb_bytes=Image.new("RGB", (2, 2), "red").tobytes(),
        )
        sample = FrameSample(
            timestamp_us=10,
            source_pts=5,
            source_time_base="1/1000000",
            owning_chunk_index=0,
            sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
            width=2,
            height=2,
            content_rect=(0, 0, 2, 2),
            disposition=FrameDisposition.REPRESENTATIVE,
        )
        classifier, _session = Stage1SafetyClassifierTests()._classifier(
            np.array([[0.1, 0.2, 0.7]], dtype=np.float32)
        )
        consumer = Stage1RepresentativeConsumer(classifier)

        consumer(frame, sample, CancellationToken())

        self.assertEqual(len(consumer.results), 1)
        self.assertEqual(consumer.results[0].source_timestamp_us, 10)
        self.assertEqual(consumer.results[0].selected_label, "SFW")

    def test_preprocessing_callback_runs_only_after_representative_acceptance(self):
        frame = ExtractedFrame(
            timestamp_us=0,
            source_pts=0,
            source_time_base="1/1000000",
            processing_chunk_index=0,
            sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
            width=4,
            height=4,
            content_rect=(0, 0, 4, 4),
            scene_score=None,
            rgb_bytes=Image.new("RGB", (4, 4), "red").tobytes(),
        )
        received = []
        service = MoviePreprocessingService(
            media_probe_service=SimpleNamespace(
                probe=lambda _video_path: SimpleNamespace(
                    duration_seconds=1.0,
                    video_streams=[SimpleNamespace(index=0)],
                )
            ),
            frame_extractor=SimpleNamespace(
                extract=lambda *_args: iter((frame,)),
            ),
        )

        result = service.preprocess(
            "video.mp4",
            config=PreprocessingConfig(target_width=4, target_height=4),
            representative_callback=lambda raw, sample, _token: received.append((raw, sample)),
        )

        self.assertEqual(result.statistics.representative_frames, 1)
        self.assertEqual(received, [(frame, result.representative_frames[0])])

    def test_preprocessing_flushes_a_batch_consumer_at_end_of_stream(self):
        frame = _extracted_frame(0, (255, 0, 0))
        classifier = _RecordingBatchClassifier()
        consumer = Stage1BatchConsumer(classifier, batch_size=4)
        service = MoviePreprocessingService(
            media_probe_service=SimpleNamespace(
                probe=lambda _video_path: SimpleNamespace(
                    duration_seconds=1.0,
                    video_streams=[SimpleNamespace(index=0)],
                )
            ),
            frame_extractor=SimpleNamespace(extract=lambda *_args: iter((frame,))),
        )

        result = service.preprocess(
            "video.mp4",
            config=PreprocessingConfig(target_width=4, target_height=4),
            representative_callback=consumer,
        )

        self.assertEqual(result.statistics.representative_frames, 1)
        self.assertEqual([len(call) for call in classifier.calls], [1])
        self.assertEqual(consumer.observed_batch_sizes, [1])


@pytest.mark.model_integration
@unittest.skipUnless(
    os.environ.get("NSFW_CUTTER_RUN_MODEL_INTEGRATION_TESTS") == "1",
    "set NSFW_CUTTER_RUN_MODEL_INTEGRATION_TESTS=1 to run the pinned ONNX model",
)
class RealStage1ModelIntegrationTests(unittest.TestCase):
    def test_pinned_model_runs_on_cpu(self):
        frames = [
            _frame_input("black", color=(0, 0, 0)),
            _frame_input("white", color=(255, 255, 255)),
        ]
        artifact = SafetyModelArtifactResolver().resolve()
        safety_session = ONNXSafetySessionFactory().create(artifact)
        input_tensor = SafetyImageAdapter().prepare_batch(frames)
        probabilities = safety_session.session.run(
            [OUTPUT_NAME],
            {INPUT_NAME: input_tensor},
        )[0]

        self.assertEqual(artifact.sha256, MODEL_SHA256)
        self.assertEqual(safety_session.execution_providers, (CPU_EXECUTION_PROVIDER,))
        self.assertEqual(input_tensor.shape, (2, 3, 224, 224))
        self.assertEqual(probabilities.shape, (2, 3))
        self.assertEqual(probabilities.dtype, np.float32)
        self.assertTrue(np.isfinite(probabilities).all())
        self.assertTrue(np.all((0.0 <= probabilities) & (probabilities <= 1.0)))
        self.assertTrue(np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5))

        results = Stage1SafetyClassifier().classify(frames)

        self.assertEqual(len(results), len(frames))
        self.assertTrue(
            all(
                result.execution_providers == (CPU_EXECUTION_PROVIDER,)
                for result in results
            )
        )


if __name__ == "__main__":
    unittest.main()
