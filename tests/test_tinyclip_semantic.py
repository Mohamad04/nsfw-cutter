from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import torch
from PIL import Image

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    SampleReason,
)
from services.analysis.representative_fanout import FinalizableRepresentativeFanout
from services.analysis.tinyclip_score_export import (
    TinyCLIPScoreArtifact,
    TinyCLIPScoreModel,
    TinyCLIPScorePrompt,
    TinyCLIPScorePromptBank,
    TinyCLIPScoreSample,
    TinyCLIPScoreValue,
    TinyCLIPScoreVideo,
    load_tinyclip_score_artifact,
)
from services.analysis.tinyclip_semantic import (
    MODEL_REQUIRED_FILES,
    MODEL_REVISION,
    ExperimentalPromptBank,
    ResolvedTinyCLIPArtifact,
    SemanticPrompt,
    TinyCLIPArtifactIntegrityError,
    TinyCLIPBatchConsumer,
    TinyCLIPFrameInput,
    TinyCLIPModelResolver,
    TinyCLIPRuntime,
    TinyCLIPSemanticClassifier,
    TinyCLIPTextFeatureCache,
)

PROMPT_BANK = ExperimentalPromptBank(
    bank_id="unit-bank",
    version="v1",
    prompts=(
        SemanticPrompt(concept_id="red", text="a red object"),
        SemanticPrompt(concept_id="green", text="a green object"),
        SemanticPrompt(concept_id="blue", text="a blue object"),
    ),
)


class _FakeProcessor:
    def __init__(self) -> None:
        self.tokenizer = SimpleNamespace()
        self.text_calls: list[dict] = []
        self.image_calls: list[list[Image.Image]] = []

    def __call__(self, *, text=None, images=None, **kwargs):
        if text is not None:
            self.text_calls.append({"text": list(text), **kwargs})
            width = min(77, max(len(item.split()) + 2 for item in text))
            return {
                "input_ids": torch.ones((len(text), width), dtype=torch.int64),
                "attention_mask": torch.ones((len(text), width), dtype=torch.int64),
            }
        self.image_calls.append(list(images))
        rows = []
        for image in images:
            pixel = torch.tensor(image.getpixel((0, 0)), dtype=torch.float32)
            rows.append(pixel[:, None, None].expand(3, 224, 224))
        return {"pixel_values": torch.stack(rows)}


class _FakeModel:
    def __init__(self) -> None:
        self.text_calls = 0
        self.image_calls = 0

    def get_text_features(self, *, input_ids, attention_mask=None):
        del input_ids, attention_mask
        self.text_calls += 1
        return torch.eye(3, dtype=torch.float32)

    def get_image_features(self, *, pixel_values):
        self.image_calls += 1
        return pixel_values[:, :, 0, 0]


class _StaticResolver:
    def __init__(self, artifact: ResolvedTinyCLIPArtifact) -> None:
        self.artifact = artifact
        self.calls = 0

    def resolve(self, *, local_files_only=False):
        del local_files_only
        self.calls += 1
        return self.artifact


class _StaticFactory:
    def __init__(self, runtime: TinyCLIPRuntime) -> None:
        self.runtime = runtime
        self.calls = 0

    def create(self, _artifact):
        self.calls += 1
        return self.runtime


def _runtime() -> tuple[TinyCLIPRuntime, _FakeProcessor, _FakeModel]:
    processor = _FakeProcessor()
    model = _FakeModel()
    return (
        TinyCLIPRuntime(
            torch=torch,
            processor=processor,
            model=model,
            torch_version=torch.__version__,
            transformers_version="test-transformers",
            device="cpu",
            dtype="float32",
            projection_dim=3,
            logit_scale_exp=10.0,
            processor_class="FakeProcessor",
            tokenizer_class="FakeTokenizer",
        ),
        processor,
        model,
    )


def _classifier(tmp_path: Path):
    runtime, processor, model = _runtime()
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"unit")
    artifact = ResolvedTinyCLIPArtifact(
        snapshot_dir=tmp_path,
        weights_path=weights,
        sha256="a" * 64,
        resolved_files=(weights,),
    )
    resolver = _StaticResolver(artifact)
    factory = _StaticFactory(runtime)
    classifier = TinyCLIPSemanticClassifier(
        artifact_resolver=resolver,
        runtime_factory=factory,
        text_feature_cache=TinyCLIPTextFeatureCache(),
    )
    return classifier, runtime, processor, model, resolver, factory


def _frame_input(index: int, *, color=(255, 0, 0)) -> TinyCLIPFrameInput:
    image = Image.new("RGB", (4, 4), (0, 0, 0))
    for y in range(1, 3):
        for x in range(1, 3):
            image.putpixel((x, y), color)
    return TinyCLIPFrameInput(
        sample_id=f"sample:{index}",
        source_timestamp_us=index * 1_000_000,
        rgb_bytes=image.tobytes(),
        width=4,
        height=4,
        content_rect=(1, 1, 2, 2),
    )


