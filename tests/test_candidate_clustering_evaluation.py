from __future__ import annotations

import ast
import inspect

from services.analysis.candidate_clustering_evaluation import (
    CandidateSample,
    _coverage,
    _split_oversized_group,
    cluster_candidates,
    select_event_frames,
)
from services.analysis.stage1_evaluation import GroundTruthInterval


def _candidate(
    timestamp_us: int,
    *,
    onnx: bool = True,
    weapons: bool = False,
    drugs: bool = False,
) -> CandidateSample:
    detectors = []
    if onnx:
        detectors.append("onnx_safety")
    if weapons or drugs:
        detectors.append("tinyclip_semantic")
    return CandidateSample(
        sample_id=f"sample:{timestamp_us}",
        timestamp_us=timestamp_us,
        sample_reasons=("temporal_safety",),
        detectors=tuple(detectors),
        onnx_nsfw=0.9 if onnx else 0.1,
        onnx_nsfl=0.1,
        onnx_triggered=onnx,
        tinyclip_triggered=weapons or drugs,
        tinyclip_weapons_triggered=weapons,
        tinyclip_drugs_triggered=drugs,
        tinyclip_weapons_score=0.8 if weapons else None,
        tinyclip_drugs_score=0.7 if drugs else None,
    )


def test_timestamp_clustering_includes_boundary_equality_and_clamps_context():
    events = cluster_candidates(
        (_candidate(0), _candidate(500_000)),
        merge_gap_seconds=0.5,
        context_seconds=1.0,
        maximum_event_duration_seconds=15.0,
        movie_duration_us=1_000_000,
    )

    assert len(events) == 1
    assert events[0].start_timestamp_us == 0
    assert events[0].end_timestamp_us == 1_000_000


def test_oversized_cluster_splits_at_largest_internal_gap():
    group = (
        _candidate(0),
        _candidate(1_000_000),
        _candidate(10_000_000),
        _candidate(11_000_000),
    )

    segments = _split_oversized_group(
        group,
        context_us=0,
        maximum_duration_us=5_000_000,
    )

    assert [[item.timestamp_us for item in segment] for segment in segments] == [
        [0, 1_000_000],
        [10_000_000, 11_000_000],
    ]


def test_selection_deduplicates_roles_caps_at_six_and_uses_temporal_diversity():
    candidates = tuple(
        _candidate(
            index * 1_000_000,
            onnx=index in {0, 3},
            weapons=index == 1,
            drugs=index == 1,
        )
        for index in range(8)
    )

    first = select_event_frames(candidates)
    second = select_event_frames(candidates)

    assert first == second
    assert len(first) == 6
    assert any(
        set(item.selection_reasons)
        >= {"strongest_tinyclip_weapons", "strongest_tinyclip_drugs"}
        for item in first
    )
    assert any("temporal_diversity" in item.selection_reasons for item in first)


def test_candidate_events_preserve_ground_truth_candidate_coverage_and_detector_mix():
    candidates = (
        _candidate(1_000_000, onnx=True),
        _candidate(2_000_000, onnx=False, drugs=True),
    )
    interval = GroundTruthInterval(
        start="00:00:01.000", end="00:00:02.000", category="drugs"
    )
    events = cluster_candidates(
        candidates,
        merge_gap_seconds=2.0,
        context_seconds=0.0,
        maximum_event_duration_seconds=15.0,
        movie_duration_us=10_000_000,
    )
    exact, tolerant, missed = _coverage(candidates, (interval,), 10_000_000)

    assert events[0].detector_profile == "both"
    assert exact == tolerant == [True]
    assert missed == []


def test_clustering_module_imports_no_movie_or_model_runtime():
    module = __import__(
        "services.analysis.candidate_clustering_evaluation", fromlist=["*"]
    )
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imports & {"torch", "transformers", "onnxruntime", "cv2", "subprocess"}
