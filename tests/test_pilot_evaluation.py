"""Synthetic metadata and fake services only: never decode media or load weights."""
from __future__ import annotations

import itertools
import json
import random
import socket
import subprocess
import sys
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from evaluation.pilot.__main__ import main
from evaluation.pilot.manifest import Clip, Manifest, file_digest, load_manifest
from evaluation.pilot.metrics import aggregate, evaluate_clip, maximum_matching
from evaluation.pilot.observability import Journal, PrefilterObserver, attach_observers
from evaluation.pilot.report import score_attempts, save_report
from evaluation.pilot.runner import resolve_settings, run_attempt, write_new
from services.analysis.contracts import (
    AnalysisRecord, AnalysisSettings, AnalysisStatus, MediaSummary, PrefilterFrameScore,
    PreflightResult, SampledFrame, TextEvidenceOutput, VisualBatch, VLMReviewResponse,
    VLMReviewResult, VLMReviewItem,
)

FIXTURE = Path(__file__).parent / "fixtures/pilot/synthetic.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access forbidden in synthetic pilot tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def clip_with(events=None, exclusions=None):
    payload = load_manifest(FIXTURE).clips[0].model_dump()
    if events is not None:
        payload["events"] = [{"event_id": f"e{i}", "start_seconds": a, "end_seconds": b,
                              "categories": categories, "notes": "synthetic"}
                             for i, (a, b, categories) in enumerate(events)]
    if exclusions is not None:
        payload["excluded_intervals"] = [{"exclusion_id": f"x{i}", "start_seconds": a,
                                         "end_seconds": b, "kind": "ambiguous", "reason": "synthetic"}
                                        for i, (a, b) in enumerate(exclusions)]
    return Clip.model_validate(payload)


def prediction(start=2.0, end=4.0, identifier="p", category="nudity"):
    return {"id": identifier, "start_seconds": start, "end_seconds": end, "category": category}


def primary(clip, predictions):
    return evaluate_clip(clip, predictions)["event_metrics"]["0.50"]


def test_perfect_prediction():
    result = evaluate_clip(clip_with(), [prediction()])
    assert result["event_metrics"]["0.50"]["f1"] == 1
    assert result["target_coverage"] == result["temporal_precision"] == 1
    assert result["event_metrics"]["0.50"]["matches"][0]["start_error_seconds"] == 0


def test_completely_missed_event():
    result = evaluate_clip(clip_with(), [])
    assert result["event_metrics"]["0.50"]["fn"] == 1
    assert result["event_metrics"]["0.50"]["precision"] is None
    assert result["missed_target_seconds"] == 2
    assert result["target_coverage"] == 0


def test_negative_false_positive():
    result = evaluate_clip(clip_with([]), [prediction()])
    assert result["event_metrics"]["0.50"]["negative_only_false_alerts_per_minute"] == 6
    assert result["excess_ordinary_seconds"] == 2
    assert result["target_coverage"] is None
    assert "tn" not in result["event_metrics"]["0.50"]


def test_duplicate_predictions():
    result = primary(clip_with(), [prediction(identifier="a"), prediction(identifier="b")])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 0)
    assert result["matches"][0]["prediction_id"] == "a"


def test_one_prediction_covering_two_distinct_events():
    clip = clip_with([(1.0, 2.0, ["nudity"]), (3.0, 4.0, ["nudity"])])
    result = evaluate_clip(clip, [prediction(1.0, 4.0)])
    assert result["event_metrics"]["0.25"]["tp"] == 1
    assert result["event_metrics"]["0.25"]["fn"] == 1
    assert result["event_metrics"]["0.50"]["tp"] == 0
    assert result["target_coverage"] == 1
    assert result["excess_ordinary_seconds"] == 1


def test_fragmented_prediction():
    result = primary(clip_with(), [prediction(2.0, 3.0, "a"), prediction(3.0, 4.0, "b")])
    assert (result["tp"], result["fp"], result["fn"]) == (1, 1, 0)


def test_overlapping_categories_binary_and_category_independent():
    clip = clip_with([(2.0, 4.0, ["nudity"]), (3.0, 5.0, ["sexual_activity"])])
    predictions = [prediction(2.0, 5.0)]
    assert primary(clip, predictions)["tp"] == 1
    result = evaluate_clip(clip, predictions, "sexual_activity")
    assert result["event_metrics"]["0.50"]["fn"] == 1
    assert evaluate_clip(clip, predictions)["target_seconds"] == 3


