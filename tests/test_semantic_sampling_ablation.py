from __future__ import annotations

import ast
import inspect

import pytest

from services.analysis.semantic_sampling_ablation import (
    FULL_ENCODER_SECONDS,
    evaluate_semantic_sampling_ablation,
    scene_aware_mask,
    select_timestamp_samples,
)
from tests.test_stage1_union_evaluation import (
    _config,
    _ground_truth,
    _prompt_bank,
    _safety,
    _semantic,
)


def test_timestamp_selection_is_deterministic_and_uses_elapsed_time():
    timestamps = (100, 450_000, 600_000, 1_100_000, 1_700_000)

    first = select_timestamp_samples(timestamps, 0.5)
    second = select_timestamp_samples(timestamps, 0.5)

    assert first.tolist() == [True, False, True, True, True]
    assert first.tolist() == second.tolist()


def test_scene_aware_mask_uses_persisted_scene_transition_reason_only():
    semantic = _semantic(_prompt_bank())
    scene_sample = semantic.samples[0].model_copy(
        update={"sample_reasons": ("scene_transition",)}
    )
    updated = semantic.model_copy(
        update={"samples": (scene_sample, *semantic.samples[1:])}
    )

    assert scene_aware_mask(updated.samples).tolist() == [True, False, False]


def test_sampling_masks_only_semantic_scores_and_re_evaluates_union_grid():
    prompt_bank = _prompt_bank()
    report = evaluate_semantic_sampling_ablation(
        _safety(),
        _semantic(prompt_bank),
        _ground_truth(),
        prompt_bank,
        _config(),
        gaps_seconds=(10.0,),
    )

    temporal = next(item for item in report.results if item.mode == "temporal")
    hybrid = next(
        item for item in report.results if item.mode == "temporal_plus_scene_transition"
    )
    assert temporal.retained_semantic_samples == 1
    # The ONNX baseline still sees every representative, even though TinyCLIP
    # has only its first sample available.
    assert temporal.highest_exact_union_recall == pytest.approx(1.0)
    assert hybrid.retained_semantic_samples == 1
    assert temporal.linear_encoder_seconds_estimate == pytest.approx(
        FULL_ENCODER_SECONDS / 3
    )
    drugs = next(item for item in temporal.target_intervals if item.category == "drugs")
    assert drugs.retained_semantic_samples_inside == 0
    assert not drugs.semantic_detected
    assert drugs.union_detected


def test_ablation_module_has_no_model_or_media_runtime_imports():
    source = inspect.getsource(
        __import__("services.analysis.semantic_sampling_ablation", fromlist=["*"])
    )
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {"torch", "transformers", "onnxruntime", "cv2", "subprocess"}
    assert not imports & forbidden
