"""No weights, decoding, subprocess media tools, or network in synthetic tests."""
import io
import socket
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evaluation.technical import benchmark as b
from evaluation.technical.__main__ import main
from services.analysis.contracts import AnalysisRecord, MediaSummary

PROPOSAL = b.ROOT / "evaluation/proposals/ucf101_technical25.v1.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))


@pytest.fixture
def manifest():
    return b.proposal(PROPOSAL)


@pytest.fixture
def clearance(tmp_path):
    p = tmp_path / "clearance.json"
    b.write_new(p, {"dataset": "UCF101", "reviewed_by": "SYNTHETIC TEST ONLY", "reviewed_at": "2026-10-18",
                   "terms_source": "synthetic", "permitted_operations": ["download", "prepare", "inference"]})
    return p


def metadata(duration=10.0):
    return {"duration_seconds": duration, "format_name": "matroska,webm",
            "streams": [{"codec_type": "video", "codec_name": "mpeg4"}],
            "packets": [{"stream_index": 0, "pts_time": "0.000", "data_hash": "SHA256:fake"}]}


@pytest.fixture
def prepared(tmp_path, manifest):
    rows = []
    for index, c in enumerate(manifest["clips"]):
        video = tmp_path / (c["clip_id"] + ".mkv")
        video.write_bytes(f"fake media {index}".encode())
        rows.append(b.PreparedClip(clip_id=c["clip_id"], source_url=c["source_url"], original_path=str(video),
                    original_sha256=b.file_digest(video), evaluated_path=str(video), evaluated_sha256=b.file_digest(video),
                    duration_seconds=10.0, media=metadata(), original_media=metadata(), operation="identity"))
    path = tmp_path / "prepared.json"
    b.write_new(path, b.Prepared(schema_version=1, proposal_sha256=b.PROPOSAL_DIGEST, clearance={}, clips=rows).model_dump())
    return path


def factory(status="completed", calls=None):
    def create(cache, journal):
        if calls is not None:
            calls.append(cache)
        journal.planned = {"b"}
        journal.started_batches.add("b")
        journal.finished["b"] = {"status": "failed" if status == "partial" else "completed", "invalid": False, "repaired": False}
        def run(request, **kwargs):
            return AnalysisRecord(video_fingerprint="sha256:" + b.file_digest(request.video_path),
                model_id=request.settings.model_id, model_revision=request.settings.model_revision,
                settings_version=request.settings.settings_version, settings=request.settings.model_dump(mode="json"),
                status=status, media=MediaSummary(duration_seconds=10, fps=25), started_at=datetime.now(UTC),
                warnings=["synthetic warning"], errors=["synthetic batch failure"] if status == "partial" else [])
        return SimpleNamespace(run=run)
    return create


def run(manifest, prepared, root, clearance, **kwargs):
    return b.run(manifest, prepared, root, allow=True, clearance=clearance,
                 metadata_factory=lambda: {"synthetic": True}, **kwargs)


def test_proposal_and_configuration(manifest):
    assert len(manifest["clips"]) == 25
    assert all(manifest["ground_truth"][k] == "unknown" for k in ("nudity", "sexual_context", "sexual_activity"))
    s = b.frozen_settings()
    assert s.batch_size == 8 and s.visual_confidence_threshold == .5
    assert s.prompt_schema_revision == 3
    assert main(["validate", str(PROPOSAL)]) == 0


@pytest.mark.parametrize("change", ["label", "extra", "type", "url", "duplicate"])
def test_strict_proposal(tmp_path, manifest, change):
    if change == "label": manifest["ground_truth"]["nudity"] = "negative"
    if change == "extra": manifest["clips"][0]["events"] = []
    if change == "type": manifest["schema_version"] = True
    if change == "url": manifest["clips"][0]["source_url"] = "https://example.com/a"
    if change == "duplicate": manifest["clips"][1] = manifest["clips"][0]
    p = tmp_path / "bad.json"
    b.write_new(p, manifest)
    with pytest.raises(ValueError): b.proposal(p)