def test_uncertain_is_alert_not_truth():
    assert primary(clip_with(), [prediction(category="uncertain")])["tp"] == 1
    assert evaluate_clip(clip_with(), [prediction(category="uncertain")], "nudity")["event_metrics"]["0.50"]["fn"] == 1
    with pytest.raises(ValidationError):
        clip_with([(2.0, 4.0, ["uncertain"])])


def test_zero_zero_metrics_are_unavailable():
    result = primary(clip_with([]), [])
    assert all(result[key] is None for key in ("precision", "recall", "f1"))
    assert result["false_alerts_per_minute"] == 0


@pytest.mark.parametrize("start,end", [(2.0, 2.0), (3.0, 2.0), (-1.0, 2.0), (1.0, 11.0),
                                      (float("nan"), 2.0), (0.0, float("inf")), (True, 4.0)])
def test_invalid_boundaries(start, end):
    with pytest.raises(ValidationError):
        clip_with([(start, end, ["nudity"])])
    with pytest.raises(ValueError):
        evaluate_clip(clip_with(), [prediction(start, end)])


def test_exclusions_keep_one_identity_and_mask_time():
    clip = clip_with([(2.0, 8.0, ["nudity"])], [(4.0, 6.0)])
    result = evaluate_clip(clip, [prediction(2.0, 8.0)])
    assert result["event_metrics"]["0.50"]["tp"] == 1
    assert result["target_seconds"] == 4
    assert result["evaluated_seconds"] == 8
    assert result["event_metrics"]["0.50"]["matches"][0]["iou"] == 1


def test_fully_masked_and_boundary_unavailable():
    result = evaluate_clip(clip_with(exclusions=[(0.0, 10.0)]), [prediction()])
    assert result["ignored_prediction_ids"] == ["p"]
    assert len(result["ignored_event_ids"]) == 1
    assert result["event_metrics"]["0.50"]["false_alerts_per_minute"] is None
    result = evaluate_clip(clip_with(exclusions=[(2.0, 3.0)]), [prediction()])
    assert result["event_metrics"]["0.50"]["matches"][0]["start_error_seconds"] is None


def test_aggregate_uses_durations_not_mean_percentages():
    positive = evaluate_clip(clip_with(), [prediction()])
    negative = evaluate_clip(clip_with([]), [prediction(0.0, 8.0)])
    result = aggregate([positive, negative])
    assert result["temporal_precision"] == 0.2
    assert result["event_metrics"]["0.50"]["negative_only_false_alerts_per_minute"] == 6


def _vertices(count):
    return [{"id": str(i), "segments": i, "start": 0, "end": 1,
             "start_observable": True, "end_observable": True} for i in range(count)]


def test_matching_cardinality_then_weight_and_deterministic_ties(monkeypatch):
    matrix = [[0.9, 0.5], [0.5, 0.0]]
    monkeypatch.setattr("evaluation.pilot.metrics.iou", lambda a, b: matrix[a][b])
    matches = maximum_matching(_vertices(2), _vertices(2), 0.5)
    assert len(matches) == 2
    matrix[:] = [[0.9, 0.8], [0.85, 0.4]]
    matches = maximum_matching(_vertices(2), _vertices(2), 0.25)
    assert sum(m["iou"] for m in matches) == pytest.approx(1.65)
    matrix[:] = [[0.5, 0.5], [0.5, 0.5]]
    baseline = maximum_matching(_vertices(2), _vertices(2), 0.5)
    assert maximum_matching(list(reversed(_vertices(2))), _vertices(2), 0.5) == baseline


def test_matching_against_exhaustive_small_oracle(monkeypatch):
    generator = random.Random(730)
    for _ in range(40):
        matrix = [[generator.choice([0.0, 0.25, 0.5, 0.75, 1.0]) for _ in range(3)] for _ in range(3)]
        monkeypatch.setattr("evaluation.pilot.metrics.iou", lambda a, b: matrix[a][b])
        actual = maximum_matching(_vertices(3), _vertices(3), 0.25)
        candidates = []
        for choices in itertools.product(range(-1, 3), repeat=3):
            used = [g for g in choices if g >= 0]
            if len(used) != len(set(used)):
                continue
            if any(g >= 0 and matrix[p][g] < 0.25 for p, g in enumerate(choices)):
                continue
            candidates.append((len(used), sum((Fraction(matrix[p][g]) for p, g in enumerate(choices) if g >= 0), Fraction(0))))
        assert (len(actual), sum((Fraction(m["iou"]) for m in actual), Fraction(0))) == max(candidates)


