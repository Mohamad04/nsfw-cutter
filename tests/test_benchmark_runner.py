"""Runner integration tests with mocked model outputs and synthetic, non-sensitive media only."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from pydantic import ValidationError

from evaluation.benchmark import runner, worker
from evaluation.benchmark.atomic import write_atomic
from evaluation.benchmark.media import probe_packets
from evaluation.benchmark.report import score
from evaluation.benchmark.results import load_results

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "tests" / "fixtures" / "pilot" / "synthetic.json"
FFMPEG = ROOT / "vendor" / "ffmpeg" / "bin"
UNKNOWN = {"nudity": "unknown", "sexual_activity": "unknown", "sexual_context": "unknown"}
NOT_APPLICABLE = "Text evidence not applicable: no audio stream and no usable selected subtitles."
FAST = runner.Limits(attempt_timeout_seconds=20, cancel_grace_seconds=5, sample_interval_seconds=0.01)
HEALTHY = {"process_tree_rss_bytes": 2**30, "available_bytes": 16 * 2**30, "commit_headroom_bytes": 8 * 2**30,
           "gpu_memory_mib": 3000, "gpu_utilization_percent": 50}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Status:
    def __init__(self, value):
        self.value = value


class Record:
    def __init__(self, status, settings, fingerprint, warnings, suggestions):
        self.status, self.settings, self.video_fingerprint = Status(status), settings, fingerprint
        self.warnings, self.suggestions = warnings, suggestions

    def model_dump(self, mode="json"):
        return {"status": self.status.value, "settings": self.settings, "video_fingerprint": self.video_fingerprint,
                "warnings": self.warnings, "suggestions": self.suggestions}


class MockPipeline:
    """behaviour[(input file name)] -> dict(alert, warnings, fail, wait_for_cancel, status)."""

    def __init__(self, behaviour, journal, calls):
        self.behaviour, self.journal, self.calls = behaviour, journal, calls

    def run(self, request, cancellation, event_callback, job_id):
        from services.analysis.cancellation import AnalysisCancelled
        name = Path(request.video_path).name
        self.calls.append(name)
        plan = self.behaviour.get(name, {})
        if callable(plan):
            plan = plan()
        for stage in ("preflight", "text_evidence", "visual_sampling", "vlm_review"):
            self.journal.emit("progress", stage=stage, overall_percent=0)
        self.journal.emit("marqo_scores", threshold=0.15, scores=[
            {"timestamp_seconds": 0.0, "model_probability": plan.get("marqo", 0.05), "decision_score": 0.05,
             "conservatively_included": False, "passes_gate": False, "origin": "periodic"}])
        if plan.get("wait_for_cancel"):
            if not cancellation.wait(15):
                raise RuntimeError("test did not cancel")
            raise AnalysisCancelled("cancelled")
        if plan.get("fail"):
            raise RuntimeError("synthetic failure")
        default = [NOT_APPLICABLE] if ".video-only" in name else []
        suggestions = [{"id": "s1", "start_seconds": 0.0, "end_seconds": 1.0, "category": "nudity",
                        "final_confidence": 0.9, "reason": "synthetic"}] if plan.get("alert") else []
        return Record(plan.get("status", "completed"), request.settings.model_dump(mode="json"),
                      "sha256:" + sha256(request.video_path), plan.get("warnings", default), suggestions)


class ThreadHandle:
    def __init__(self, target):
        self.thread = threading.Thread(target=target, daemon=True)
        self.pid = os.getpid()
        self.thread.start()

    def poll(self):
        return None if self.thread.is_alive() else 0

    def wait(self, timeout=None):
        self.thread.join(timeout)

    def kill(self):
        pass


class Campaign:
    """Synthetic technical-track campaign: unreviewed (missing) labels, two independent groups."""

    def __init__(self, tmp, names=("v1", "v2"), media=None, groups=None):
        self.tmp = Path(tmp)
        self.media_root = self.tmp / "media"
        self.media_root.mkdir()
        self.behaviour, self.calls = {}, []
        items = []
        for index, name in enumerate(names):
            path = self.media_root / f"{name}.mp4"
            if media is None:
                path.write_bytes(f"synthetic video {name}".encode())
            else:
                media(path)
            items.append({"item_id": name, "group_id": (groups or {}).get(name, f"subject_{index}"), "split": "test",
                          "file_name": path.name, "sha256": sha256(path), "duration_seconds": 2.0,
                          "video_label": "missing", "category_labels": UNKNOWN})
        self.manifest = self.tmp / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "benchmark_id": "runner_fixture", "track": "technical", "synthetic_fixture": True,
            "dataset": {"dataset_id": "synthetic", "name": "Synthetic", "publisher": "tests",
                        "homepage": "https://example.org/s", "version": "1", "license_id": "CC0-1.0",
                        "license_evidence": [{"url": "https://example.org/l", "retrieved": "2026-10-20",
                                              "statement": "synthetic"}],
                        "access": "ungated", "permitted_use": "tests", "redistribution_allowed": True,
                        "content": "synthetic"},
            "annotation": {"version": "0", "source": "project_annotators", "guideline": "synthetic"},
            "items": items}), encoding="utf-8")
        self.dir = self.tmp / "campaign"

    def launcher(self, spec_path):
        factory = lambda cache, journal: MockPipeline(self.behaviour, journal, self.calls)  # noqa: E731
        return ThreadHandle(lambda: worker.run_attempt(spec_path, pipeline_factory=factory))

    def identity(self):
        return {"commit": "2399e950aeb33dd7925690c78d3f5f25d50d07cb", "frozen_baseline": runner.BASELINE,
                "configuration_sha256": "c" * 64, "model_revisions": {"qwen": "q@r"}, "gpu": "Synthetic GPU, 0.0, 0 MiB",
                "runtime_sha256": "r" * 64, "environment": {"synthetic": True}}

    @staticmethod
    def fake_prepare(source, target):
        target.write_bytes(Path(source).read_bytes() + b" video-only")
        return {"sha256": sha256(target), "derived_from_sha256": sha256(source), "video_packets_verified_identical": True}

    def run(self, sampler=lambda pid: HEALTHY, limits=FAST, prepare=None, **options):
        return runner.run(self.manifest, self.media_root, self.dir, PILOT, allow_inference=True, limits=limits,
                          launcher=self.launcher, sampler=sampler, identity_factory=self.identity,
                          prepare=prepare or self.fake_prepare, preload_whisper_cuda12=False, **options)

    def collect(self, name="results.json"):
        return runner.collect(self.manifest, self.dir, PILOT, self.tmp / name)

    def attempts(self, item, config):
        return [d for d in (self.dir / "attempts").glob(f"*_{item}_{config}_*")]


class RunnerCampaignTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_paired_campaign_collects_a1_a2_and_derives_a0(self):
        c = Campaign(self.tmp)
        c.behaviour.update({"v1.mp4": {"alert": True, "marqo": 0.5}, "v2.mp4": {"marqo": 0.05}})
        self.assertEqual(c.run()["stopped_at"], None)
        results = c.collect()
        self.assertEqual(sorted((r.item_id, r.config, r.status) for r in results.results),
                         [("v1", "A1", "completed"), ("v1", "A2", "completed"),
                          ("v2", "A1", "completed"), ("v2", "A2", "completed")])
        a1 = next(r for r in results.results if (r.item_id, r.config) == ("v1", "A1"))
        self.assertTrue(a1.input.video_packets_verified_identical)
        self.assertEqual(a1.input.derived_from_sha256, sha256(c.media_root / "v1.mp4"))
        a2 = next(r for r in results.results if (r.item_id, r.config) == ("v1", "A2"))
        self.assertEqual(a2.marqo_scores[0].probability, 0.5)
        self.assertEqual(a2.start_mode, "cold_process")
        self.assertIsNotNone(a2.wall_seconds)
        # The alternating order puts A1 first for the second source video.
        self.assertEqual(c.calls, ["v1.mp4", "v1.video-only.mp4", "v2.video-only.mp4", "v2.mp4"])
        summary = json.loads(next(iter(c.attempts("v1", "A2"))).joinpath("summary.json").read_text())
        self.assertEqual(summary["whisper_backend"], "cuda_float16")
        self.assertIn("text_evidence", summary["stage_seconds"])
        report = score(load_manifest_for(c), load_results(c.tmp / "results.json"), pilot_manifest=PILOT,
                       resamples=20)
        self.assertIn("not a complete NSFW accuracy evaluation", report["scope_warning"])
        self.assertEqual(set(report["video_level"]), {"withheld"})  # unreviewed labels
        self.assertEqual(report["alert_review"]["A0@0.15"]["alerted_videos"], 1)
        self.assertEqual(report["alert_review"]["A2"]["alerts_by_reference_label"]["missing"], 1)
        # A default (two-configuration) campaign keeps its historical identity: no configs key.
        self.assertNotIn("configs", json.loads((c.dir / "campaign.json").read_text()))

    def test_a2_only_campaign_runs_and_collects_only_a2(self):
        c = Campaign(self.tmp)
        c.behaviour.update({"v1.mp4": {"alert": True, "marqo": 0.5, "warnings": [NOT_APPLICABLE]},
                            "v2.mp4": {"warnings": [NOT_APPLICABLE]}})
        prepared = []
        self.assertIsNone(c.run(configs=("A2",), prepare=lambda s, t: prepared.append(s))["stopped_at"])
        self.assertEqual(c.calls, ["v1.mp4", "v2.mp4"])
        self.assertEqual(prepared, [])  # no video-only copy without A1
        self.assertEqual(json.loads((c.dir / "campaign.json").read_text())["configs"], ["A2"])
        results = c.collect()
        self.assertEqual(sorted((r.item_id, r.config) for r in results.results), [("v1", "A2"), ("v2", "A2")])
        # A campaign created for one set of configurations cannot be continued with another.
        with self.assertRaisesRegex(ValueError, "campaign identity changed"):
            c.run()

    def test_accepted_partial_outcomes_are_recorded_never_retried_and_failures_still_stop(self):
        c = Campaign(self.tmp, names=("v1", "v2", "v3"))
        c.behaviour.update({"v1.mp4": {"status": "partial", "warnings": [NOT_APPLICABLE]},
                            "v2.mp4": {"warnings": [NOT_APPLICABLE]}, "v3.mp4": {"fail": True}})
        self.assertEqual(c.run(configs=("A2",))["stopped_at"], "v1/A2")  # default policy stops
        self.assertEqual(c.run(configs=("A2",), accept_partial=True, retry_incomplete=True)["stopped_at"], "v3/A2")
        self.assertEqual(c.calls, ["v1.mp4", "v2.mp4", "v3.mp4"])  # the recorded partial v1 is accepted, not rerun
        c.behaviour["v3.mp4"] = {"warnings": [NOT_APPLICABLE]}
        self.assertIsNone(c.run(configs=("A2",), accept_partial=True, retry_incomplete=True)["stopped_at"])
        self.assertEqual(c.calls[3:], ["v3.mp4"])  # only the failed attempt is retried
        spec = json.loads(next(iter(c.attempts("v3", "A2"))).joinpath("spec.json").read_text())
        self.assertEqual(spec["accepted_terminal_statuses"], ["completed", "partial"])
        statuses = {r.item_id: r.status for r in c.collect().results}
        self.assertEqual(statuses, {"v1": "partial", "v2": "completed", "v3": "completed"})

    def test_invalid_configuration_sets_are_refused(self):
        c = Campaign(self.tmp)
        for configs in ((), ("A1",), ("A2", "A2"), ("A2", "A3")):
            with self.assertRaisesRegex(ValueError, "configs must"):
                c.run(configs=configs)
        self.assertFalse(c.dir.exists())

    def test_resource_limit_cancels_and_requires_explicit_resumption(self):
        c = Campaign(self.tmp, names=("v1",))
        c.behaviour["v1.mp4"] = {"wait_for_cancel": True}
        low = dict(HEALTHY, available_bytes=2**20)
        outcome = c.run(sampler=lambda pid: low)
        self.assertEqual(outcome["stopped_at"], "v1/A2")
        self.assertEqual((outcome["status"], outcome["error_type"]), ("cancelled", "resource_limit:available_memory"))
        attempt = c.attempts("v1", "A2")[0]
        self.assertTrue((attempt / "cancel").exists())
        self.assertEqual(json.loads((attempt / "parent_summary.json").read_text())["intervention"],
                         "resource_limit:available_memory")
        with self.assertRaises(ValueError):  # no silent retry
            c.run()
        c.behaviour["v1.mp4"] = {}
        self.assertIsNone(c.run(retry_incomplete=True)["stopped_at"])
        self.assertEqual(len(c.attempts("v1", "A2")), 2)  # history kept
        self.assertEqual(len(c.attempts("v1", "A1")), 1)
        rows = {(r.item_id, r.config): r for r in c.collect().results}
        self.assertEqual(rows[("v1", "A2")].status, "completed")

    def test_timeout_cancels_the_attempt(self):
        c = Campaign(self.tmp, names=("v1",))
        c.behaviour["v1.mp4"] = {"wait_for_cancel": True}
        outcome = c.run(limits=runner.Limits(attempt_timeout_seconds=0.05, cancel_grace_seconds=5,
                                              sample_interval_seconds=0.01))
        self.assertEqual(outcome["error_type"], "timeout")

    def test_failed_job_resumption_never_duplicates_completed_samples(self):
        c = Campaign(self.tmp)
        state = {"failed": False}

        def flaky():
            if not state["failed"]:
                state["failed"] = True
                return {"fail": True}
            return {}
        c.behaviour["v2.video-only.mp4"] = flaky
        outcome = c.run()
        self.assertEqual((outcome["stopped_at"], outcome["status"]), ("v2/A1", "failed"))
        partial = {(r.item_id, r.config): r.status for r in c.collect("partial.json").results}
        self.assertEqual(partial, {("v1", "A1"): "completed", ("v1", "A2"): "completed",
                                   ("v2", "A1"): "failed", ("v2", "A2"): "not_run"})
        with self.assertRaises(ValueError):
            c.run()
        self.assertIsNone(c.run(retry_incomplete=True)["stopped_at"])
        self.assertEqual(c.calls.count("v1.mp4"), 1)
        self.assertEqual(c.calls.count("v1.video-only.mp4"), 1)
        self.assertEqual(len(c.attempts("v2", "A1")), 2)

    def test_whisper_cpu_fallback_and_text_in_a1_are_failures(self):
        c = Campaign(self.tmp, names=("v1",))
        c.behaviour["v1.mp4"] = {"warnings": ["CUDA Whisper inference failed; using the slow CPU fallback."]}
        outcome = c.run()
        self.assertEqual((outcome["status"], outcome["error_type"]), ("failed", "whisper_cpu_fallback"))
        second = Path(self.tmp) / "second"
        second.mkdir()
        d = Campaign(second, names=("v1",))
        d.behaviour["v1.video-only.mp4"] = {"warnings": []}  # text evidence ran on the audio-free input
        d.behaviour["v1.mp4"] = {}
        self.assertEqual(d.run()["error_type"], "a1_text_branch_ran")

    def test_invalid_checksum_is_refused_before_any_inference(self):
        c = Campaign(self.tmp)
        (c.media_root / "v2.mp4").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            c.run()
        self.assertNotIn("v2.mp4", c.calls)
        self.assertFalse(c.attempts("v2", "A2"))

    def test_duplicate_input_identity_is_refused(self):
        c = Campaign(self.tmp, media=lambda path: path.write_bytes(b"same bytes"))
        with self.assertRaises(ValidationError):
            c.run()
        self.assertEqual(c.calls, [])

    def test_pilot_leakage_is_refused(self):
        c = Campaign(self.tmp, groups={"v1": "synthetic_source"})
        with self.assertRaises(ValueError):
            c.run()
        self.assertFalse(c.dir.exists())

    def test_inference_requires_explicit_permission_and_stable_identity(self):
        c = Campaign(self.tmp, names=("v1",))
        with self.assertRaises(PermissionError):
            runner.run(c.manifest, c.media_root, c.dir, PILOT)
        c.run()
        with self.assertRaises(ValueError):  # different limits = different campaign identity
            c.run(limits=runner.Limits(attempt_timeout_seconds=99, sample_interval_seconds=0.01))

    def test_collected_results_file_is_atomic_and_never_overwritten(self):
        c = Campaign(self.tmp, names=("v1",))
        c.run()
        c.collect()
        with self.assertRaises(FileExistsError):
            c.collect()
        self.assertFalse([p for p in Path(self.tmp).glob(".*.tmp")])

    @unittest.skipUnless((FFMPEG / "ffmpeg.exe").is_file(), "vendor/ffmpeg is not prepared")
    def test_real_video_only_copy_preserves_packets_through_the_runner(self):
        def synthetic(path):
            # Different tones make the two synthetic sources distinct media (distinct SHA-256).
            subprocess.run([str(FFMPEG / "ffmpeg.exe"), "-v", "error", "-f", "lavfi", "-i",
                            "testsrc=size=160x120:rate=25:duration=2",
                            "-f", "lavfi", "-i", f"sine=frequency={440 if path.stem == 'v1' else 660}:duration=2",
                            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
                           check=True, capture_output=True, timeout=120)
        c = Campaign(self.tmp, media=synthetic)
        self.assertIsNone(c.run(prepare=runner_default_prepare())["stopped_at"])
        for name in ("v1", "v2"):
            identity = json.loads((c.dir / "inputs" / f"{name}.json").read_text())
            self.assertTrue(identity["video_packets_verified_identical"])
            copy = probe_packets(Path(identity["path"]), FFMPEG / "ffprobe.exe")
            source = probe_packets(c.media_root / f"{name}.mp4", FFMPEG / "ffprobe.exe")
            self.assertEqual(copy["stream_types"], ["video"])
            self.assertEqual(copy["video_packets"], source["video_packets"])


class CliEndToEndTests(unittest.TestCase):
    """The real CLI entry point; only the runner's injectable dependencies are simulated (no model)."""

    def cli(self, campaign, *args, sampler=lambda pid: HEALTHY):
        from unittest import mock

        from evaluation.benchmark.__main__ import main
        defaults = {"launcher": campaign.launcher, "sampler": sampler, "identity_factory": campaign.identity,
                    "prepare": campaign.fake_prepare, "preload_whisper_cuda12": False}
        real_limits = runner.Limits
        fast = lambda **kw: real_limits(**{**kw, "sample_interval_seconds": 0.01,  # noqa: E731
                                           "cancel_grace_seconds": 5})
        with mock.patch.dict(runner.run.__kwdefaults__, defaults), mock.patch.object(runner, "Limits", fast):
            return main(list(map(str, args)))

    def test_cli_campaign_collect_score_cancel_and_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp)
            c.behaviour.update({"v1.mp4": {"alert": True, "marqo": 0.5}, "v2.mp4": {"wait_for_cancel": True}})
            common = ["--pilot-manifest", PILOT]
            self.assertEqual(self.cli(c, "validate", c.manifest, *common), 0)
            with self.assertRaises(SystemExit):  # the pilot manifest is mandatory
                self.cli(c, "run", c.manifest, "--media-root", c.media_root, "--campaign", c.dir,
                         "--allow-inference")
            with self.assertRaises(PermissionError):  # inference needs --allow-inference
                self.cli(c, "run", c.manifest, "--media-root", c.media_root, "--campaign", c.dir, *common)
            low = dict(HEALTHY, available_bytes=2**20)
            run = ["run", c.manifest, "--media-root", c.media_root, "--campaign", c.dir, *common, "--allow-inference"]
            # v1 completes; v2/A2 waits until the low-memory sampler forces a cooperative cancellation.
            def sampler(pid):
                return low if c.calls and c.calls[-1] == "v2.mp4" else HEALTHY
            self.assertEqual(self.cli(c, *run, sampler=sampler), 2)
            self.assertTrue((c.dir / "campaign.json").exists())
            with self.assertRaises(ValueError):  # interrupted job: no silent resumption
                self.cli(c, *run)
            c.behaviour["v2.mp4"] = {}
            self.assertEqual(self.cli(c, *run, "--retry-incomplete"), 0)
            out = Path(tmp) / "results.json"
            self.assertEqual(self.cli(c, "collect", c.manifest, "--campaign", c.dir, "--output", out, *common), 0)
            with self.assertRaises(FileExistsError):
                self.cli(c, "collect", c.manifest, "--campaign", c.dir, "--output", out, *common)
            results = load_results(out)
            self.assertEqual(sorted((r.item_id, r.config, r.status) for r in results.results),
                             [("v1", "A1", "completed"), ("v1", "A2", "completed"),
                              ("v2", "A1", "completed"), ("v2", "A2", "completed")])
            report_dir = Path(tmp) / "report"
            self.assertEqual(self.cli(c, "score", c.manifest, out, "--output", report_dir, *common,
                                      "--resamples", 20), 0)
            metrics = json.loads((report_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(set(metrics["video_level"]), {"withheld"})
            self.assertIn("not a complete NSFW accuracy evaluation", metrics["scope_warning"])
            self.assertEqual(metrics["alert_review"]["A0@0.15"]["alerted_videos"], 1)
            self.assertEqual(metrics["alert_review"]["A2"]["alerts_by_reference_label"], {
                "positive": 0, "negative": 0, "uncertain": 0, "missing": 1})
            self.assertFalse(list(Path(tmp).rglob(".*.tmp")))
            self.assertEqual(len(c.attempts("v2", "A2")), 2)  # cancelled attempt kept in the history
            self.assertEqual(len(c.attempts("v2", "A1")), 1)  # completed sample not repeated
            cancelled = sorted(c.attempts("v2", "A2"))[0]
            self.assertEqual(json.loads((cancelled / "parent_summary.json").read_text())["intervention"],
                             "resource_limit:available_memory")

    def test_cli_refuses_pilot_leakage_before_creating_a_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, groups={"v2": "synthetic_source"})
            with self.assertRaises(ValueError):
                self.cli(c, "run", c.manifest, "--media-root", c.media_root, "--campaign", c.dir,
                         "--pilot-manifest", PILOT, "--allow-inference")
            self.assertFalse(c.dir.exists())
            with self.assertRaises(ValueError):
                self.cli(c, "validate", c.manifest, "--pilot-manifest", PILOT)


class SubprocessPlumbingTests(unittest.TestCase):
    def test_real_worker_process_refuses_a_wrong_input_before_building_the_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "attempt"
            directory.mkdir()
            media = Path(tmp) / "input.mp4"
            media.write_bytes(b"synthetic")
            write_atomic(directory / "spec.json", {
                "item_id": "v1", "group_id": "g", "config": "A2", "input_path": str(media),
                "input_sha256": "0" * 64, "attempt_dir": str(directory), "campaign_manifest_digest": "d" * 64,
                "preload_whisper_cuda12": False, "start_mode": "cold_process"})
            outcome = runner.supervise(directory, runner.subprocess_launcher, lambda pid: HEALTHY,
                                       runner.Limits(attempt_timeout_seconds=120, sample_interval_seconds=0.2))
            self.assertEqual((outcome["status"], outcome["error_type"]), ("failed", "input_sha256_mismatch"))
            self.assertTrue((directory / "worker_stderr.log").exists())
            self.assertFalse((directory / "record.json").exists())
            self.assertGreaterEqual(json.loads((directory / "monitor_summary.json").read_text())["samples"], 1)


class ObservabilityTests(unittest.TestCase):
    def test_inputs_are_recorded_with_absolute_paths_from_any_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            other = Path(tmp) / "elsewhere"
            other.mkdir()
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                runner.run(Path("manifest.json"), Path("media"), Path("campaign"), PILOT, allow_inference=True,
                           limits=FAST, launcher=c.launcher, sampler=lambda pid: HEALTHY,
                           identity_factory=c.identity, prepare=c.fake_prepare, preload_whisper_cuda12=False)
                identity = json.loads((c.dir / "inputs" / "v1.json").read_text())
                self.assertTrue(Path(identity["path"]).is_absolute())
                self.assertEqual(identity["file_name"], "v1.video-only.mp4")
                spec = json.loads(next(iter(c.attempts("v1", "A1"))).joinpath("spec.json").read_text())
                self.assertTrue(Path(spec["input_path"]).is_absolute())
                os.chdir(other)  # resuming and collecting from another directory still works
                self.assertIsNone(c.run()["stopped_at"])
                self.assertEqual(len(c.attempts("v1", "A1")), 1)
                c.collect()
            finally:
                os.chdir(previous)

    def test_legacy_relative_input_records_resolve_beside_their_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            inputs = c.dir / "inputs"
            inputs.mkdir(parents=True)
            copy = inputs / "v1.video-only.mp4"
            identity = Campaign.fake_prepare(c.media_root / "v1.mp4", copy)
            (inputs / "v1.json").write_text(json.dumps({**identity, "path": "some\\relative\\v1.video-only.mp4"}))
            from evaluation.benchmark.manifest import load_manifest
            item = load_manifest(c.manifest).items[0]
            resolved = runner._prepare_inputs(c.dir, item, c.media_root / "v1.mp4", c.fake_prepare)
            self.assertEqual(Path(resolved["path"]), copy.resolve())
            self.assertIn("relative", json.loads((inputs / "v1.json").read_text())["path"])  # not rewritten

    def test_process_tree_cpu_is_measured_and_exited_processes_are_tolerated(self):
        import sys
        rss, cpu, error = runner.process_tree_usage(os.getpid())
        self.assertGreater(rss, 0)
        self.assertIsNone(cpu)  # first sample has no interval
        self.assertIsNone(error)
        sum(i * i for i in range(200_000))
        rss, cpu, error = runner.process_tree_usage(os.getpid())
        self.assertIsNotNone(cpu)
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        runner.process_tree_usage(child.pid)
        child.wait(timeout=30)
        self.assertEqual(runner.process_tree_usage(child.pid), (None, None, "NoSuchProcess"))

    def test_monitor_summary_reports_cpu_peak_mean_and_convention(self):
        values = iter([None, 50.0, 150.0])

        def sampler(pid):
            return dict(HEALTHY, process_tree_cpu_percent=next(values, 100.0))
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            c.behaviour["v1.mp4"] = {"wait_for_cancel": True}
            c.run(sampler=sampler, limits=runner.Limits(attempt_timeout_seconds=0.2, cancel_grace_seconds=5,
                                                         sample_interval_seconds=0.02))
            summary = json.loads(next(iter(c.attempts("v1", "A2"))).joinpath("monitor_summary.json").read_text())
            self.assertEqual(summary["cpu"]["logical_cpus"], os.cpu_count())
            self.assertIn("100 = one logical CPU", summary["cpu"]["convention"])
            self.assertEqual(summary["cpu"]["peak_percent"], 150.0)
            self.assertEqual(summary["cpu"]["valid_samples"], summary["samples"] - 1)

    def test_whisper_probe_times_without_storing_text(self):
        import sys
        import types
        from evaluation.benchmark import whisper_probe

        class Segment:
            text = "SECRET TRANSCRIPT"

        class FakeModel:
            def __init__(self, *args, device="cpu", compute_type="int8", **kwargs):
                self.model = types.SimpleNamespace(device=device, compute_type=compute_type)

            def transcribe(self, audio, **kwargs):
                info = types.SimpleNamespace(language="en", language_probability=0.97)
                return iter([Segment(), Segment(), Segment()]), info

        events = []
        journal = types.SimpleNamespace(emit=lambda kind, **data: events.append({"kind": kind, **data}))
        saved = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=FakeModel)
        try:
            self.assertTrue(whisper_probe.install(journal))
            model = sys.modules["faster_whisper"].WhisperModel("small", device="cuda", compute_type="float16")
            segments, info = model.transcribe("audio.wav", beam_size=1)
            self.assertEqual([s.text for s in segments], ["SECRET TRANSCRIPT"] * 3)  # outputs unchanged
            partial, _ = model.transcribe("audio.wav")
            next(partial)
            partial.close()  # e.g. cancellation while iterating
        finally:
            if saved is None:
                sys.modules.pop("faster_whisper")
            else:
                sys.modules["faster_whisper"] = saved
        self.assertNotIn("SECRET", json.dumps(events))
        summary = whisper_probe.summarize(events)
        self.assertEqual(summary["model_loads"][0]["device"], "cuda")
        self.assertEqual(summary["model_loads"][0]["compute_type"], "float16")
        first, second = summary["transcriptions"]
        self.assertEqual((first["ok"], first["segments"], first["language"]), (True, 3, "en"))
        self.assertEqual((second["complete"], second["segments"]), (False, 1))

    def test_probe_is_installed_for_a2_only_and_a1_never_imports_whisper_runtime(self):
        script = (
            "import json, sys, types\n"
            "from evaluation.benchmark import worker\n"
            "events = []\n"
            "journal = types.SimpleNamespace(emit=lambda kind, **data: events.append(kind))\n"
            "calls = []\n"
            "_, a1 = worker.prepare_whisper_runtime('A1', journal, enable_cublas=lambda: calls.append('cublas'),\n"
            "                                        cuda_init=lambda: calls.append('cuda'))\n"
            "a1_modules = {m: m in sys.modules for m in ('faster_whisper', 'ctranslate2')}\n"
            "a1_events = list(events)\n"
            "class Fake:\n"
            "    pass\n"
            "sys.modules['faster_whisper'] = types.SimpleNamespace(WhisperModel=Fake)\n"
            "_, a2 = worker.prepare_whisper_runtime('A2', journal, enable_cublas=lambda: calls.append('cublas'),\n"
            "                                        cuda_init=lambda: calls.append('cuda'))\n"
            "print(json.dumps({'a1': a1, 'a1_modules': a1_modules, 'a1_events': a1_events, 'a2': a2,\n"
            "                  'events': events, 'calls': calls,\n"
            "                  'patched': sys.modules['faster_whisper'].WhisperModel is not Fake}))\n")
        out = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=120,
                             check=True)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(result["a1_modules"], {"faster_whisper": False, "ctranslate2": False})
        self.assertEqual(result["a1_events"], [])
        self.assertFalse(result["a1"]["whisper_probe_installed"])
        self.assertTrue(result["a1"]["torch_cuda_initialized"])
        self.assertTrue(result["a2"]["whisper_probe_installed"])
        self.assertTrue(result["patched"])
        self.assertEqual(result["events"], ["whisper_probe"])
        self.assertEqual(result["calls"], ["cublas", "cuda", "cublas", "cuda"])  # preload order unchanged

    def test_zero_segment_language_is_not_reported_as_a_speech_language(self):
        from evaluation.benchmark import whisper_probe
        events = [{"kind": "whisper_probe", "available": True},
                  {"kind": "whisper_transcription", "ok": True, "complete": True, "device": "cuda", "language": "en",
                   "language_probability": 0.44, "segments": 0, "setup_seconds": 0.1, "seconds": 0.4},
                  {"kind": "whisper_transcription", "ok": True, "complete": True, "device": "cuda", "language": "en",
                   "language_probability": 0.78, "segments": 7, "setup_seconds": 0.1, "seconds": 0.8}]
        silent, spoken = whisper_probe.summarize(events)["transcriptions"]
        self.assertEqual((silent["language"], silent["language_probability"]), (None, None))
        self.assertEqual(silent["language_basis"], "no_speech_segments_unreliable")
        self.assertEqual(silent["detected_language_without_speech"], "en")
        self.assertFalse(silent["speech_segments_present"])
        self.assertEqual((spoken["language"], spoken["language_probability"]), ("en", 0.78))
        self.assertEqual(spoken["language_basis"], "speech_segments")
        self.assertIsNone(spoken["detected_language_without_speech"])

    def test_worker_summary_records_whisper_runtime_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            c.run()
            for config in ("A1", "A2"):
                summary = json.loads(next(iter(c.attempts("v1", config))).joinpath("summary.json").read_text())
                self.assertEqual(set(summary["python_modules_imported"]), {"faster_whisper", "ctranslate2"})
                self.assertIsNone(summary["whisper_observed"])

    def test_observed_non_cuda_whisper_fails_a2_even_without_a_warning(self):
        class ProbeEmittingPipeline(MockPipeline):
            def run(self, request, cancellation, event_callback, job_id):
                self.journal.emit("whisper_probe", available=True)
                self.journal.emit("whisper_model_load", ok=True, device="cpu", compute_type="int8", seconds=1.0)
                self.journal.emit("whisper_transcription", ok=True, complete=True, device="cpu", language="en",
                                  language_probability=0.9, segments=2, setup_seconds=0.1, seconds=1.0)
                return super().run(request, cancellation, event_callback, job_id)

        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            c.launcher = lambda spec: ThreadHandle(lambda: worker.run_attempt(
                spec, pipeline_factory=lambda cache, journal: ProbeEmittingPipeline(c.behaviour, journal, c.calls)))
            outcome = c.run()
            self.assertEqual((outcome["status"], outcome["error_type"]), ("failed", "whisper_cpu_fallback"))
            summary = json.loads(next(iter(c.attempts("v1", "A2"))).joinpath("summary.json").read_text())
            self.assertFalse(summary["whisper_backend_confirmed"])
            self.assertEqual(summary["whisper_observed"]["transcriptions"][0]["segments"], 2)


