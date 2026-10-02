from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from services.analysis.cancellation import CancellationToken
from services.analysis.candidate_clustering_evaluation import (
    CandidateEvent,
    CandidateSample,
    ClusteringConfiguration,
    ExperimentalCandidateEventsArtifact,
    ExperimentalCandidatePolicy,
    SelectedEventFrame,
)
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    SampleReason,
)
from services.analysis.smolvlm_quality_evaluation import (
    CachedSelectedFrame,
    EventQualityRecord,
    FrameTarget,
    SelectedFrameCacheConsumer,
    SelectedFrameCacheManifest,
    SmolVLMRealQualityReport,
    VerificationAttempt,
    build_verification_request,
    classify_unverified_reason,
    comparison_frame_indices,
    evaluate_real_candidate_quality,
    evaluate_silver_intervals,
    is_single_json_object,
    match_event_to_ground_truth,
    select_default_comparison_events,
    summarize_latency_by_image_count,
    summarize_quality,
    write_missed_interval_review,
)
from services.analysis.smolvlm_verifier import (
    GeneratedVerificationPayload,
    SmolVLMRuntimeProvenance,
    VerificationStatus,
    VLMVerificationResult,
)
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    GroundTruthVideo,
)


def test_event_ground_truth_overlap_and_multiple_intervals() -> None:
    event = _event("event:0001", 10_000_000, 30_000_000, image_count=1)
    intervals = (
        GroundTruthInterval(start="00:00:12.000", end="00:00:15.000", category="drugs"),
        GroundTruthInterval(start="00:00:20.000", end="00:00:25.000", category="weapons"),
        GroundTruthInterval(start="00:00:40.000", end="00:00:45.000", category="nudity"),
    )

    overlaps = match_event_to_ground_truth(event, intervals, movie_duration_us=60_000_000)

    assert [(item.interval_id, item.exact_overlap) for item in overlaps] == [
        ("silver:000", True),
        ("silver:001", True),
    ]


def test_known_unsafe_and_category_aware_recall_are_separate() -> None:
    event = _event("event:0001", 10_000_000, 30_000_000, image_count=1)
    intervals = (
        GroundTruthInterval(start="00:00:12.000", end="00:00:15.000", category="drugs"),
        GroundTruthInterval(start="00:00:20.000", end="00:00:25.000", category="weapons"),
    )
    overlaps = match_event_to_ground_truth(event, intervals, movie_duration_us=60_000_000)
    record = _record(event, overlaps, _attempt(VerificationStatus.VERIFIED_UNSAFE, ("drugs",)))

    metrics = evaluate_silver_intervals(intervals, (record,))

    assert [metric.unsafe_detected_exact for metric in metrics] == [True, True]
    assert [metric.category_detected_exact for metric in metrics] == [True, False]


def test_unverified_is_not_counted_safe_and_unlabeled_is_descriptive() -> None:
    labeled = _event("event:0001", 10_000_000, 11_000_000, image_count=1)
    unlabeled = _event("event:0002", 40_000_000, 41_000_000, image_count=1)
    interval = GroundTruthInterval(
        start="00:00:10.000", end="00:00:12.000", category="violence"
    )
    records = (
        _record(
            labeled,
            match_event_to_ground_truth(labeled, (interval,), movie_duration_us=60_000_000),
            _attempt(VerificationStatus.UNVERIFIED),
        ),
        _record(
            unlabeled,
            (),
            _attempt(VerificationStatus.VERIFIED_UNSAFE, ("weapons",)),
        ),
    )
    intervals = evaluate_silver_intervals((interval,), records)

    summary = summarize_quality(
        records,
        intervals,
        model_load_seconds=1.0,
        artifact_resolution_seconds=0.5,
        sequential_verifier_wall_seconds=2.0,
    )

    assert summary.verified_safe == 0
    assert summary.unverified == 1
    assert summary.unlabeled_verified_unsafe == 1
    assert summary.exact_unsafe_recall == 0.0


def test_latency_is_aggregated_by_image_count() -> None:
    records = (
        _record(_event("e1", 0, 1, image_count=1), (), _attempt(total_seconds=1.0)),
        _record(_event("e2", 2, 3, image_count=1), (), _attempt(total_seconds=3.0)),
        _record(_event("e3", 4, 5, image_count=3), (), _attempt(total_seconds=6.0)),
    )

    metrics = summarize_latency_by_image_count(records)

    assert [(item.image_count, item.event_count) for item in metrics] == [(1, 2), (3, 1)]
    assert metrics[0].mean_total_seconds == 2.0
    assert metrics[1].p95_total_seconds == 6.0


