from __future__ import annotations

import ast
import inspect

import pytest

from services.analysis.semantic_sampling_robustness import (
    SemanticSamplingRobustnessError,
    evaluate_semantic_sampling_robustness,
    phase_offset_grid,
    select_phase_offset_samples,
)
from tests.test_stage1_union_evaluation import (
    _config,
    _ground_truth,
    _prompt_bank,
    _safety,
    _semantic,
)


def test_phase_zero_uses_global_targets_and_nonzero_phase_does_not_force_first():
    timestamps = (2_000_000, 3_000_000, 5_000_000, 7_000_000, 9_000_000)

    assert select_phase_offset_samples(timestamps, 3.0, 0.0).tolist() == [
        True,
        True,
        False,
        True,
        True,
    ]
    assert select_phase_offset_samples(timestamps, 3.0, 2.5).tolist() == [
        False,
        True,
        False,
        True,
        True,
    ]


@pytest.mark.parametrize("phase", (-0.1, 3.0, 4.0))
def test_phase_must_be_less_than_gap(phase: float):
    with pytest.raises(SemanticSamplingRobustnessError, match="phase < gap"):
        select_phase_offset_samples((1_000_000, 2_000_000), 3.0, phase)


def test_phase_grid_is_deterministic_and_contains_quarters():
    offsets = phase_offset_grid(3.0, 1.0)

    assert offsets == (0.0, 0.75, 1.0, 1.5, 2.0, 2.25)


def test_robustness_aggregates_worst_case_success_and_keeps_onnx_full_coverage():
    prompt_bank = _prompt_bank()
    report = evaluate_semantic_sampling_robustness(
        _safety(),
        _semantic(prompt_bank),
        _ground_truth(),
        prompt_bank,
        _config(),
        gaps_seconds=(10.0,),
        phase_step_seconds=1.0,
    )

    result = report.gap_results[0]
    assert result.phase_offsets_seconds[0] == 0.0
    assert result.minimum_retained_semantic_samples >= 1
    assert result.worst_case_exact_recall == pytest.approx(1.0)
    assert result.phase_success_rate_100_recall == pytest.approx(1.0)
    assert result.robust_exact_recall_1
    assert result.target_interval_summary
    # The synthetic ONNX artifact detects the drug interval even if that phase
    # has no retained TinyCLIP representative inside it.
    assert any(
        target.phases_union_detected == target.total_phases
        for target in result.target_interval_summary
    )


def test_robustness_module_does_not_import_ai_or_media_runtimes():
    module = __import__(
        "services.analysis.semantic_sampling_robustness", fromlist=["*"]
    )
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"torch", "transformers", "onnxruntime", "cv2", "subprocess"}