@pytest.mark.parametrize("operation", ["download", "prepare", "inference"])
def test_authorization(operation, clearance):
    with pytest.raises(ValueError): b.authorize(False, clearance, operation)
    with pytest.raises(ValueError): b.authorize(True, None, operation)
    assert b.authorize(True, clearance, operation)["sha256"]


def test_gates_before_side_effects(manifest, tmp_path):
    with pytest.raises(ValueError): b.download(manifest, tmp_path / "d")
    with pytest.raises(ValueError): b.prepare(manifest, tmp_path, tmp_path / "p")
    with pytest.raises(ValueError): b.run(manifest, tmp_path / "absent", tmp_path / "r")
    assert not list(tmp_path.iterdir())


def test_prepared_identity(manifest, prepared):
    data = b.load_prepared(prepared, manifest)
    Path(data.clips[0].evaluated_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA"): b.load_prepared(prepared, manifest)


@pytest.mark.parametrize("field,value", [("duration_seconds", -1), ("duration_seconds", float("inf")),
                                        ("original_sha256", "bad"), ("events", [])])
def test_prepared_strict(field, value, prepared):
    payload = b.read(prepared)["clips"][0]
    payload[field] = value
    with pytest.raises(ValueError): b.PreparedClip.model_validate(payload)


def test_remux_checks():
    before, after = metadata(), metadata()
    b.verify_remux(before, after)
    after["packets"][0]["pts_time"] = "1"
    with pytest.raises(ValueError): b.verify_remux(before, after)
    after = metadata()
    after["packets"][0]["data_hash"] = "different"
    with pytest.raises(ValueError): b.verify_remux(before, after)
    after = metadata()
    after["streams"] = []
    with pytest.raises(ValueError): b.verify_remux(before, after)


def test_prepare_with_mock_media(tmp_path, manifest, clearance):
    # Preserve 25 identities but use explicitly fake sizes in this unit-level fixture.
    for c in manifest["clips"]:
        payload = c["clip_id"].encode()
        c["http_content_length_bytes"] = len(payload)
        (tmp_path / c["source_filename"]).write_bytes(payload)
    def fake_remux(source, target):
        with target.open("xb") as stream: stream.write(source.read_bytes())
    directory = b.prepare(manifest, tmp_path, tmp_path / "out", allow=True, clearance=clearance,
                          probe_fn=lambda _: metadata(), remux_fn=fake_remux)
    data = b.load_prepared(directory / "prepared.json", manifest)
    assert len(data.clips) == 25
    assert all(c.operation == "stream_copy_remux" for c in data.clips)


def test_campaign_complete_resume_and_isolation(manifest, prepared, tmp_path, clearance):
    root, calls = tmp_path / "campaign", []
    result = run(manifest, prepared, root, clearance, pipeline_factory=factory(calls=calls))
    assert result["completed_clips"] == result["attempted_clips"] == 25
    assert result["technical_success_rate"] == 1
    assert result["overall_rtf_completed"] == result["completed_pipeline_seconds"] / 250
    assert len(list((root / "attempts").glob("*/cache"))) == 25
    old = {str(p): b.file_digest(p) for p in (root / "attempts").rglob("*.json")}
    result2 = run(manifest, prepared, root, clearance, pipeline_factory=Mock(side_effect=AssertionError("rerun")))
    assert result2["attempt_count"] == 25
    assert old == {str(p): b.file_digest(p) for p in (root / "attempts").rglob("*.json")}
    assert result["completed_qwen_batches"]["completed_batches"]["observed_total"] == 25
    assert not {"precision", "recall", "F1", "TP", "FP", "FN"} & result.keys()


@pytest.mark.parametrize("status", ["partial", "failed", "cancelled"])
def test_stops_and_explicit_retry(status, manifest, prepared, tmp_path, clearance):
    root = tmp_path / "campaign"
    result = run(manifest, prepared, root, clearance, pipeline_factory=factory(status))
    assert result["attempted_clips"] == 1 and result["unattempted_clips"] == 24
    assert result["latest_attempts"][0]["status"] == status
    with pytest.raises(ValueError, match="retry-incomplete"):
        run(manifest, prepared, root, clearance, pipeline_factory=factory())
    result = run(manifest, prepared, root, clearance, retry_incomplete=True, pipeline_factory=factory())
    assert result["attempt_count"] == 26 and result["completed_clips"] == 25


def test_interrupted_recovery(manifest, prepared, tmp_path, clearance):
    root = tmp_path / "campaign"
    run(manifest, prepared, root, clearance, pipeline_factory=factory("partial"))
    # Simulate process termination before summary publication (synthetic fixtures only).
    next((root / "attempts").glob("*/summary.json")).unlink()
    assert b.report(manifest, root)["status_counts"]["interrupted_unknown"] == 1
    with pytest.raises(ValueError): run(manifest, prepared, root, clearance, pipeline_factory=factory())
    result = run(manifest, prepared, root, clearance, retry_incomplete=True, pipeline_factory=factory())
    assert result["interrupted_runtime_unknown"] and result["attempt_count"] == 26


def test_no_overwrite(tmp_path):
    path = tmp_path / "record.json"
    b.write_new(path, {"original": True})
    with pytest.raises(FileExistsError): b.write_new(path, {})
    assert b.read(path) == {"original": True}


def test_union_and_invalid_intervals():
    assert b.flagged_seconds([{"start_seconds": 0, "end_seconds": 4},
                              {"start_seconds": 2, "end_seconds": 6}], 10) == 6
    with pytest.raises(ValueError): b.flagged_seconds([{"start_seconds": 0, "end_seconds": 11}], 10)


def test_record_tamper(manifest, prepared, tmp_path, clearance):
    root = tmp_path / "campaign"
    run(manifest, prepared, root, clearance, pipeline_factory=factory("partial"))
    next((root / "attempts").glob("*/record.json")).write_text("{}")
    with pytest.raises(ValueError, match="integrity"): b.report(manifest, root)


def test_exclusive_campaign_lock(tmp_path):
    with b.campaign_lock(tmp_path):
        with pytest.raises(OSError):
            with b.campaign_lock(tmp_path): pass


def test_report_weighted_runtime(monkeypatch, manifest, tmp_path):
    b.write_new(tmp_path / "campaign.json", {"proposal_sha256": b.PROPOSAL_DIGEST, "configuration_sha256": b.CONFIG_DIGEST})
    rows = []
    for i, (duration, runtime) in enumerate([(10, 20), (90, 45)]):
        rows.append({"clip_id": manifest["clips"][i]["clip_id"], "status": "completed", "duration_seconds": duration,
                     "pipeline_seconds": runtime, "runner_seconds": runtime + 1, "suggestions": [{}],
                     "flagged_seconds": duration / 2, "candidate_windows": 1,
                     "reliability": {"planned_batches": 1, "completed_batches": 1, "failed_batches": 0}})
    monkeypatch.setattr(b, "history", lambda _: rows)
    result = b.report(manifest, tmp_path)
    assert result["overall_rtf_completed"] == .65
    assert result["suggestions_per_video_hour"] == 72
    assert result["fraction_video_duration_flagged"] == .5


def test_download_mock_only(manifest, tmp_path, clearance):
    for c in manifest["clips"]: c["http_content_length_bytes"] = 4
    def opener(url, **kwargs):
        response = io.BytesIO(b"fake")
        response.geturl = lambda: url
        return response
    directory = b.download(manifest, tmp_path / "downloads", allow=True, clearance=clearance, opener=opener)
    assert len(b.read(directory / "download.json")["files"]) == 25
    second = b.download(manifest, tmp_path / "downloads", allow=True, clearance=clearance, opener=opener)
    assert directory != second


def test_download_refuses_redirect(manifest, tmp_path, clearance):
    def opener(url, **kwargs):
        response = io.BytesIO(b"fake")
        response.geturl = lambda: "https://other.invalid/video"
        return response
    with pytest.raises(ValueError, match="redirect"):
        b.download(manifest, tmp_path, allow=True, clearance=clearance, opener=opener)
    assert not list(tmp_path.rglob("*.avi"))


@pytest.mark.parametrize("change", ["url", "order", "metadata", "duration", "duplicate"])
def test_prepared_provenance_changes(manifest, prepared, change):
    data = b.read(prepared)
    if change == "url": data["clips"][0]["source_url"] = "https://other.invalid/a"
    if change == "order": data["clips"].reverse()
    if change == "metadata": data["clips"][0]["media"]["nsfw_label"] = "negative"
    if change == "duration": data["clips"][0]["duration_seconds"] = 12.0
    if change == "duplicate": data["clips"][1]["original_sha256"] = data["clips"][0]["original_sha256"]
    alternate = prepared.with_name("alternate.json")
    b.write_new(alternate, data)
    with pytest.raises(ValueError): b.load_prepared(alternate, manifest)


def test_pipeline_exception_is_saved(manifest, prepared, tmp_path, clearance):
    def failing(cache, journal):
        return SimpleNamespace(run=Mock(side_effect=RuntimeError("private raw content")))
    root = tmp_path / "campaign"
    result = run(manifest, prepared, root, clearance, pipeline_factory=failing)
    assert result["latest_attempts"][0]["error_type"] == "RuntimeError"
    assert "private raw content" not in str(result)
    assert result["status_counts"]["failed"] == 1


def test_changed_environment_blocks_resume(manifest, prepared, tmp_path, clearance):
    root = tmp_path / "campaign"
    run(manifest, prepared, root, clearance, pipeline_factory=factory("partial"))
    with pytest.raises(ValueError, match="provenance"):
        b.run(manifest, prepared, root, allow=True, clearance=clearance, retry_incomplete=True,
              pipeline_factory=factory(), metadata_factory=lambda: {"dependencies": {"mock": "changed"}})


def test_validation_does_not_import_ai_runtime():
    # A fresh process checks the offline CLI import boundary, not model inference.
    import subprocess
    import sys
    code = ("import sys; from evaluation.technical.__main__ import main; "
            f"main(['validate', {str(PROPOSAL)!r}]); "
            "assert not {'torch','transformers','services.analysis.pipeline','evaluation.pilot.metrics'} & sys.modules.keys()")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


@pytest.mark.parametrize("operation", ["download", "prepare", "run"])
def test_cli_authorization(operation, tmp_path):
    args = [operation, str(PROPOSAL)]
    if operation != "run": args += ["--output", str(tmp_path / "out")]
    if operation == "prepare": args += ["--media-root", str(tmp_path)]
    if operation == "run": args += ["--campaign", str(tmp_path / "campaign"), "--prepared", str(tmp_path / "absent")]
    with pytest.raises(SystemExit) as exc: main(args)
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())


def test_duplicate_json_keys(tmp_path):
    p = tmp_path / "duplicate.json"
    p.write_text('{"x": 1, "x": 2}')
    with pytest.raises(ValueError, match="Duplicate"): b.read(p)


def test_partial_summary_recovery(manifest, prepared, tmp_path, clearance):
    root = tmp_path / "campaign"
    run(manifest, prepared, root, clearance, pipeline_factory=factory("partial"))
    summary = next((root / "attempts").glob("*/summary.json"))
    summary.write_text('{"clip_id":')
    result = run(manifest, prepared, root, clearance, retry_incomplete=True, pipeline_factory=factory())
    assert result["completed_clips"] == 25
    assert result["all_attempts"][0]["summary_unreadable"]
    assert summary.read_text() == '{"clip_id":'