class FakePsutil:
    """Synthetic psutil: a process table where a PID can be reused by a process with a new creation time."""

    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    def __init__(self):
        self.table = {}  # pid -> {"created": float, "rss": int, "cpu": float, "parent": pid | None}
        test = self

        class Process:
            def __init__(self, pid):
                if pid not in test.table:
                    raise test.NoSuchProcess(pid)
                self.pid, self.created = pid, test.table[pid]["created"]

            def _alive(self):
                entry = test.table.get(self.pid)
                if entry is None or entry["created"] != self.created:  # exited, or PID reused
                    raise test.NoSuchProcess(self.pid)
                return entry

            def create_time(self):
                self._alive()
                return self.created

            def children(self, recursive=False):
                self._alive()
                found, frontier = [], [self.pid]
                while frontier:
                    parent = frontier.pop()
                    for pid, entry in list(test.table.items()):
                        if entry["parent"] == parent:
                            found.append(Process(pid))
                            if recursive:
                                frontier.append(pid)
                return found

            def cpu_percent(self, interval=None):
                return self._alive()["cpu"]

            def memory_info(self):
                return type("Memory", (), {"rss": self._alive()["rss"]})()

        self.Process = Process

    def spawn(self, pid, created, rss=100, cpu=50.0, parent=None):
        self.table[pid] = {"created": created, "rss": rss, "cpu": cpu, "parent": parent}


