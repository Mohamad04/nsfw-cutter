from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    CandidateSample,
    ClusteringConfiguration,
    ExperimentalCandidateEventsArtifact,
    ExperimentalCandidatePolicy,
    SelectedEventFrame,
)
from services.analysis.smolvlm_prompt_ablation import (
    CATEGORY_IDS,
    PROMPT_VARIANTS,
    CategoryEvidenceMap,
    EvidenceMapPayload,
    PromptVariantId,
    build_evidence_map_conversation,
    evaluate_prompt_ablation,
    output_collapse_diagnostics,
    parse_evidence_map_json,
)
from services.analysis.smolvlm_quality_evaluation import (
    CachedSelectedFrame,
    SelectedFrameCacheManifest,
)
from services.analysis.smolvlm_verifier import (
    EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    RawSmolVLMGeneration,
    SmolVLMRuntimeProvenance,
    VLMFrameDescriptor,
    VLMVerificationRequestMetadata,
)
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    GroundTruthVideo,
)


def test_evidence_schema_has_no_model_generated_unsafe_field() -> None:
    assert tuple(EvidenceMapPayload.model_fields) == ("category_evidence",)
    assert "unsafe" not in CategoryEvidenceMap.model_fields


def test_empty_evidence_derives_safe_and_nonempty_derives_unsafe() -> None:
    empty = _payload()
    detected = _payload(weapons=(2,))

    assert empty.derived_categories == ()
    assert empty.derived_unsafe is False
    assert detected.derived_categories == ("weapons",)
    assert detected.derived_unsafe is True


def test_multiple_categories_preserve_contract_order() -> None:
    payload = _payload(violence=(1,), weapons=(2,), drugs=(3,))
    assert payload.derived_categories == ("violence", "weapons", "drugs")


def test_duplicate_evidence_index_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _payload(weapons=(1, 1))


def test_out_of_range_frame_index_is_rejected() -> None:
    raw = _payload(weapons=(3,)).model_dump_json()
    with pytest.raises(ValueError, match="unavailable"):
        parse_evidence_map_json(raw, frame_count=2)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload["category_evidence"].update({"unknown": []}),
        lambda payload: payload.update({"extra": "forbidden"}),
    ),
)
def test_unknown_category_and_extra_field_are_rejected(mutation) -> None:
    payload = _payload().model_dump(mode="json")
    mutation(payload)
    with pytest.raises(ValidationError, match="Extra inputs"):
        parse_evidence_map_json(json.dumps(payload), frame_count=2)


def test_all_prompts_have_frames_and_no_filled_safe_example() -> None:
    metadata = VLMVerificationRequestMetadata(
        event_id="event:1",
        frames=(
            VLMFrameDescriptor(frame_index=1, timestamp_us=1),
            VLMFrameDescriptor(frame_index=2, timestamp_us=2),
        ),
        policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY,
    )
    for definition in PROMPT_VARIANTS:
        conversation = build_evidence_map_conversation(metadata, definition)
        text = " ".join(
            item.get("text", "") for item in conversation[0]["content"]
        )
        compact = text.replace(" ", "").casefold()
        assert "Frame 1" in text and "Frame 2" in text
        assert '"unsafe":false' not in compact
        assert "brief visible evidence" not in text
        assert "severity" not in text.casefold()
        assert "reason" not in text.casefold()


def test_output_collapse_diagnostics_normalize_json_key_order() -> None:
    values = ('{"a":1,"b":2}', '{ "b": 2, "a": 1 }', '{"a":9}')
    metrics = output_collapse_diagnostics(values)
    assert metrics.unique_raw_outputs == 3
    assert metrics.unique_normalized_outputs == 2
    assert metrics.most_common_normalized_frequency == 2
    assert metrics.diagnostic_collapse_flag is False