def test_json_and_unverified_failure_classification() -> None:
    malformed = _attempt(VerificationStatus.UNVERIFIED, raw="not-json")
    assert not is_single_json_object(malformed.result.raw_generated_text)
    assert classify_unverified_reason(malformed.result) == "malformed_json"
    assert is_single_json_object('{"unsafe":false}')


def test_comparison_reduces_large_events_to_three_ordered_frames() -> None:
    assert comparison_frame_indices(1) == (1,)
    assert comparison_frame_indices(3) == (1, 2, 3)
    assert comparison_frame_indices(6) == (1, 3, 6)


def test_default_comparison_selection_includes_drugs_and_weapons() -> None:
    drug = _event("drug", 10_000_000, 20_000_000, image_count=6)
    weapon = _event("weapon", 30_000_000, 40_000_000, image_count=1)
    intervals = (
        GroundTruthInterval(start="00:00:10.000", end="00:00:20.000", category="drugs"),
        GroundTruthInterval(start="00:00:30.000", end="00:00:40.000", category="weapons"),
    )
    records = tuple(
        _record(
            event,
            match_event_to_ground_truth(event, intervals, movie_duration_us=60_000_000),
            _attempt(),
        )
        for event in (drug, weapon)
    )

    assert select_default_comparison_events((drug, weapon), records) == ("drug", "weapon")


def test_build_request_preserves_frame_order_and_uses_lossless_cache(tmp_path: Path) -> None:
    event = _event("event:0001", 1, 2, image_count=2)
    entries = []
    from services.analysis.smolvlm_quality_evaluation import CachedSelectedFrame

    for index, selected in enumerate(event.selected_frames, start=1):
        relative = Path(f"frame-{index}.png")
        Image.new("RGB", (4, 3), (index, 2, 3)).save(tmp_path / relative)
        entries.append(
            CachedSelectedFrame(
                event_id=event.event_id,
                frame_index=index,
                sample_id=selected.sample.sample_id,
                timestamp_us=selected.sample.timestamp_us,
                source_pts=index,
                owning_chunk_index=0,
                sample_reasons=("temporal_safety",),
                selection_reasons=selected.selection_reasons,
                canvas_width=4,
                canvas_height=3,
                content_rect=(0, 0, 4, 3),
                cropped_width=4,
                cropped_height=3,
                relative_png_path=relative.as_posix(),
                png_sha256="0" * 64,
            )
        )

    request, images = build_verification_request(event, entries, tmp_path)

    assert [frame.timestamp_us for frame in request.metadata.frames] == [1, 2]
    assert [image.getpixel((0, 0))[0] for image in images] == [1, 2]
    for image in images:
        image.close()


def test_unresolved_identity_is_not_substituted_by_equal_timestamp(tmp_path: Path) -> None:
    target = FrameTarget(
        event_id="event:0001",
        frame_index=1,
        sample_id="representative:0:100:7",
        timestamp_us=100,
        expected_sample_reasons=("temporal_safety",),
        selection_reasons=("earliest_candidate",),
    )
    consumer = SelectedFrameCacheConsumer((target,), tmp_path)
    sample = FrameSample(
        timestamp_us=100,
        source_pts=8,
        owning_chunk_index=0,
        sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
        width=4,
        height=4,
        content_rect=(0, 1, 4, 2),
        disposition=FrameDisposition.REPRESENTATIVE,
    )
    frame = ExtractedFrame(
        timestamp_us=100,
        source_pts=8,
        source_time_base=None,
        processing_chunk_index=0,
        sample_reasons=frozenset({SampleReason.TEMPORAL_SAFETY}),
        width=4,
        height=4,
        content_rect=(0, 1, 4, 2),
        scene_score=None,
        rgb_bytes=bytes(range(4 * 4 * 3)),
    )

    consumer(frame, sample, CancellationToken())

    assert consumer.entries == {}
    assert consumer.observed_at_target_timestamp == {100: "representative:0:100:8"}


def test_missed_review_contains_only_missed_interval_frames(tmp_path: Path) -> None:
    event = _event("event:0001", 10_000_000, 11_000_000, image_count=1)
    interval = GroundTruthInterval(
        start="00:00:10.000", end="00:00:12.000", category="drugs"
    )
    overlaps = match_event_to_ground_truth(event, (interval,), movie_duration_us=60_000_000)
    cache = tmp_path / "cache"
    cache.mkdir()
    Image.new("RGB", (4, 3)).save(cache / "selected.png")
    record = _record(event, overlaps, _attempt(VerificationStatus.VERIFIED_SAFE))
    record = record.model_copy(update={"selected_frame_paths": ("selected.png",)})
    interval_results = evaluate_silver_intervals((interval,), (record,))
    report = _report(record, interval_results)

    output = write_missed_interval_review(
        report,
        frame_cache_root=cache,
        output_dir=tmp_path / "review",
    )

    assert output is not None
    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert [item["interval_id"] for item in index["missed_intervals"]] == ["silver:000"]
    assert SmolVLMRealQualityReport.model_validate_json(
        report.model_dump_json()
    ) == report