class ProcessMonitoringTests(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        self.ps = FakePsutil()
        patcher = mock.patch.dict(sys.modules, {"psutil": self.ps})
        patcher.start()
        self.addCleanup(patcher.stop)
        for cache in (runner._PROCESSES, runner._PRIMED):
            self.addCleanup(cache.clear)
            cache.clear()

    def test_reused_pid_is_measured_as_a_new_process(self):
        self.ps.spawn(100, created=1.0, rss=10)
        runner.process_tree_usage(100)
        self.assertEqual(runner.process_tree_usage(100), (10, 50.0, None))
        del self.ps.table[100]
        self.ps.spawn(100, created=2.0, rss=20, cpu=80.0)  # the next worker receives the same PID
        self.assertEqual(runner.process_tree_usage(100), (20, None, None))  # new process: no interval yet
        self.assertEqual(runner.process_tree_usage(100), (20, 80.0, None))
        self.assertEqual(set(runner._PROCESSES), {(100, 2.0)})

    def test_reused_child_pid_does_not_inherit_the_old_cpu_baseline(self):
        self.ps.spawn(100, created=1.0, rss=10, cpu=10.0)
        self.ps.spawn(200, created=1.5, rss=5, cpu=30.0, parent=100)
        runner.process_tree_usage(100)
        self.assertEqual(runner.process_tree_usage(100), (15, 40.0, None))
        self.ps.spawn(200, created=3.0, rss=7, cpu=90.0, parent=100)
        self.assertEqual(runner.process_tree_usage(100), (17, 10.0, None))  # new child primed, not counted
        self.assertEqual(runner.process_tree_usage(100), (17, 100.0, None))

    def test_terminated_processes_are_reported_and_never_estimated(self):
        self.ps.spawn(100, created=1.0)
        self.ps.spawn(200, created=1.0, rss=5, parent=100)
        runner.process_tree_usage(100)
        del self.ps.table[200]
        self.assertEqual(runner.process_tree_usage(100), (100, 50.0, None))  # exited child skipped
        self.assertNotIn((200, 1.0), runner._PROCESSES)
        del self.ps.table[100]
        self.assertEqual(runner.process_tree_usage(100), (None, None, "NoSuchProcess"))

    def test_monitor_summary_discloses_unmeasured_samples_and_limits_still_apply(self):
        def sampler(pid):
            return dict(HEALTHY, process_tree_rss_bytes=None, process_tree_cpu_percent=None,
                        process_tree_error="NoSuchProcess", available_bytes=2**30)
        with tempfile.TemporaryDirectory() as tmp:
            c = Campaign(tmp, names=("v1",))
            c.behaviour["v1.mp4"] = {"wait_for_cancel": True}
            c.run(sampler=sampler)
            directory = next(iter(c.attempts("v1", "A2")))
            summary = json.loads(directory.joinpath("monitor_summary.json").read_text())
            self.assertEqual(summary["intervention"], "resource_limit:available_memory")
            self.assertEqual(summary["process_tree_monitoring"],
                             {"samples_without_rss": summary["samples"], "errors": {"NoSuchProcess": summary["samples"]}})
            self.assertNotIn("process_tree_rss_bytes", summary)
            self.assertIsNone(summary["cpu"]["peak_percent"])


class AtomicAndWorkerUnitTests(unittest.TestCase):
    def test_atomic_write_refuses_overwrite_and_leaves_nothing_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.json"
            with self.assertRaises(ValueError):
                write_atomic(path, {"bad": float("nan")})
            self.assertEqual(list(Path(tmp).iterdir()), [])
            write_atomic(path, {"ok": 1})
            with self.assertRaises(FileExistsError):
                write_atomic(path, {"ok": 2})
            self.assertEqual(json.loads(path.read_text()), {"ok": 1})

    def test_whisper_backend_classification(self):
        self.assertEqual(worker.whisper_backend([]), "cuda_float16")
        self.assertEqual(worker.whisper_backend([NOT_APPLICABLE]), "not_applicable")
        for warning in ("CUDA Whisper initialization failed; using slow CPU fallback.",
                        "CUDA is unavailable; Whisper is using the slow CPU fallback.",
                        "Whisper is using the slow CPU backend."):
            self.assertEqual(worker.whisper_backend([warning]), "cpu_fallback")

    def test_resource_breach_rules(self):
        limits = runner.Limits(gpu_breach_samples=2)
        self.assertEqual(runner.breach(dict(HEALTHY, commit_headroom_bytes=1), limits, 0)[0],
                         "resource_limit:commit_headroom")
        reason, streak = runner.breach(dict(HEALTHY, gpu_memory_mib=8000), limits, 0)
        self.assertEqual((reason, streak), (None, 1))
        self.assertEqual(runner.breach(dict(HEALTHY, gpu_memory_mib=8000), limits, 1)[0],
                         "resource_limit:gpu_memory")
        self.assertEqual(runner.breach(HEALTHY, limits, 1), (None, 0))


def load_manifest_for(campaign):
    from evaluation.benchmark.manifest import load_manifest
    return load_manifest(campaign.manifest)


def runner_default_prepare():
    from evaluation.benchmark.media import prepare_video_only_copy
    return lambda s, t: prepare_video_only_copy(s, t, ffmpeg=FFMPEG / "ffmpeg.exe", ffprobe=FFMPEG / "ffprobe.exe")


if __name__ == "__main__":
    unittest.main()