def test_ablation_retries_truncation_and_sorts_best_variant(tmp_path: Path) -> None:
    event = _event()
    artifact = ExperimentalCandidateEventsArtifact(
        video_filename="movie.mp4",
        video_duration_us=20_000_000,
        policy=ExperimentalCandidatePolicy(
            semantic_gap_seconds=10.0,
            semantic_phase_seconds=0.0,
            onnx_baseline="D",
            nsfw_threshold=0.3,
            nsfl_threshold=0.3,
            semantic_strategy="mean_positive_cosine",
            weapons_threshold=0.1,
            drugs_threshold=0.1,
        ),
        clustering_configuration=ClusteringConfiguration(
            merge_gap_seconds=15.0,
            context_seconds=0.0,
            maximum_event_duration_seconds=60.0,
        ),
        events=(event,),
    )
    ground_truth = GroundTruthArtifact(
        video=GroundTruthVideo(filename="movie.mp4"),
        intervals=(
            GroundTruthInterval(
                start="00:00:09.000",
                end="00:00:11.000",
                category="weapons",
            ),
        ),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    Image.new("RGB", (4, 3)).save(cache / "selected.png")
    manifest = _manifest(event)
    events_path = tmp_path / "events.json"
    gt_path = tmp_path / "gt.json"
    events_path.write_text(artifact.model_dump_json(), encoding="utf-8")
    gt_path.write_text(ground_truth.model_dump_json(), encoding="utf-8")
    runtime = _FakeRuntime()

    report, full = evaluate_prompt_ablation(
        artifact,
        ground_truth,
        manifest,
        event_artifact_path=events_path,
        ground_truth_path=gt_path,
        frame_cache_root=cache,
        verifier=_FakeVerifier(runtime),
    )

    assert 96 in runtime.max_new_tokens_calls
    assert report.best_measured_prompt_variant == PromptVariantId.HIGH_RECALL
    best = next(
        item
        for item in report.variants
        if item.definition.variant_id == PromptVariantId.HIGH_RECALL
    )
    assert best.metrics.known_unsafe_recall == 1.0
    assert best.metrics.category_aware_recall == 1.0
    assert full.summary.known_silver_metrics.category_aware_recall == 1.0


def _payload(**updates: tuple[int, ...]) -> EvidenceMapPayload:
    values = {category: () for category in CATEGORY_IDS}
    values.update(updates)
    return EvidenceMapPayload(
        category_evidence=CategoryEvidenceMap(**values),
    )


def _event() -> CandidateEvent:
    sample = CandidateSample(
        sample_id="representative:0:10000000:1",
        timestamp_us=10_000_000,
        sample_reasons=("temporal_safety",),
        detectors=("onnx_safety",),
        onnx_nsfw=0.5,
        onnx_nsfl=0.1,
        onnx_triggered=True,
        tinyclip_triggered=False,
        tinyclip_weapons_triggered=False,
        tinyclip_drugs_triggered=False,
    )
    return CandidateEvent(
        event_id="event:0001",
        candidate_start_timestamp_us=10_000_000,
        candidate_end_timestamp_us=10_000_000,
        start_timestamp_us=10_000_000,
        end_timestamp_us=10_000_000,
        duration_seconds=0.0,
        candidate_count=1,
        detector_profile="onnx_only",
        selected_frames=(
            SelectedEventFrame(sample=sample, selection_reasons=("strongest_onnx",)),
        ),
        largest_selected_frame_gap_seconds=0.0,
        start_to_first_selected_seconds=0.0,
        last_selected_to_end_seconds=0.0,
    )


def _manifest(event: CandidateEvent) -> SelectedFrameCacheManifest:
    selected = event.selected_frames[0]
    return SelectedFrameCacheManifest(
        video_path="movie.mp4",
        video_filename="movie.mp4",
        video_duration_us=20_000_000,
        video_fingerprint="sha256:" + "a" * 64,
        event_artifact_sha256="b" * 64,
        preprocessing_score_artifact_sha256="c" * 64,
        preprocessing={},
        expected_event_count=1,
        expected_frame_reference_count=1,
        representatives_observed=1,
        entries=(
            CachedSelectedFrame(
                event_id=event.event_id,
                frame_index=1,
                sample_id=selected.sample.sample_id,
                timestamp_us=selected.sample.timestamp_us,
                source_pts=1,
                owning_chunk_index=0,
                sample_reasons=("temporal_safety",),
                selection_reasons=selected.selection_reasons,
                canvas_width=4,
                canvas_height=3,
                content_rect=(0, 0, 4, 3),
                cropped_width=4,
                cropped_height=3,
                relative_png_path="selected.png",
                png_sha256="0" * 64,
            ),
        ),
        unresolved=(),
    )


def _provenance() -> SmolVLMRuntimeProvenance:
    return SmolVLMRuntimeProvenance(
        repository_id="test/model",
        revision="a" * 40,
        checkpoint_sha256="b" * 64,
        model_class="SmolVLMForConditionalGeneration",
        processor_class="SmolVLMProcessor",
        parameter_count=1,
        model_dtype="float32",
        device="cuda",
        transformers_version="test",
        torch_version="test",
        attention_implementation="sdpa",
    )


class _FakeRuntime:
    def __init__(self) -> None:
        self.provenance = _provenance()
        self.max_new_tokens_calls: list[int] = []
        self._minimal_truncated = False

    def generate_raw(
        self,
        request,
        conversation,
        *,
        max_new_tokens: int,
        image_splitting: bool,
    ) -> RawSmolVLMGeneration:
        assert image_splitting is False
        self.max_new_tokens_calls.append(max_new_tokens)
        text = " ".join(
            item.get("text", "") for item in conversation[0]["content"]
        )
        is_minimal = "Visual definitions:" not in text
        if is_minimal and max_new_tokens == 64 and not self._minimal_truncated:
            self._minimal_truncated = True
            return self._generation(
                request.metadata.event_id,
                raw='{"category_evidence":',
                truncated=True,
                max_tokens=max_new_tokens,
            )
        weapons = (1,) if "plausible visible evidence" in text else ()
        return self._generation(
            request.metadata.event_id,
            raw=_payload(weapons=weapons).model_dump_json(),
            truncated=False,
            max_tokens=max_new_tokens,
        )

    def _generation(
        self,
        event_id: str,
        *,
        raw: str,
        truncated: bool,
        max_tokens: int,
    ) -> RawSmolVLMGeneration:
        return RawSmolVLMGeneration(
            event_id=event_id,
            raw_generated_text=raw,
            error=("generation reached max_new_tokens" if truncated else None),
            truncated=truncated,
            generated_token_count=max_tokens if truncated else 20,
            chat_template_seconds=0.0,
            processor_seconds=0.0,
            generation_seconds=0.1,
            decode_seconds=0.0,
            total_seconds=0.1,
            tokens_per_second=200.0,
            expansion=None,
            provenance=self.provenance,
        )


class _FakeVerifier:
    def __init__(self, runtime: _FakeRuntime) -> None:
        self._runtime = runtime

    def runtime(self) -> _FakeRuntime:
        return self._runtime