def _callback_frame(index: int) -> tuple[ExtractedFrame, FrameSample]:
    frame_input = _frame_input(index)
    reasons = frozenset({SampleReason.TEMPORAL_SAFETY})
    frame = ExtractedFrame(
        timestamp_us=frame_input.source_timestamp_us,
        source_pts=index,
        source_time_base="1/1000",
        processing_chunk_index=0,
        sample_reasons=reasons,
        width=frame_input.width,
        height=frame_input.height,
        content_rect=frame_input.content_rect,
        scene_score=None,
        rgb_bytes=frame_input.rgb_bytes,
    )
    sample = FrameSample(
        timestamp_us=frame.timestamp_us,
        source_pts=frame.source_pts,
        source_time_base=frame.source_time_base,
        owning_chunk_index=0,
        sample_reasons=reasons,
        width=frame.width,
        height=frame.height,
        content_rect=frame.content_rect,
        disposition=FrameDisposition.REPRESENTATIVE,
    )
    return frame, sample


def test_resolver_uses_only_pinned_files_and_validates_sha(tmp_path):
    payload = b"verified-safetensors"
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    calls = []
    for filename in MODEL_REQUIRED_FILES:
        (snapshot / filename).write_bytes(
            payload if filename == "model.safetensors" else b"{}"
        )

    def download(**kwargs):
        calls.append(kwargs)
        return str(snapshot / kwargs["filename"])

    with (
        patch("services.analysis.tinyclip_semantic.MODEL_WEIGHTS_SIZE", len(payload)),
        patch(
            "services.analysis.tinyclip_semantic.MODEL_WEIGHTS_SHA256",
            hashlib.sha256(payload).hexdigest(),
        ),
    ):
        artifact = TinyCLIPModelResolver(
            model_cache_dir=tmp_path / "cache",
            hub_download=download,
        ).resolve(local_files_only=True)

    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert [call["filename"] for call in calls] == list(MODEL_REQUIRED_FILES)
    assert all(call["revision"] == MODEL_REVISION for call in calls)
    assert all(call["local_files_only"] is True for call in calls)
    assert not any("pytorch_model.bin" in call["filename"] for call in calls)