def test_only_truncated_primary_output_is_retried_at_96_tokens(tmp_path: Path) -> None:
    event = _event("event:0001", 10_000_000, 11_000_000, image_count=1)
    events = ExperimentalCandidateEventsArtifact(
        video_filename="movie.mp4",
        video_duration_us=60_000_000,
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
                start="00:00:10.000", end="00:00:12.000", category="drugs"
            ),
        ),
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    image_path = cache / "selected.png"
    Image.new("RGB", (4, 3)).save(image_path)
    selected = event.selected_frames[0]
    entry = CachedSelectedFrame(
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
    )
    manifest = SelectedFrameCacheManifest(
        video_path="movie.mp4",
        video_filename="movie.mp4",
        video_duration_us=60_000_000,
        video_fingerprint="sha256:" + "a" * 64,
        event_artifact_sha256="b" * 64,
        preprocessing_score_artifact_sha256="c" * 64,
        preprocessing={},
        expected_event_count=1,
        expected_frame_reference_count=1,
        representatives_observed=1,
        entries=(entry,),
        unresolved=(),
    )
    event_path = tmp_path / "events.json"
    gt_path = tmp_path / "gt.json"
    event_path.write_text(events.model_dump_json(), encoding="utf-8")
    gt_path.write_text(ground_truth.model_dump_json(), encoding="utf-8")
    runtime = _RetryRuntime()
    verifier = _FakeVerifier(runtime)

    report = evaluate_real_candidate_quality(
        events,
        ground_truth,
        manifest,
        event_artifact_path=event_path,
        ground_truth_path=gt_path,
        frame_cache_root=cache,
        verifier=verifier,
        run_default_comparison=False,
    )

    assert runtime.max_new_tokens_calls == [64, 96]
    assert report.events[0].primary_attempt.result.status == VerificationStatus.UNVERIFIED
    assert report.events[0].truncation_retry_96.result.status == VerificationStatus.VERIFIED_SAFE
    assert report.summary.truncation_retries == 1


def _event(event_id: str, start_us: int, end_us: int, *, image_count: int) -> CandidateEvent:
    frames = tuple(
        SelectedEventFrame(
            sample=CandidateSample(
                sample_id=f"representative:0:{start_us + index - 1}:{index}",
                timestamp_us=start_us + index - 1,
                sample_reasons=("temporal_safety",),
                detectors=("onnx_safety",),
                onnx_nsfw=0.4,
                onnx_nsfl=0.1,
                onnx_triggered=True,
                tinyclip_triggered=False,
                tinyclip_weapons_triggered=False,
                tinyclip_drugs_triggered=False,
            ),
            selection_reasons=("strongest_onnx",),
        )
        for index in range(1, image_count + 1)
    )
    return CandidateEvent(
        event_id=event_id,
        candidate_start_timestamp_us=start_us,
        candidate_end_timestamp_us=end_us,
        start_timestamp_us=start_us,
        end_timestamp_us=end_us,
        duration_seconds=(end_us - start_us) / 1_000_000,
        candidate_count=image_count,
        detector_profile="onnx_only",
        selected_frames=frames,
        largest_selected_frame_gap_seconds=0.0,
        start_to_first_selected_seconds=0.0,
        last_selected_to_end_seconds=0.0,
    )


def _provenance() -> SmolVLMRuntimeProvenance:
    return SmolVLMRuntimeProvenance(
        repository_id="test/model",
        revision="a" * 40,
        checkpoint_sha256="b" * 64,
        model_class="SmolVLMForConditionalGeneration",
        processor_class="SmolVLMProcessor",
        parameter_count=1,
        model_dtype="torch.float32",
        device="cpu",
        transformers_version="test",
        torch_version="test",
        attention_implementation=None,
    )


