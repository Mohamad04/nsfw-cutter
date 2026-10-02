from __future__ import annotations

import ast
import hashlib
import inspect
import json

import numpy as np
import pytest

from services.analysis.preprocessing_contracts import PreprocessingConfig
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    GroundTruthVideo,
    Stage1ScoreArtifact,
    Stage1ScoreModel,
    Stage1ScoreSample,
    Stage1ScoreVideo,
)
from services.analysis.stage1_union_evaluation import (
    REQUIRED_CONCEPT_IDS,
    OfflinePrompt,
    OfflinePromptBank,
    SemanticModelProvenance,
    SemanticPromptBankProvenance,
    SemanticScoreArtifact,
    SemanticScoreSample,
    SemanticScoreValue,
    Stage1UnionEvaluationConfiguration,
    Stage1UnionEvaluationError,
    _candidate_metrics,
    _strategy_scores,
    _temporal_workload,
    align_artifacts,
    evaluate_union_artifacts,
)


def _prompt_bank() -> OfflinePromptBank:
    prompts = tuple(
        OfflinePrompt(concept_id=concept_id, text=f"prompt {index}")
        for index, concept_id in enumerate(REQUIRED_CONCEPT_IDS)
    )
    return OfflinePromptBank(bank_id="test-bank", version="v1", prompts=prompts)


def _safety_samples() -> tuple[Stage1ScoreSample, ...]:
    return (
        Stage1ScoreSample(
            sample_id="a",
            timestamp_us=1_000_000,
            nsfl=0.05,
            nsfw=0.10,
            sfw=0.85,
            selected_label="SFW",
            sample_reasons=("temporal_safety",),
        ),
        Stage1ScoreSample(
            sample_id="b",
            timestamp_us=5_000_000,
            nsfl=0.45,
            nsfw=0.10,
            sfw=0.45,
            selected_label="NSFL",
            sample_reasons=("temporal_safety",),
        ),
        Stage1ScoreSample(
            sample_id="c",
            timestamp_us=9_000_000,
            nsfl=0.05,
            nsfw=0.35,
            sfw=0.60,
            selected_label="SFW",
            sample_reasons=("temporal_safety",),
        ),
    )


def _safety() -> Stage1ScoreArtifact:
    return Stage1ScoreArtifact(
        generated_at_utc="2026-01-01T00:00:00Z",
        video=Stage1ScoreVideo(filename="movie.mp4", duration_us=10_000_000),
        model=Stage1ScoreModel(
            repo_id="safety",
            revision="pinned",
            sha256="a" * 64,
            runtime="onnxruntime:test",
            providers=("CPUExecutionProvider",),
        ),
        preprocessing=PreprocessingConfig(),
        samples=_safety_samples(),
    )


def _semantic_sample(sample_id: str, timestamp_us: int, scores: dict[str, float]):
    return SemanticScoreSample(
        sample_id=sample_id,
        timestamp_us=timestamp_us,
        sample_reasons=("temporal_safety",),
        scores=tuple(
            SemanticScoreValue(
                concept_id=concept_id,
                prompt_sha256=hashlib.sha256(concept_id.encode()).hexdigest(),
                cosine_similarity=scores[concept_id],
                scaled_logit=scores[concept_id] * 10.0,
            )
            for concept_id in REQUIRED_CONCEPT_IDS
        ),
    )


def _semantic(
    prompt_bank: OfflinePromptBank,
    *,
    alternate_ids: bool = False,
    timestamp_offset_us: int = 0,
) -> SemanticScoreArtifact:
    values = []
    rows = (
        # weapon is strongest in the first interval, drug in the second.
        {**{value: 0.10 for value in REQUIRED_CONCEPT_IDS}, "weapons.firearm": 0.90},
        {**{value: 0.10 for value in REQUIRED_CONCEPT_IDS}, "drugs.smoking_marijuana": 0.85},
        {**{value: 0.10 for value in REQUIRED_CONCEPT_IDS}, "control.everyday_scene": 0.95},
    )
    for index, (sample, scores) in enumerate(zip(_safety_samples(), rows, strict=True)):
        values.append(
            _semantic_sample(
                f"semantic-{index}" if alternate_ids else sample.sample_id,
                sample.timestamp_us + timestamp_offset_us,
                scores,
            )
        )
    return SemanticScoreArtifact(
        artifact_kind="tinyclip_semantic_raw_scores",
        generated_at_utc="2026-01-01T00:00:00Z",
        video=Stage1ScoreVideo(filename="movie.mp4", duration_us=10_000_000),
        model=SemanticModelProvenance(
            repo_id="tinyclip",
            revision="pinned",
            checkpoint_sha256="b" * 64,
            torch_version="not-loaded",
            transformers_version="not-loaded",
            device="cpu",
            dtype="float32",
            processor_class="CLIPProcessor",
            tokenizer_class="CLIPTokenizer",
            logit_scale_exp=10.0,
        ),
        prompt_bank=SemanticPromptBankProvenance(
            bank_id=prompt_bank.bank_id,
            version=prompt_bank.version,
            digest=prompt_bank.digest,
            prompts=prompt_bank.prompts,
        ),
        preprocessing=PreprocessingConfig(),
        samples=tuple(values),
    )


def _ground_truth() -> GroundTruthArtifact:
    return GroundTruthArtifact(
        video=GroundTruthVideo(filename="movie.mp4"),
        intervals=(
            GroundTruthInterval(
                start="00:00:00.500",
                end="00:00:01.500",
                category="weapons",
                severity="high",
            ),
            GroundTruthInterval(
                start="00:00:04.500",
                end="00:00:05.500",
                category="drugs",
                severity="medium",
            ),
        ),
    )