def test_manifest_drafts_unknown_fields_and_source_leakage():
    path = Path("evaluation/pilot/templates/six_clips.blank.json")
    assert len(load_manifest(path, allow_draft=True).clips) == 6
    with pytest.raises(ValueError, match="Non-exhaustive"):
        load_manifest(path)
    data = load_manifest(FIXTURE).model_dump()
    data["unexpected"] = 1
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)
    data.pop("unexpected")
    duplicate = {**data["clips"][0], "clip_id": "different", "split": "test"}
    data["clips"].append(duplicate)
    with pytest.raises(ValidationError, match="leakage"):
        Manifest.model_validate(data)


def test_validate_only_never_opens_media_or_imports_pipeline(monkeypatch, capsys):
    monkeypatch.setattr("evaluation.pilot.runner.production_pipeline", Mock(side_effect=AssertionError("no pipeline")))
    monkeypatch.setattr("evaluation.pilot.runner.environment_metadata", Mock(side_effect=AssertionError("no ffmpeg")))
    monkeypatch.setattr("evaluation.pilot.manifest.file_digest", Mock(side_effect=AssertionError("no media")))
    assert main(["validate-only", str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)["inference_executed"] is False


@pytest.mark.parametrize("mode", ["fast", "balanced", "thorough"])
def test_parameter_parity_with_application(tmp_path, mode):
    from controllers.app.app_controller import _analysis_settings_from_app_settings
    from models.app_settings import AppSettings
    app = AppSettings(ai_analysis_mode=mode, confidence_threshold=0.63,
                      ai_visual_batch_size=3, ai_scene_threshold=0.42,
                      ai_merge_gap_seconds=2.0, ai_context_padding_seconds=0.8,
                      enable_gpu=False, ai_sample_rate_fps=4.0)
    path = tmp_path / "app.json"
    write_new(path, app.model_dump(mode="json"))
    settings, _ = resolve_settings(path)
    assert settings == _analysis_settings_from_app_settings(app)
    assert settings.sample_rate_fps is None  # legacy app field deliberately ignored
    assert settings.prefilter_candidate_threshold == 0.15
    assert settings.visual_confidence_threshold == 0.63


def test_configuration_overrides_are_validated(tmp_path):
    path = tmp_path / "settings.json"
    write_new(path, {})
    with pytest.raises(ValidationError):
        resolve_settings(path, {"made_up_setting": 1})
    settings, _ = resolve_settings(path, {"prefilter_candidate_threshold": 0.25})
    assert settings.visual_confidence_threshold == 0.5
    assert settings.prefilter_candidate_threshold == 0.25
    with pytest.raises(ValueError, match="cannot change production"):
        resolve_settings(path, {"model_revision": "main"})


def synthetic_manifest(tmp_path):
    media = tmp_path / "synthetic.bin"
    media.write_bytes(b"synthetic metadata fixture, NOT video")
    data = load_manifest(FIXTURE).model_dump()
    data["clips"][0].update(file_path=media.name, sha256=file_digest(media))
    return Manifest.model_validate(data), tmp_path / "manifest.json"


def fake_pipeline_factory(outcomes, references, observed=True):
    def factory(cache, journal):
        from services.analysis.pipeline import AnalysisPipeline, AnalysisServices, _invoke_fixed_sequence
        from services.analysis.tracing import OptionalLangSmithTracer
        from services.analysis.providers.base import VLMProviderUnavailableError, VLMStructuredOutputError

        class Preflight:
            def run(self, path, settings, cancellation, *args, **kwargs):
                cancellation.raise_if_cancelled()
                fingerprint = "sha256:" + file_digest(path)
                return path, PreflightResult(video_fingerprint=fingerprint,
                    media=MediaSummary(duration_seconds=10.0, fps=25.0),
                    cache_key=cache.make_key(fingerprint, settings))

        class Sampling:
            def sample_coarse(self, *args):
                return [SampledFrame(timestamp_seconds=t, path=Path("nonexistent.jpg"), source="interval")
                        for t in (2.5, 6.5)]

            def refine_candidates(self, path, workspace, duration, settings, candidates, frames, *args):
                return frames, [VisualBatch(batch_id=f"b{i}", start_seconds=f.timestamp_seconds - 0.5,
                                            end_seconds=f.timestamp_seconds + 0.5, frames=[f],
                                            candidate_window_id=candidates[0].window_id)
                                for i, f in enumerate(frames)]

        class Prefilter:
            warnings = []

            def score_frames(self, frames, *args):
                references["marqo_calls"] = references.get("marqo_calls", 0) + 1
                return [PrefilterFrameScore(frame=f, nsfw_probability=0.9) for f in frames]

            def release(self):
                pass

        class Provider:
            warnings = []

            def review_batch(self, batch, settings, cancellation):
                outcome = outcomes.get(batch.batch_id, "complete")
                if outcome == "fail":
                    raise VLMStructuredOutputError("synthetic invalid", raw_output="DO NOT RETAIN")
                if outcome == "unavailable":
                    raise VLMProviderUnavailableError("synthetic unavailable")
                if outcome == "cancel":
                    cancellation.cancel()
                    cancellation.raise_if_cancelled()
                suggestions = []
                if outcome == "positive":
                    suggestions = [VLMReviewItem(category="nudity", confidence=0.9,
                        start_seconds=batch.start_seconds, end_seconds=batch.end_seconds,
                        evidence_timestamps=[f.timestamp_seconds for f in batch.frames],
                        reason="SENSITIVE_NOTE", needs_review=True)]
                return VLMReviewResult(response=VLMReviewResponse(suggestions=suggestions),
                                       repaired=outcome == "repair", raw_output="DO NOT RETAIN")

        services = AnalysisServices(cache=cache, preflight=Preflight(),
            text_evidence=SimpleNamespace(gather=lambda *a, **kw: TextEvidenceOutput()),
            visual_sampling=Sampling(), prefilter=Prefilter(), provider=Provider(),
            tracer=OptionalLangSmithTracer(enabled=False))
        original_prefilter = services.prefilter
        pipeline = AnalysisPipeline(attach_observers(services, journal) if observed else services)
        if observed:
            assert pipeline.services.prefilter.service is original_prefilter
        # Actual run() and production nodes; optional LangGraph orchestration only is mocked.
        pipeline._invoke_graph = lambda state: _invoke_fixed_sequence(state, pipeline.services)
        references["cache"] = cache
        references["pipeline"] = pipeline
        return pipeline
    return factory


def synthetic_attempt(tmp_path, outcomes=None):
    manifest, path = synthetic_manifest(tmp_path)
    references = {}
    directory, summary = run_attempt(manifest, path, manifest.clips[0], AnalysisSettings(), tmp_path / "runs",
                                    pipeline_factory=fake_pipeline_factory(outcomes or {}, references),
                                    metadata_factory=lambda: {"synthetic": True})
    return manifest, directory, summary, references


def test_partial_pipeline_actual_run_and_marqo_preservation(tmp_path):
    manifest, directory, summary, references = synthetic_attempt(tmp_path, {"b0": "fail", "b1": "repair"})
    assert summary["status"] == "partial"
    assert references["marqo_calls"] == 1
    assert summary["reliability"]["invalid_responses"] == 2
    assert summary["reliability"]["repaired_responses"] == 1
    record = AnalysisRecord.model_validate_json((directory / "record.json").read_text())
    assert record.status == AnalysisStatus.PARTIAL
    assert record.metrics["failed_batches"] == 1
    assert summary["pipeline_seconds"] >= 0
    assert summary["real_time_factor"] == summary["pipeline_seconds"] / 10
    for path in directory.rglob("*.json*"):
        assert "DO NOT RETAIN" not in path.read_text(encoding="utf-8")
    assert not list(directory.rglob("*.jpg"))
    report = score_attempts(manifest, [directory])
    assert report["reliability"]["tuning"]["partial"] == 1
    assert next(g for g in report["aggregates"] if g["population"] == "completed_only")["clip_count"] == 0


def test_unprocessed_batches_and_cancellation(tmp_path):
    _, _, summary, _ = synthetic_attempt(tmp_path, {"b0": "unavailable"})
    assert summary["reliability"]["unprocessed_batches"] == 1
    _, _, summary, _ = synthetic_attempt(tmp_path, {"b0": "cancel"})
    assert summary["status"] == "cancelled"
    assert summary["reliability"]["cancelled_batches"] == 1


def test_cache_isolation_record_preservation_and_no_overwrite(tmp_path):
    _, directory, summary, refs = synthetic_attempt(tmp_path)
    original = (directory / "record.json").read_bytes()
    _, second, partial, second_refs = synthetic_attempt(tmp_path, {"b0": "fail"})
    assert directory != second
    assert refs["cache"].root != second_refs["cache"].root
    assert summary["status"] == "completed" and partial["status"] == "partial"
    assert (directory / "record.json").read_bytes() == original
    with pytest.raises(FileExistsError):
        write_new(directory / "record.json", {})


def test_returned_record_not_cached_record(tmp_path):
    manifest, path = synthetic_manifest(tmp_path)
    returned = AnalysisRecord(video_fingerprint="sha256:" + manifest.clips[0].sha256,
        model_id="synthetic", model_revision="synthetic", settings_version=2,
        settings=AnalysisSettings().model_dump(mode="json"), status=AnalysisStatus.PARTIAL,
        started_at=datetime.now(UTC), errors=["synthetic current failure"])
    def factory(cache, journal):
        cache.load = Mock(side_effect=AssertionError("must not fetch cached result"))
        return SimpleNamespace(run=lambda *a, **k: returned)
    directory, summary = run_attempt(manifest, path, manifest.clips[0], AnalysisSettings(), tmp_path / "runs",
                                    pipeline_factory=factory, metadata_factory=lambda: {})
    assert json.loads((directory / "record.json").read_text()) == returned.model_dump(mode="json")


def test_conservative_fallback_not_a_model_probability(tmp_path):
    frame = SampledFrame(timestamp_seconds=1.0, path=Path("absent.jpg"), source="scene")
    score = PrefilterFrameScore(frame=frame, nsfw_probability=1.0, conservatively_included=True)
    journal = Journal(tmp_path / "events.jsonl")
    observer = PrefilterObserver(SimpleNamespace(score_frames=lambda *a: [score]), journal)
    assert observer.score_frames([frame], AnalysisSettings(), None)[0] is score
    journal.close()
    item = json.loads((tmp_path / "events.jsonl").read_text())["scores"][0]
    assert item["model_probability"] is None and item["decision_score"] == 1
    assert item["conservatively_included"] and item["origin"] == "scene"


def test_production_construction_preserves_marqo_without_loading_models(tmp_path):
    from evaluation.pilot.observability import PrivateEvaluationCache
    from evaluation.pilot.runner import production_pipeline
    from services.analysis.prefilter import LocalNSFWPrefilter
    from services.analysis.providers.qwen import LocalQwenVLProvider
    journal = Journal(tmp_path / "events.jsonl")
    pipeline = production_pipeline(PrivateEvaluationCache(tmp_path / "cache"), journal)
    assert isinstance(pipeline.services.prefilter.service, LocalNSFWPrefilter)
    assert isinstance(pipeline.services.provider.service, LocalQwenVLProvider)
    journal.close()


def test_missing_file_failed_attempt_has_no_fake_record(tmp_path):
    manifest = load_manifest(FIXTURE)
    directory, summary = run_attempt(manifest, tmp_path / "manifest.json", manifest.clips[0],
        AnalysisSettings(), tmp_path / "runs", pipeline_factory=Mock(side_effect=AssertionError("no pipeline")),
        metadata_factory=lambda: {})
    assert summary["status"] == "failed" and not summary["record_available"]
    assert not (directory / "record.json").exists()
    assert score_attempts(manifest, [directory])["reliability"]["tuning"]["quality_unavailable"] == 1


def test_offline_report_identity_duplicate_selection_and_csv(tmp_path):
    manifest, directory, _, _ = synthetic_attempt(tmp_path)
    report = score_attempts(manifest, [directory])
    output = tmp_path / "report"
    save_report(report, output)
    assert (output / "metrics.json").is_file() and (output / "clips.csv").is_file()
    with pytest.raises(FileExistsError):
        save_report(report, output)
    with pytest.raises(ValueError, match="one attempt"):
        score_attempts(manifest, [directory, directory])
    payload = manifest.model_dump()
    payload["clips"][0]["annotation_version"] = "changed"
    with pytest.raises(ValueError, match="identity mismatch"):
        score_attempts(Manifest.model_validate(payload), [directory])


def test_cli_refuses_inference_without_explicit_flag(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["run", str(FIXTURE), "--clip", "synthetic_01", "--output", str(tmp_path / "runs")])
    assert error.value.code == 2
    assert not (tmp_path / "runs").exists()


def test_validate_only_fresh_process_without_ai_qt_or_subprocess_access():
    script = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'PySide6', 'huggingface_hub', 'subprocess'}:
        raise AssertionError('Forbidden import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from evaluation.pilot.__main__ import main
raise SystemExit(main(['validate-only', 'tests/fixtures/pilot/synthetic.json']))
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inference_executed"] is False


def test_observers_and_private_cache_do_not_change_positive_result(tmp_path):
    manifest, path = synthetic_manifest(tmp_path)
    records = []
    for observed in (False, True):
        directory, summary = run_attempt(manifest, path, manifest.clips[0], AnalysisSettings(), tmp_path / "runs",
            pipeline_factory=fake_pipeline_factory({"b0": "positive"}, {}, observed=observed),
            metadata_factory=lambda: {})
        assert summary["status"] == "completed"
        record = json.loads((directory / "record.json").read_text())
        assert record["suggestions"] and "SENSITIVE_NOTE" in (directory / "record.json").read_text()
        records.append({k: v for k, v in record.items() if k not in ("started_at", "completed_at")})
        for artifact in (directory / "cache").rglob("*.json"):
            assert "SENSITIVE_NOTE" not in artifact.read_text()
        assert "SENSITIVE_NOTE" not in (directory / "observations.jsonl").read_text()
    assert records[0] == records[1]


def test_hash_mismatch_is_recorded_before_pipeline(tmp_path):
    manifest, path = synthetic_manifest(tmp_path)
    payload = manifest.model_dump()
    payload["clips"][0]["sha256"] = "f" * 64
    manifest = Manifest.model_validate(payload)
    factory = Mock(side_effect=AssertionError("must not start pipeline"))
    directory, summary = run_attempt(manifest, path, manifest.clips[0], AnalysisSettings(), tmp_path / "runs",
                                    pipeline_factory=factory, metadata_factory=lambda: {})
    assert summary["error_code"] == "clip_sha256_mismatch"
    assert summary["status"] == "failed" and summary["pipeline_seconds"] is None
    factory.assert_not_called()


def test_hard_interruption_is_unknown_not_a_success(tmp_path):
    manifest, directory, _, _ = synthetic_attempt(tmp_path)
    (directory / "summary.json").unlink()  # Simulate crash using ONLY the test's temporary artifact.
    report = score_attempts(manifest, [directory])
    assert report["reliability"]["tuning"]["interrupted_unknown"] == 1
    assert report["clips"] == []


def test_annotation_categories_match_production():
    from services.analysis.contracts import NSFWCategory
    from evaluation.pilot.metrics import CATEGORIES
    assert set(CATEGORIES) == {item.value for item in NSFWCategory} - {"uncertain"}


@pytest.mark.parametrize("change", [{"schema_version": True}, {"schema_version": 2}])
def test_manifest_version_is_strict(change):
    payload = load_manifest(FIXTURE).model_dump()
    with pytest.raises(ValidationError):
        Manifest.model_validate({**payload, **change})


def test_url_is_not_a_clip_path():
    payload = clip_with().model_dump()
    with pytest.raises(ValidationError, match="local file path"):
        Clip.model_validate({**payload, "file_path": "https://example.invalid/video.mp4"})


def test_timeout_after_invalid_response_retains_typed_evidence(tmp_path):
    from evaluation.pilot.observability import ProviderObserver
    from services.analysis.providers.base import VLMStructuredOutputError, VLMProviderTimeoutError
    journal = Journal(tmp_path / "observations.jsonl")
    def review(*args):
        try:
            raise VLMStructuredOutputError("private text")
        except VLMStructuredOutputError as exc:
            raise VLMProviderTimeoutError("private repair", stop_reason="timeout") from exc
    observer = ProviderObserver(SimpleNamespace(review_batch=review), journal)
    frame = SampledFrame(timestamp_seconds=2.0, path=Path("not-an-image.jpg"), source="interval")
    batch = VisualBatch(batch_id="b", start_seconds=1.0, end_seconds=3.0, frames=[frame])
    with pytest.raises(VLMProviderTimeoutError):
        observer.review_batch(batch, AnalysisSettings(), None)
    assert journal.reliability()["invalid_responses"] == 1
    journal.close()
    text = (tmp_path / "observations.jsonl").read_text()
    assert "private" not in text and "timeout" in text