def _attempt(
    status: VerificationStatus = VerificationStatus.VERIFIED_SAFE,
    categories: tuple[str, ...] = (),
    *,
    total_seconds: float = 1.0,
    raw: str | None = None,
) -> VerificationAttempt:
    unsafe = status == VerificationStatus.VERIFIED_UNSAFE
    payload = None
    error = None
    if status != VerificationStatus.UNVERIFIED:
        payload = GeneratedVerificationPayload(
            unsafe=unsafe,
            categories=categories,
            severity="high" if unsafe else None,
            reason="visible evidence" if unsafe else "no allowed evidence",
            evidence_frame_indices=(1,) if unsafe else (),
        )
    else:
        error = "JSONDecodeError: Expecting value"
    raw_text = raw if raw is not None else (
        json.dumps(payload.model_dump(mode="json")) if payload else "not-json"
    )
    result = VLMVerificationResult(
        event_id="test",
        status=status,
        payload=payload,
        evidence_timestamps_us=(1,) if unsafe else (),
        raw_generated_text=raw_text,
        error=error,
        truncated=False,
        generated_token_count=10,
        chat_template_seconds=0.1,
        processor_seconds=0.2,
        generation_seconds=0.6,
        decode_and_validation_seconds=0.1,
        total_seconds=total_seconds,
        tokens_per_second=10.0,
        expansion=None,
        provenance=_provenance(),
    )
    return VerificationAttempt(
        image_splitting=False,
        max_new_tokens=64,
        syntactic_json_valid=is_single_json_object(raw_text),
        pydantic_valid=payload is not None,
        failure_reason=classify_unverified_reason(result),
        result=result,
    )


def _record(
    event: CandidateEvent,
    overlaps: tuple,
    attempt: VerificationAttempt,
) -> EventQualityRecord:
    return EventQualityRecord(
        event_id=event.event_id,
        start_timestamp_us=event.start_timestamp_us,
        end_timestamp_us=event.end_timestamp_us,
        selected_frame_count=len(event.selected_frames),
        selected_frame_timestamps_us=tuple(
            frame.sample.timestamp_us for frame in event.selected_frames
        ),
        selected_frame_paths=tuple("selected.png" for _ in event.selected_frames),
        selected_frame_selection_reasons=tuple(
            frame.selection_reasons for frame in event.selected_frames
        ),
        silver_overlaps=overlaps,
        resolution_status="resolved",
        resolution_error=None,
        primary_attempt=attempt,
        truncation_retry_96=None,
    )


def _report(record: EventQualityRecord, intervals: tuple):
    from services.analysis.smolvlm_verifier import EXPERIMENTAL_VISUAL_SAFETY_POLICY

    summary = summarize_quality(
        (record,),
        intervals,
        model_load_seconds=0.0,
        artifact_resolution_seconds=0.0,
        sequential_verifier_wall_seconds=1.0,
    )
    return SmolVLMRealQualityReport(
        video_filename="movie.mp4",
        video_duration_us=60_000_000,
        video_fingerprint="sha256:" + "a" * 64,
        event_artifact_path="events.json",
        event_artifact_sha256="b" * 64,
        ground_truth_path="gt.json",
        ground_truth_sha256="c" * 64,
        frame_cache_manifest_path="manifest.json",
        model_provenance=_provenance().model_dump(mode="json"),
        verification_policy=EXPERIMENTAL_VISUAL_SAFETY_POLICY.model_dump(mode="json"),
        generation_settings={},
        events=(record,),
        silver_intervals=intervals,
        summary=summary,
        default_splitting_comparison=(),
        metric_notes=(),
    )


class _RetryRuntime:
    def __init__(self) -> None:
        self.provenance = _provenance()
        self.max_new_tokens_calls: list[int] = []

    def verify(self, request, *, max_new_tokens: int, image_splitting: bool):
        del image_splitting
        self.max_new_tokens_calls.append(max_new_tokens)
        if max_new_tokens == 64:
            return VLMVerificationResult(
                event_id=request.metadata.event_id,
                status=VerificationStatus.UNVERIFIED,
                payload=None,
                evidence_timestamps_us=(),
                raw_generated_text='{"unsafe": false',
                error="generation reached max_new_tokens before termination",
                truncated=True,
                generated_token_count=64,
                chat_template_seconds=0.0,
                processor_seconds=0.0,
                generation_seconds=0.0,
                decode_and_validation_seconds=0.0,
                total_seconds=0.0,
                tokens_per_second=None,
                expansion=None,
                provenance=self.provenance,
            )
        result = _attempt(VerificationStatus.VERIFIED_SAFE).result
        return result.model_copy(update={"event_id": request.metadata.event_id})


class _FakeVerifier:
    def __init__(self, runtime: _RetryRuntime) -> None:
        self._runtime = runtime
        self.model_load_seconds = 0.0
        self.artifact_resolution_seconds = 0.0

    def runtime(self) -> _RetryRuntime:
        return self._runtime