def _config(**overrides) -> Stage1UnionEvaluationConfiguration:
    return Stage1UnionEvaluationConfiguration(
        expected_representative_samples=3,
        semantic_threshold_count=2,
        context_seconds=(0.0, 1.0, 2.0, 5.0),
        merge_gap_seconds=(0.0, 1.0, 2.0),
        **overrides,
    )


def test_alignment_uses_sample_identity_and_validates_prompt_digest():
    prompt_bank = _prompt_bank()
    aligned = align_artifacts(_safety(), _semantic(prompt_bank), prompt_bank, _config())

    assert aligned.alignment.mode == "sample_id"
    assert aligned.alignment.aligned_sample_count == 3
    assert aligned.semantic[0].sample_id == "a"


def test_alignment_uses_explicit_timestamp_fallback_and_rejects_mismatch():
    prompt_bank = _prompt_bank()
    timestamp_aligned = align_artifacts(
        _safety(),
        _semantic(prompt_bank, alternate_ids=True),
        prompt_bank,
        _config(timestamp_tolerance_us=0),
    )
    assert timestamp_aligned.alignment.mode == "timestamp"

    with pytest.raises(Stage1UnionEvaluationError, match="Timestamp"):
        align_artifacts(
            _safety(),
            _semantic(prompt_bank, alternate_ids=True, timestamp_offset_us=2),
            prompt_bank,
            _config(timestamp_tolerance_us=1),
        )


def test_alignment_rejects_prompt_bank_mismatch():
    prompt_bank = _prompt_bank()
    changed = prompt_bank.model_copy(update={"version": "v2"})
    with pytest.raises(Stage1UnionEvaluationError, match="prompt-bank digest"):
        align_artifacts(_safety(), _semantic(prompt_bank), changed, _config())


def test_aggregation_methods_and_control_margin_are_correct():
    prompt_bank = _prompt_bank()
    semantic = _semantic(prompt_bank)
    arrays = {
        concept_id: np.asarray(
            [
                next(score.cosine_similarity for score in sample.scores if score.concept_id == concept_id)
                for sample in semantic.samples
            ]
        )
        for concept_id in REQUIRED_CONCEPT_IDS
    }
    strategies = _strategy_scores(arrays)

    assert strategies["max_positive_cosine"]["weapons"][0] == pytest.approx(0.90)
    assert strategies["mean_positive_cosine"]["weapons"][0] == pytest.approx(0.30)
    assert strategies["max_positive_vs_control_max_margin"]["weapons"][0] == pytest.approx(0.80)
    assert strategies["max_positive_vs_control_max_margin"]["weapons"][2] < 0.0
    assert strategies["mean_positive_vs_control_max_margin"]["drugs"][1] > 0.0


def test_semantic_policies_recover_target_categories_and_union_metrics():
    prompt_bank = _prompt_bank()
    report = evaluate_union_artifacts(
        _safety(),
        _semantic(prompt_bank),
        _ground_truth(),
        prompt_bank,
        _config(),
    )

    assert report.score_distributions
    assert any(item.population == "inside_weapons" for item in report.score_distributions)
    assert len(report.interval_peak_scores) == 2
    assert report.interval_peak_scores[0].exact.maximum_nsfw.value == pytest.approx(0.10)
    assert report.interval_peak_scores[0].exact.prompt_peaks[1][0] == "weapons.firearm"
    assert any(
        result.metrics.semantic_target_category_recall
        and all(item.interval_recall == 1.0 for item in result.metrics.semantic_target_category_recall)
        for result in report.semantic_policies
    )
    assert any(result.metrics.interval_recall == 1.0 for result in report.union_policies)
    assert report.exact_recall_pareto


def test_threshold_equality_is_a_candidate_and_no_candidate_is_explicit():
    intervals = _ground_truth().intervals
    timestamps = np.asarray([1_000_000, 5_000_000], dtype=np.int64)
    equal_metrics = _candidate_metrics(
        np.asarray([True, False]),
        timestamps=timestamps,
        intervals=intervals,
        duration_us=10_000_000,
        tolerance_seconds=5.0,
        temporal_grid=((0.0, 0.0),),
        frames_per_region=6,
    )
    none_metrics = _candidate_metrics(
        np.asarray([False, False]),
        timestamps=timestamps,
        intervals=intervals,
        duration_us=10_000_000,
        tolerance_seconds=5.0,
        temporal_grid=((0.0, 0.0),),
        frames_per_region=6,
    )

    assert equal_metrics.detected_intervals == 1
    assert none_metrics.candidate_samples == 0
    assert none_metrics.frame_candidate_precision is None


@pytest.mark.parametrize("context", [0.0, 1.0, 2.0, 5.0])
@pytest.mark.parametrize("merge_gap", [0.0, 1.0, 2.0])
def test_temporal_workload_supports_requested_context_and_gap_grid(context, merge_gap):
    workload = _temporal_workload(
        np.asarray([1_000_000, 2_000_000, 8_000_000], dtype=np.int64),
        duration_us=10_000_000,
        context_seconds=context,
        merge_gap_seconds=merge_gap,
        frames_per_region=6,
    )
    assert workload.estimated_vlm_images == workload.merged_candidate_regions * 6
    assert workload.movie_fraction >= 0.0


def test_offline_module_does_not_import_inference_runtimes_or_movie_processing():
    import services.analysis.stage1_union_evaluation as module

    tree = ast.parse(inspect.getsource(module))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {"onnxruntime", "torch", "transformers"} & imported


def test_semantic_artifact_schema_is_json_serializable(tmp_path):
    prompt_bank = _prompt_bank()
    artifact = _semantic(prompt_bank)
    path = tmp_path / "semantic.json"
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    loaded = SemanticScoreArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded == artifact
    assert json.loads(path.read_text(encoding="utf-8"))["samples"][0].get("candidate") is None