def test_resolver_rejects_bad_sha_before_loading(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    for filename in MODEL_REQUIRED_FILES:
        (snapshot / filename).write_bytes(b"bad" if filename == "model.safetensors" else b"{}")

    def download(**kwargs):
        return str(snapshot / kwargs["filename"])

    with (
        patch("services.analysis.tinyclip_semantic.MODEL_WEIGHTS_SIZE", 3),
        patch("services.analysis.tinyclip_semantic.MODEL_WEIGHTS_SHA256", "0" * 64),
        pytest.raises(TinyCLIPArtifactIntegrityError),
    ):
        TinyCLIPModelResolver(hub_download=download).resolve()


def test_prompt_bank_digest_is_stable_and_order_sensitive():
    clone = ExperimentalPromptBank.model_validate(PROMPT_BANK.model_dump())
    reversed_bank = PROMPT_BANK.model_copy(
        update={"prompts": tuple(reversed(PROMPT_BANK.prompts))}
    )
    assert clone.digest == PROMPT_BANK.digest
    assert reversed_bank.digest != PROMPT_BANK.digest


def test_official_processor_receives_cropped_content_and_explicit_text_contract(tmp_path):
    classifier, _runtime_value, processor, _model, _resolver, _factory = _classifier(
        tmp_path
    )
    classifier.classify([_frame_input(0, color=(12, 34, 56))], PROMPT_BANK)

    assert processor.image_calls[0][0].size == (2, 2)
    assert processor.image_calls[0][0].getpixel((0, 0)) == (12, 34, 56)
    assert processor.text_calls[0]["padding"] is True
    assert processor.text_calls[0]["truncation"] is True
    assert processor.text_calls[0]["max_length"] == 77


def test_text_features_cached_l2_normalization_cosine_and_concept_order(tmp_path):
    classifier, runtime, _processor, model, resolver, factory = _classifier(tmp_path)
    first = classifier.classify([_frame_input(0, color=(3, 4, 0))], PROMPT_BANK)
    second = classifier.classify([_frame_input(1, color=(0, 0, 9))], PROMPT_BANK)

    assert model.text_calls == 1
    assert model.image_calls == 2
    assert resolver.calls == factory.calls == 1
    assert runtime.timing.text_embedding_calls == 1
    assert [score.concept_id for score in first[0].concept_scores] == [
        "red",
        "green",
        "blue",
    ]
    assert first[0].concept_scores[0].cosine_similarity == pytest.approx(0.6)
    assert first[0].concept_scores[1].cosine_similarity == pytest.approx(0.8)
    assert first[0].concept_scores[0].scaled_logit == pytest.approx(6.0)
    assert second[0].concept_scores[2].cosine_similarity == pytest.approx(1.0)
    payload = first[0].model_dump()
    assert "candidate" not in payload
    assert "threshold" not in payload
    assert "rgb_bytes" not in payload


def test_batch_consumer_preserves_order_and_flushes_partial_batch(tmp_path):
    classifier, _runtime_value, _processor, _model, _resolver, _factory = _classifier(
        tmp_path
    )
    consumer = TinyCLIPBatchConsumer(classifier, PROMPT_BANK, batch_size=2)
    token = CancellationToken()
    for index in range(3):
        consumer(*_callback_frame(index), token)
    consumer.flush(token)

    assert consumer.observed_batch_sizes == [2, 1]
    assert consumer.inference_calls == 2
    assert [result.source_timestamp_us for result in consumer.results] == [
        0,
        1_000_000,
        2_000_000,
    ]


def test_cancellation_is_observed_between_semantic_batches():
    token = CancellationToken()

    class CancellingClassifier:
        def classify(self, frames, _prompt_bank):
            token.cancel()
            return list(frames)

    consumer = TinyCLIPBatchConsumer(CancellingClassifier(), PROMPT_BANK, batch_size=1)
    with pytest.raises(AnalysisCancelled):
        consumer(*_callback_frame(0), token)
    assert consumer.inference_calls == 1


def test_fanout_passes_same_frame_and_isolates_failure():
    token = CancellationToken()
    received = []

    class Failing:
        def __call__(self, *_args):
            raise RuntimeError("semantic failed")

        def flush(self, _token):
            raise AssertionError("inactive consumer must not be flushed")

    class Healthy:
        def __call__(self, frame, _sample, _token):
            received.append(frame)

        def flush(self, _token):
            received.append("flushed")

    fanout = FinalizableRepresentativeFanout(
        [("tinyclip", Failing()), ("onnx-safety", Healthy())]
    )
    frame, sample = _callback_frame(0)
    fanout(frame, sample, token)
    fanout.flush(token)

    assert received == [frame, "flushed"]
    assert received[0] is frame
    assert len(fanout.failures) == 1
    assert fanout.failures[0].consumer_name == "tinyclip"
    assert fanout.is_active("onnx-safety") is True


def test_score_artifact_json_round_trip_without_pixels_or_thresholds(tmp_path):
    artifact = TinyCLIPScoreArtifact(
        generated_at_utc="2026-01-01T00:00:00Z",
        video=TinyCLIPScoreVideo(filename="movie.mp4", duration_us=10_000_000),
        model=TinyCLIPScoreModel(
            repo_id="repo",
            revision="revision",
            checkpoint_sha256="a" * 64,
            torch_version="test",
            transformers_version="test",
            device="cpu",
            dtype="float32",
            processor_class="CLIPProcessor",
            tokenizer_class="CLIPTokenizerFast",
            logit_scale_exp=10.0,
        ),
        prompt_bank=TinyCLIPScorePromptBank(
            bank_id="bank",
            version="v1",
            digest="b" * 64,
            prompts=(TinyCLIPScorePrompt(concept_id="weapon", text="a firearm"),),
        ),
        preprocessing={},
        samples=(
            TinyCLIPScoreSample(
                sample_id="sample:0",
                timestamp_us=0,
                sample_reasons=("temporal_safety",),
                scores=(
                    TinyCLIPScoreValue(
                        concept_id="weapon",
                        prompt_sha256="c" * 64,
                        cosine_similarity=0.2,
                        scaled_logit=2.0,
                    ),
                ),
            ),
        ),
    )
    path = tmp_path / "scores.json"
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    loaded = load_tinyclip_score_artifact(path)
    payload = loaded.model_dump_json()

    assert loaded == artifact
    assert "candidate" not in payload
    assert "semantic_threshold" not in payload
    assert "rgb_bytes" not in payload


@pytest.mark.tinyclip_model_integration
@pytest.mark.skipif(
    os.environ.get("NSFW_CUTTER_RUN_TINYCLIP_INTEGRATION_TESTS") != "1",
    reason="set NSFW_CUTTER_RUN_TINYCLIP_INTEGRATION_TESTS=1 to run",
)
def test_pinned_tinyclip_real_cpu_contract_and_ordering():
    classifier = TinyCLIPSemanticClassifier()
    frames = [
        _frame_input(0, color=(0, 0, 0)),
        _frame_input(1, color=(255, 255, 255)),
    ]
    results = classifier.classify(frames, PROMPT_BANK)
    runtime = classifier.runtime

    assert runtime is not None
    assert runtime.device == "cpu"
    assert runtime.projection_dim > 0
    assert runtime.logit_scale_exp > 0.0
    assert [result.sample_id for result in results] == ["sample:0", "sample:1"]
    assert all(len(result.concept_scores) == len(PROMPT_BANK.prompts) for result in results)
    assert all(
        score.cosine_similarity == pytest.approx(score.cosine_similarity)
        for result in results
        for score in result.concept_scores
    )
