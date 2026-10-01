from __future__ import annotations

import pytest

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.representative_fanout import FinalizableRepresentativeFanout
from services.analysis.semantic_sampling_robustness import select_phase_offset_samples
from services.analysis.temporal_representative_router import (
    TemporalRepresentativeRouter,
)
from tests.test_tinyclip_semantic import _callback_frame


class _RecordingConsumer:
    def __init__(self) -> None:
        self.timestamps: list[int] = []
        self.flushes = 0

    def __call__(self, _frame, sample, _cancellation) -> None:
        self.timestamps.append(sample.timestamp_us)

    def flush(self, _cancellation) -> None:
        self.flushes += 1


def _route(router: TemporalRepresentativeRouter, timestamps: list[int]) -> None:
    token = CancellationToken()
    for index, timestamp in enumerate(timestamps):
        frame, sample = _callback_frame(index)
        router(frame, sample.model_copy(update={"timestamp_us": timestamp}), token)


@pytest.mark.parametrize(
    ("gap", "phase"),
    ((0.0, 0.0), (10.0, -0.1), (10.0, 10.0)),
)
def test_gap_and_phase_are_validated(gap: float, phase: float):
    with pytest.raises(ValueError):
        TemporalRepresentativeRouter(
            _RecordingConsumer(), gap_seconds=gap, phase_seconds=phase
        )


def test_phase_zero_uses_global_targets_and_finalizes_without_synthetic_frame():
    downstream = _RecordingConsumer()
    router = TemporalRepresentativeRouter(downstream, gap_seconds=10.0)

    _route(router, [2_000_000, 9_000_000, 10_000_000, 20_000_000])
    router.flush(CancellationToken())

    assert downstream.timestamps == [2_000_000, 10_000_000, 20_000_000]
    assert downstream.flushes == 1
    assert router.metrics.representatives_routed == 3
    assert router.metrics.representatives_skipped == 1


def test_nonzero_phase_does_not_force_first_and_large_jump_routes_once():
    downstream = _RecordingConsumer()
    router = TemporalRepresentativeRouter(
        downstream,
        gap_seconds=10.0,
        phase_seconds=2.5,
    )

    _route(router, [2_000_000, 3_000_000, 35_000_000])

    assert downstream.timestamps == [3_000_000, 35_000_000]
    assert router.metrics.first_routed_timestamp_us == 3_000_000
    assert router.metrics.maximum_routed_delta_us == 32_000_000


def test_online_router_matches_offline_phase_selector_and_holds_no_skipped_frames():
    timestamps = [2_000_000, 3_000_000, 5_000_000, 7_000_000, 9_000_000]
    downstream = _RecordingConsumer()
    router = TemporalRepresentativeRouter(
        downstream,
        gap_seconds=3.0,
        phase_seconds=2.5,
    )

    _route(router, timestamps)

    expected_mask = select_phase_offset_samples(timestamps, 3.0, 2.5)
    assert downstream.timestamps == [
        timestamp
        for timestamp, selected in zip(timestamps, expected_mask, strict=True)
        if selected
    ]
    assert not hasattr(router, "_pending")
    assert router.metrics.total_representatives_observed == len(timestamps)


def test_cancellation_prevents_new_semantic_routing():
    downstream = _RecordingConsumer()
    router = TemporalRepresentativeRouter(downstream, gap_seconds=10.0)
    token = CancellationToken()
    token.cancel()
    frame, sample = _callback_frame(0)

    with pytest.raises(AnalysisCancelled):
        router(frame, sample, token)
    assert downstream.timestamps == []
    assert router.metrics.total_representatives_observed == 0


def test_fanout_keeps_onnx_sibling_on_full_coverage_while_semantic_is_sparse():
    onnx = _RecordingConsumer()
    tinyclip = _RecordingConsumer()
    router = TemporalRepresentativeRouter(tinyclip, gap_seconds=10.0)
    fanout = FinalizableRepresentativeFanout(
        (("onnx-safety", onnx), ("semantic-router", router))
    )
    timestamps = [2_000_000, 9_000_000, 10_000_000, 20_000_000]
    token = CancellationToken()
    for index, timestamp in enumerate(timestamps):
        frame, sample = _callback_frame(index)
        fanout(frame, sample.model_copy(update={"timestamp_us": timestamp}), token)
    fanout.flush(token)

    assert onnx.timestamps == timestamps
    assert tinyclip.timestamps == [2_000_000, 10_000_000, 20_000_000]
    assert onnx.flushes == tinyclip.flushes == 1
