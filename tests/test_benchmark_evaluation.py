"""Synthetic, non-sensitive tests for evaluation.benchmark (no model, no real media, no network)."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from evaluation.benchmark import events, media, video_metrics as vm
from evaluation.benchmark.__main__ import main as cli
from evaluation.benchmark.manifest import BenchmarkManifest, manifest_digest
from evaluation.benchmark.report import score as _score
from evaluation.benchmark.results import ResultsFile
from evaluation.benchmark.stats import grouped_bootstrap, holm, mcnemar_exact, wilson

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "tests" / "fixtures" / "pilot" / "synthetic.json"
ABSENT = {"nudity": "absent", "sexual_activity": "absent", "sexual_context": "absent"}
UNKNOWN = {"nudity": "unknown", "sexual_activity": "unknown", "sexual_context": "unknown"}


def score(manifest, results, **options):
    return _score(manifest, results, pilot_manifest=PILOT, **options)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def item(item_id, label, group=None, split="test", categories=None, **extra):
    if categories is None:
        categories = ABSENT if label == "negative" else {**UNKNOWN, "nudity": "present"} if label == "positive" else UNKNOWN
    basis = "unreviewed" if label == "missing" else "complete"
    return {"item_id": item_id, "group_id": group or f"g_{item_id}", "split": split, "sha256": sha(item_id),
            "duration_seconds": 60.0, "video_label": label, "review_basis": basis,
            "category_labels": categories, **extra}


def manifest_dict(items, track="accuracy"):
    return {"schema_version": 1, "benchmark_id": "synthetic_bench", "track": track, "synthetic_fixture": True,
            "dataset": {"dataset_id": "synthetic", "name": "Synthetic fixture", "publisher": "tests",
                        "homepage": "https://example.org/synthetic", "version": "1", "license_id": "CC0-1.0",
                        "license_evidence": [{"url": "https://example.org/license", "retrieved": "2026-10-19",
                                              "statement": "synthetic fixture"}],
                        "access": "ungated", "permitted_use": "tests", "redistribution_allowed": True,
                        "content": "synthetic"},
            "annotation": {"version": "1", "source": "project_annotators", "guideline": "synthetic"},
            "items": items}


def build(items, track="accuracy"):
    return BenchmarkManifest.model_validate(manifest_dict(items, track))


def result(item_id, config, alert=False, status="completed", scores=None, original=None, **extra):
    identity = None
    if status == "completed":
        identity = {"sha256": sha(item_id) if config == "A2" else sha(item_id + "-video-only")}
        if config == "A1":
            identity |= {"derived_from_sha256": original or sha(item_id), "video_packets_verified_identical": True}
    suggestions = [{"id": f"{item_id}-s", "start_seconds": 10.0, "end_seconds": 20.0, "category": "nudity",
                    "final_confidence": 0.9}] if alert and status == "completed" else []
    return {"item_id": item_id, "config": config, "status": status, "input": identity, "suggestions": suggestions,
            "marqo_scores": scores or [], "pipeline_seconds": 30.0, "start_mode": "cold_process", **extra}


def results_file(manifest, rows):
    return ResultsFile.model_validate({
        "schema_version": 1, "benchmark_id": manifest.benchmark_id, "manifest_digest": manifest_digest(manifest),
        "environment": {"commit": "2399e950aeb33dd7925690c78d3f5f25d50d07cb", "model_revisions": {"qwen": "r"},
                        "whisper_backend": "cuda_float16", "gpu": "synthetic", "driver": "0"},
        "results": rows})


class ManifestTests(unittest.TestCase):
    def test_valid_manifest_and_evaluable_excludes_flagged_items(self):
        manifest = build([item("a", "positive"), item("b", "negative"),
                          item("c", "negative", excluded=True, exclusion_reason="age not verifiable")])
        self.assertEqual([i.item_id for i in manifest.evaluable()], ["a", "b"])

    def test_invalid_inputs_are_rejected(self):
        cases = {
            "duplicate id": [item("a", "negative"), item("a", "negative", group="g2")],
            "duplicate media": [item("a", "negative"), {**item("b", "negative"), "sha256": sha("a")}],
            "group leakage": [item("a", "negative", group="g"), item("b", "negative", group="g", split="tuning")],
            "negative with present category": [item("a", "negative", categories={**ABSENT, "nudity": "present"})],
            "positive with all absent": [item("a", "positive", categories=ABSENT)],
            "exclusion without reason": [item("a", "negative", excluded=True)],
            "missing category key": [item("a", "negative", categories={"nudity": "absent"})],
        }
        for name, items in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                build(items)

    def test_review_basis_must_match_the_label(self):
        with self.assertRaises(ValidationError):  # a reference label needs a review basis
            build([{**item("a", "negative"), "review_basis": "unreviewed"}])
        with self.assertRaises(ValidationError):  # missing labels cannot claim a review
            build([{**item("a", "missing"), "review_basis": "random_audit"}])
        partial = build([item("a", "negative"), {**item("b", "negative"), "review_basis": "random_audit"},
                         item("c", "missing")])
        self.assertFalse(partial.verification()["complete"])
        self.assertEqual(partial.verification()["by_basis"]["random_audit"], 1)
        self.assertTrue(build([item("a", "negative")]).verification()["complete"])

    def test_benchmark_must_be_disjoint_from_the_development_pilot(self):
        from evaluation.benchmark.manifest import assert_disjoint_from_pilot
        pilot = ROOT / "tests" / "fixtures" / "pilot" / "synthetic.json"
        clean = build([item("a", "negative")])
        self.assertEqual(assert_disjoint_from_pilot(clean, pilot)["pilot_clips"], 1)
        for name, overlapping in {
            "same media": {**item("a", "negative"), "sha256": "0" * 64},
            "same source": item("a", "negative", group="synthetic_source"),
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                assert_disjoint_from_pilot(build([overlapping]), pilot)

    def test_technical_track_refuses_positive_labels(self):
        with self.assertRaises(ValidationError):
            build([item("a", "positive")], track="technical")
        build([item("a", "negative"), item("b", "missing")], track="technical")

    def test_temporal_annotation_rules(self):
        temporal = {"binary_exhaustive": True, "exhaustive_categories": ["nudity"],
                    "events": [{"event_id": "e1", "start_seconds": 5.0, "end_seconds": 70.0,
                                "categories": ["nudity"], "notes": ""}]}
        with self.assertRaises(ValidationError):  # event beyond duration
            build([item("a", "positive", temporal=temporal)])
        unknown = {**temporal, "exhaustive_categories": ["sexual_activity"],
                   "events": [{**temporal["events"][0], "end_seconds": 20.0}]}
        with self.assertRaises(ValidationError):  # exhaustive category labelled unknown
            build([item("a", "positive", temporal=unknown)])
        with self.assertRaises(ValidationError):  # positive video without events
            build([item("a", "positive", temporal={**temporal, "events": []})])


class StatsTests(unittest.TestCase):
    def test_wilson_reference_values(self):
        interval = wilson(8, 10)
        self.assertAlmostEqual(interval["low"], 0.4902, places=4)
        self.assertAlmostEqual(interval["high"], 0.9433, places=4)
        self.assertIsNone(wilson(0, 0))
        with self.assertRaises(ValueError):
            wilson(3, 2)

    def test_exact_mcnemar_and_holm(self):
        self.assertAlmostEqual(mcnemar_exact(0, 5)["p_value"], 0.0625)
        self.assertAlmostEqual(mcnemar_exact(3, 3)["p_value"], 1.0)
        self.assertIsNone(mcnemar_exact(0, 0)["p_value"])
        adjusted = holm({"a": 0.01, "b": 0.04, "c": None})
        self.assertAlmostEqual(adjusted["a"], 0.02)
        self.assertAlmostEqual(adjusted["b"], 0.04)
        self.assertIsNone(adjusted["c"])

    def test_grouped_bootstrap_resamples_whole_groups_reproducibly(self):
        rows = [{"group": "g1", "v": 1.0}, {"group": "g1", "v": 1.0}, {"group": "g2", "v": 0.0}]
        mean = lambda sample: sum(r["v"] for r in sample) / len(sample)  # noqa: E731
        first = grouped_bootstrap(rows, "group", mean, resamples=500, seed=7)
        self.assertEqual(first, grouped_bootstrap(rows, "group", mean, resamples=500, seed=7))
        self.assertEqual(first["groups"], 2)
        self.assertAlmostEqual(first["estimate"], 2 / 3)
        # Groups move together: a resample holds either 0, 2 or 4 ones out of 2 or 4 rows.
        self.assertGreaterEqual(first["low"], 0.0)
        self.assertLessEqual(first["high"], 1.0)
        undefined = grouped_bootstrap(rows, "group", lambda s: None if len(s) == 2 else 1.0, resamples=200, seed=1)
        self.assertGreater(undefined["undefined_resamples"], 0)


class VideoMetricTests(unittest.TestCase):
    def test_uncertain_missing_and_failures_are_accounted_not_scored(self):
        rows = [{"label": "positive", "alert": True}, {"label": "positive", "alert": None},
                {"label": "negative", "alert": False}, {"label": "negative", "alert": True},
                {"label": "uncertain", "alert": True}, {"label": "missing", "alert": False}]
        excluded = vm.confusion(rows)
        self.assertEqual((excluded["tp"], excluded["fn"], excluded["tn"], excluded["fp"]), (1, 0, 1, 1))
        self.assertEqual((excluded["failed_positive"], excluded["uncertain_label"], excluded["missing_label"]), (1, 1, 1))
        worst = vm.confusion(rows, "worst_case")
        self.assertEqual(worst["fn"], 1)
        metrics = vm.video_metrics(excluded)
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["specificity"], 0.5)
        self.assertEqual(metrics["balanced_accuracy"], 0.75)
        self.assertIsNone(vm.video_metrics(vm.confusion([{"label": "negative", "alert": False}]))["recall"])

    def test_decision_rules(self):
        manifest = build([item("a", "negative")])
        res = results_file(manifest, [result("a", "A2", alert=False, scores=[
            {"timestamp_seconds": 0.0, "probability": 0.2}, {"timestamp_seconds": 5.0, "probability": None}])])
        a2 = res.results[0]
        self.assertFalse(vm.pipeline_alert(a2))
        self.assertEqual(vm.a0_alert(a2, 0.15), (True, 1))
        self.assertEqual(vm.a0_alert(a2, 0.45), (False, 1))
        partial = results_file(manifest, [result("a", "A2", status="partial")]).results[0]
        self.assertIsNone(vm.pipeline_alert(partial))


class EventTests(unittest.TestCase):
    def temporal_manifest(self):
        temporal = {"binary_exhaustive": True, "exhaustive_categories": ["nudity"],
                    "events": [{"event_id": "e1", "start_seconds": 10.0, "end_seconds": 20.0,
                                "categories": ["nudity"], "notes": ""}]}
        return build([item("a", "positive", temporal=temporal),
                      item("b", "negative", temporal={"binary_exhaustive": True, "events": []}),
                      item("c", "positive")])

    def test_events_scored_only_where_exhaustive_and_masked_by_category(self):
        manifest = self.temporal_manifest()
        res = {r.item_id: r for r in results_file(manifest, [result("a", "A2", alert=True),
                                                             result("b", "A2", alert=True),
                                                             result("c", "A2", alert=True)]).results}
        rows, unusable = events.event_rows(manifest.evaluable(), res)
        self.assertEqual([r["clip_id"] for r in rows], ["a", "b"])  # c has video-level labels only
        self.assertEqual(unusable, [])
        summary = events.summarize(rows)
        self.assertEqual(summary["event_metrics"]["0.50"]["tp"], 1)
        self.assertEqual(summary["event_metrics"]["0.50"]["fp"], 1)
        self.assertAlmostEqual(summary["event_metrics"]["0.50"]["false_alert_events_per_hour"], 30.0)
        nudity_rows, _ = events.event_rows(manifest.evaluable(), res, "nudity")
        self.assertEqual([r["clip_id"] for r in nudity_rows], ["a"])
        with self.assertRaises(events.TemporalAnnotationsUnavailable):
            events.event_rows(manifest.evaluable(), res, "sexual_activity")

    def test_video_level_only_dataset_refuses_event_metrics(self):
        manifest = build([item("a", "positive"), item("b", "negative")])
        with self.assertRaises(events.TemporalAnnotationsUnavailable):
            events.event_rows(manifest.evaluable(), {})


class ReportTests(unittest.TestCase):
    def test_paired_report_with_groups_and_sample_accounting(self):
        items = [item(f"p{i}", "positive", group=f"src{i % 3}") for i in range(6)]
        items += [item(f"n{i}", "negative", group=f"src{3 + i % 3}") for i in range(6)]
        items += [item("u", "uncertain", group="src9")]
        manifest = build(items)
        rows = []
        for i in range(6):
            high = [{"timestamp_seconds": 0.0, "probability": 0.5 if i < 5 else 0.1}]
            rows += [result(f"p{i}", "A2", alert=i < 5, scores=high), result(f"p{i}", "A1", alert=i < 4)]
            low = [{"timestamp_seconds": 0.0, "probability": 0.2 if i < 3 else 0.05}]
            rows += [result(f"n{i}", "A2", alert=i == 0, scores=low), result(f"n{i}", "A1", alert=False)]
        rows.append(result("u", "A2", alert=True))
        report = score(manifest, results_file(manifest, rows), resamples=300)
        self.assertEqual(report["sample_sizes"]["positive"], 6)
        self.assertEqual(report["sample_sizes"]["uncertain"], 1)
        a2 = report["video_level"]["A2"]["exclude"]["counts"]
        self.assertEqual((a2["tp"], a2["fn"], a2["fp"], a2["tn"]), (5, 1, 1, 5))
        a0 = report["video_level"]["A0@0.15"]["exclude"]["counts"]
        self.assertEqual((a0["tp"], a0["fp"]), (5, 3))
        self.assertEqual(report["video_level"]["A1"]["exclude"]["counts"]["failed_positive"], 0)
        paired = report["paired_comparisons"]["A1_vs_A2"]
        self.assertEqual(paired["paired_items"], 12)
        self.assertEqual(paired["mcnemar"]["b"] + paired["mcnemar"]["c"], paired["mcnemar"]["discordant"])
        self.assertIn("p_value_holm", paired["mcnemar"])
        self.assertFalse(report["event_level"]["A2"]["binary"]["available"])
        self.assertFalse(report["event_level"]["A0"]["available"])
        self.assertNotIn("scope_warning", report)

    def test_negative_only_track_carries_a_scope_warning(self):
        manifest = build([item("a", "negative"), item("b", "negative")], track="technical")
        report = score(manifest, results_file(manifest, [result("a", "A2"), result("b", "A2", alert=True)]),
                       resamples=100)
        self.assertIn("not a complete NSFW accuracy evaluation", report["scope_warning"])
        self.assertIsNone(report["video_level"]["A2"]["exclude"]["metrics"]["recall"])
        self.assertEqual(report["video_level"]["A2"]["exclude"]["metrics"]["specificity"], 0.5)

    def test_partial_review_withholds_accuracy_and_reports_confirmed_alerts(self):
        items = [item(f"m{i}", "missing", group=f"s{i % 3}") for i in range(6)]
        items += [{**item(f"r{i}", "negative", group=f"s{i}"), "review_basis": "alert_triggered"} for i in range(2)]
        items += [{**item(f"q{i}", "negative", group=f"s{i}"), "review_basis": "random_audit"} for i in range(2)]
        manifest = build(items, track="technical")
        rows = [result(f"m{i}", "A2") for i in range(6)]
        rows += [result(f"r{i}", "A2", alert=True) for i in range(2)] + [result(f"q{i}", "A2") for i in range(2)]
        report = score(manifest, results_file(manifest, rows), resamples=50)
        self.assertIn("withheld", report["video_level"])
        self.assertIn("withheld", report["paired_comparisons"])
        review = report["alert_review"]["A2"]
        self.assertEqual((review["completed_runs"], review["alerted_videos"]), (10, 2))
        self.assertAlmostEqual(review["alert_rate_unverified_ci"]["estimate"], 0.2)
        self.assertTrue(review["all_alerts_reviewed"])
        self.assertEqual(review["confirmed_false_alerts"], 2)
        self.assertAlmostEqual(review["confirmed_false_alerts_per_analyzed_hour"], 12.0)  # 2 alerts / (10 x 60 s)
        self.assertEqual(review["random_audit"]["audited_videos"], 2)
        self.assertEqual(review["random_audit"]["positives_found_without_alert"], 0)
        # An alert on an unreviewed video makes the confirmed rate a lower bound: it is withheld.
        rows[0] = result("m0", "A2", alert=True)
        unreviewed = score(manifest, results_file(manifest, rows), resamples=50)["alert_review"]["A2"]
        self.assertFalse(unreviewed["all_alerts_reviewed"])
        self.assertIsNone(unreviewed["confirmed_false_alerts_per_analyzed_video_ci"])
        self.assertIsNone(unreviewed["confirmed_false_alerts_per_analyzed_hour"])

    def test_results_must_match_manifest_and_verified_inputs(self):
        manifest = build([item("a", "negative")])
        with self.assertRaises(ValueError):
            score(manifest, results_file(manifest, [result("zzz", "A2")]))
        other = results_file(manifest, [result("a", "A2")])
        other.manifest_digest = "0" * 64
        with self.assertRaises(ValueError):
            score(manifest, other)
        with self.assertRaises(ValueError):  # A2 input must be the manifest's media
            score(manifest, results_file(manifest, [{**result("a", "A2"), "input": {"sha256": sha("other")}}]))
        with self.assertRaises(ValidationError):  # A1 input must be verified against its source
            results_file(manifest, [{**result("a", "A1"), "input": {"sha256": sha("x")}}])
        with self.assertRaises(ValidationError):  # duplicate result
            results_file(manifest, [result("a", "A2"), result("a", "A2")])


class MediaTests(unittest.TestCase):
    PROBE = {"stream_types": ["video", "audio"], "video_codecs": ["h264"],
             "video_packets": [[("0.000000", "SHA256:aa"), ("0.040000", "SHA256:bb")]]}

    def test_video_only_copy_verification(self):
        same = {**self.PROBE, "stream_types": ["video"]}
        media.verify_video_only_copy(self.PROBE, same)
        for name, target in {
            "audio kept": self.PROBE,
            "payload changed": {**same, "video_packets": [[("0.000000", "SHA256:aa"), ("0.040000", "SHA256:cc")]]},
            "timeline shifted": {**same, "video_packets": [[("0.000000", "SHA256:aa"), ("0.050000", "SHA256:bb")]]},
            "packet dropped": {**same, "video_packets": [[("0.000000", "SHA256:aa")]]},
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                media.verify_video_only_copy(self.PROBE, target)

    def test_real_stream_copy_on_a_synthetic_test_pattern(self):
        ffmpeg, ffprobe = (ROOT / "vendor" / "ffmpeg" / "bin" / name for name in ("ffmpeg.exe", "ffprobe.exe"))
        if not ffmpeg.is_file() or not ffprobe.is_file():
            self.skipTest("vendor/ffmpeg is not prepared")
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "pattern.mp4", Path(tmp) / "pattern.video-only.mp4"
            subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
                            "-shortest", str(source)], check=True, capture_output=True, timeout=120)
            identity = media.prepare_video_only_copy(source, target, ffmpeg=ffmpeg, ffprobe=ffprobe)
            self.assertTrue(identity["video_packets_verified_identical"])
            self.assertNotEqual(identity["sha256"], identity["derived_from_sha256"])
            with self.assertRaises(FileExistsError):
                media.prepare_video_only_copy(source, target, ffmpeg=ffmpeg, ffprobe=ffprobe)

    def test_cuda12_cublas_preload_verifies_pins_and_loads_the_dependency_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            vendor = root / "vendor" / "cuda12-cublas"
            vendor.mkdir(parents=True)
            payload = {"cublas64_12.dll": b"main", "cublasLt64_12.dll": b"light"}
            for name, data in payload.items():
                (vendor / name).write_bytes(data)
            pin = {"version": "test", "binaries": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                                                   for name, data in payload.items()}}
            (root / "scripts" / "cuda12-cublas-pin.json").write_text(json.dumps(pin), encoding="utf-8")
            loaded = media.enable_whisper_cuda12_cublas(root, loader=lambda path: Path(path).name)
            self.assertEqual(loaded, ["cublasLt64_12.dll", "cublas64_12.dll"])
            (vendor / "cublas64_12.dll").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                media.enable_whisper_cuda12_cublas(root, loader=lambda path: path)


class MethodologyTests(unittest.TestCase):
    """Review designs, metric suppression, label handling and anti-leakage enforcement."""

    def reviewed(self, item_id, label, basis, group=None):
        return {**item(item_id, label, group=group), "review_basis": basis}

    def technical(self, extra=()):
        # 4 unreviewed presumed negatives, 2 alerted+reviewed negatives, 2 audited non-alerted negatives.
        items = [item(f"m{i}", "missing", group=f"s{i % 2}") for i in range(4)]
        items += [self.reviewed(f"r{i}", "negative", "alert_triggered", group=f"s{i}") for i in range(2)]
        items += [self.reviewed(f"q{i}", "negative", "random_audit", group=f"s{i}") for i in range(2)]
        return build([*items, *extra], track="technical")

    def technical_rows(self, alert_on_unreviewed=False):
        rows = [result(f"m{i}", "A2", alert=alert_on_unreviewed and i == 0) for i in range(4)]
        rows += [result(f"r{i}", "A2", alert=True) for i in range(2)]
        return rows + [result(f"q{i}", "A2") for i in range(2)]

    def test_1_complete_review_reports_classification_metrics_with_denominators(self):
        manifest = build([item("p1", "positive"), item("p2", "positive"), item("n1", "negative"),
                          item("n2", "negative")])
        report = score(manifest, results_file(manifest, [result("p1", "A2", alert=True), result("p2", "A2"),
                                                         result("n1", "A2", alert=True), result("n2", "A2")]),
                       resamples=50)
        self.assertTrue(report["verification"]["complete"])
        metrics = report["video_level"]["A2"]["exclude"]["metrics"]
        self.assertEqual((metrics["recall"], metrics["specificity"], metrics["precision"]), (0.5, 0.5, 0.5))
        self.assertIn("reference negatives", metrics["denominators"]["specificity_and_false_positive_rate"])
        self.assertIn("A1_vs_A2", report["paired_comparisons"])

    def test_2_partial_review_withholds_classification_metrics(self):
        manifest = build([item("n1", "negative"), self.reviewed("n2", "negative", "random_audit")])
        report = score(manifest, results_file(manifest, [result("n1", "A2"), result("n2", "A2")]), resamples=50)
        self.assertFalse(report["verification"]["complete"])
        self.assertEqual(set(report["video_level"]), {"withheld"})

    def test_3_all_alerts_and_an_audit_sample_reviewed(self):
        manifest = self.technical()
        review = score(manifest, results_file(manifest, self.technical_rows()), resamples=50)["alert_review"]["A2"]
        self.assertTrue(review["all_alerts_reviewed"])
        self.assertEqual(review["confirmed_false_alerts"], 2)
        self.assertAlmostEqual(review["confirmed_false_alerts_per_analyzed_video_ci"]["estimate"], 2 / 8)
        self.assertEqual(review["random_audit"]["labels"], {"positive": 0, "negative": 2, "uncertain": 0})

    def test_4_no_alert_reviewed_withholds_confirmed_rates(self):
        manifest = build([item(f"m{i}", "missing") for i in range(3)], track="technical")
        rows = [result("m0", "A2", alert=True), result("m1", "A2", alert=True), result("m2", "A2")]
        review = score(manifest, results_file(manifest, rows), resamples=50)["alert_review"]["A2"]
        self.assertFalse(review["all_alerts_reviewed"])
        self.assertEqual(review["alerts_by_reference_label"]["missing"], 2)
        self.assertEqual(review["confirmed_false_alerts"], 0)
        self.assertIsNone(review["confirmed_false_alerts_per_analyzed_video_ci"])
        self.assertIsNone(review["confirmed_false_alerts_per_analyzed_hour"])

    def test_5_alert_rate_uses_every_analyzed_video(self):
        manifest = self.technical()
        rows = self.technical_rows(alert_on_unreviewed=True)
        rows[1] = result("m1", "A2", status="failed")  # failures are outside the denominator, and counted
        review = score(manifest, results_file(manifest, rows), resamples=50)["alert_review"]["A2"]
        self.assertEqual((review["completed_runs"], review["failed_or_partial_runs"]), (7, 1))
        self.assertEqual(review["alert_rate_unverified_ci"]["total"], 7)
        self.assertEqual(review["alert_rate_unverified_ci"]["successes"], 3)

    def test_6_confirmed_false_alerts_require_every_alert_reviewed(self):
        manifest = self.technical()
        complete = score(manifest, results_file(manifest, self.technical_rows()), resamples=50)
        incomplete = score(manifest, results_file(manifest, self.technical_rows(alert_on_unreviewed=True)),
                           resamples=50)
        self.assertIsNotNone(complete["alert_review"]["A2"]["confirmed_false_alerts_per_analyzed_video_ci"])
        self.assertIsNone(incomplete["alert_review"]["A2"]["confirmed_false_alerts_per_analyzed_video_ci"])

    def test_7_unsupported_metrics_and_paired_tests_are_suppressed(self):
        manifest = self.technical()
        report = score(manifest, results_file(manifest, self.technical_rows()), resamples=50)
        for section in ("video_level", "paired_comparisons", "event_level"):
            self.assertEqual(set(report[section]), {"withheld"})
        text = json.dumps(report)
        for name in ('"precision"', '"recall"', '"specificity"', '"f1"', '"mcnemar"'):
            self.assertNotIn(name, text)

    def test_8_9_10_pilot_overlap_is_refused_at_validation_and_scoring(self):
        independent = build([item("a", "negative")])
        same_media = build([{**item("a", "negative"), "sha256": "0" * 64}])
        same_source = build([item("a", "negative", group="synthetic_source")])
        report = score(independent, results_file(independent, [result("a", "A2")]), resamples=20)
        self.assertEqual(report["disjoint_from_pilot"]["pilot_clips"], 1)
        for manifest in (same_media, same_source):
            with self.assertRaises(ValueError):
                score(manifest, results_file(manifest, []), resamples=20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(same_source.model_dump_json(), encoding="utf-8")
            with self.assertRaises(ValueError):
                cli(["validate", str(path), "--pilot-manifest", str(PILOT)])
            with self.assertRaises(SystemExit):  # the check cannot be skipped from the CLI
                cli(["validate", str(path)])
            with self.assertRaises(SystemExit):
                cli(["score", str(path), str(path), "--output", str(Path(tmp) / "out")])

    def test_scoring_requires_media_identity_for_every_evaluable_item(self):
        manifest = build([{**item("a", "negative"), "sha256": None}])
        with self.assertRaises(ValueError):
            score(manifest, results_file(manifest, []), resamples=20)

    def test_11_unknown_and_uncertain_labels_are_never_scored_as_negatives(self):
        manifest = build([item("p", "positive"), item("n", "negative"), item("u", "uncertain"),
                          item("k", "negative", categories={**UNKNOWN, "nudity": "absent"})])
        report = score(manifest, results_file(manifest, [result("p", "A2", alert=True), result("n", "A2"),
                                                         result("u", "A2"), result("k", "A2")]), resamples=20)
        counts = report["video_level"]["A2"]["exclude"]["counts"]
        self.assertEqual((counts["tp"], counts["tn"], counts["uncertain_label"]), (1, 2, 1))
        self.assertEqual(report["sample_sizes"]["uncertain"], 1)

    def test_12_nsfw_discovered_in_the_technical_corpus_is_excluded_and_counted(self):
        discovered = {**self.reviewed("x", "positive", "alert_triggered"), "excluded": True,
                      "exclusion_reason": "nsfw_discovered"}
        with self.assertRaises(ValidationError):  # an unexcluded positive is refused in this track
            self.technical(extra=[{**discovered, "excluded": False, "exclusion_reason": ""}])
        manifest = self.technical(extra=[discovered])
        report = score(manifest, results_file(manifest, [*self.technical_rows(), result("x", "A2", alert=True)]),
                       resamples=20)
        self.assertEqual(report["sample_sizes"]["excluded_by_reason"], {"nsfw_discovered": 1})
        self.assertEqual(report["sample_sizes"]["excluded_reference_positives"], 1)
        self.assertEqual(report["sample_sizes"]["evaluable"], 8)
        self.assertEqual(report["alert_review"]["A2"]["alerted_videos"], 2)  # excluded video not scored


class CharadesManifestTests(unittest.TestCase):
    def synthetic_zip(self, tmp):
        import zipfile
        path = Path(tmp) / "Charades.zip"
        header = "id,subject,scene,quality,relevance,verified,script,objects,descriptions,actions,length\n"
        rows = []
        for i in range(12):
            action = "c155 1.0 4.0" if i % 2 else "c008 1.0 4.0"
            scene = "Kitchen" if i % 3 else "Bedroom"
            # Ordinary videos (i = 2, 4, 8, 10) belong to subjects S2/S4 only, hard ones never do.
            rows.append(f"V{i:03d},S{i % 6},{scene},7,7,Yes,script,obj,desc,{action},30.0")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Charades/Charades_v1_classes.txt", "c008 Opening a door\nc155 Someone is undressing\n")
            archive.writestr("Charades/Charades_v1_train.csv", header + "\n".join(rows[:8]) + "\n")
            archive.writestr("Charades/Charades_v1_test.csv", header + "\n".join(rows[8:]) + "\n")
        return path

    def test_deterministic_stratified_selection_with_subject_cap(self):
        from evaluation.benchmark import charades
        with tempfile.TemporaryDirectory() as tmp:
            path = self.synthetic_zip(tmp)
            first = charades.build_manifest(path, total=8, per_subject_cap=2)
            self.assertEqual(first, charades.build_manifest(path, total=8, per_subject_cap=2))
            manifest = BenchmarkManifest.model_validate(first)
            self.assertEqual(manifest.track, "technical")
            self.assertTrue(all(i.video_label == "missing" for i in manifest.items))
            groups = [i.group_id for i in manifest.items]
            self.assertLessEqual(max(groups.count(g) for g in set(groups)), 2)
            strata = [i.provenance["stratum"] for i in manifest.items]
            self.assertEqual((strata.count("hard"), strata.count("ordinary")), (4, 4))
            with self.assertRaises(ValueError):  # S2/S4 with cap 1 cannot supply 4 ordinary videos
                charades.build_manifest(path, total=8, per_subject_cap=1)


class CliTests(unittest.TestCase):
    def test_validate_and_score_write_a_new_report_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest = build([item("a", "positive"), item("b", "negative")])
            (tmp / "manifest.json").write_text(json.dumps(manifest_dict([item("a", "positive"), item("b", "negative")])),
                                               encoding="utf-8")
            results = results_file(manifest, [result("a", "A2", alert=True), result("b", "A2")])
            (tmp / "results.json").write_text(results.model_dump_json(), encoding="utf-8")
            self.assertEqual(cli(["validate", str(tmp / "manifest.json"), "--pilot-manifest",
                                  str(PILOT)]), 0)
            out = tmp / "report"
            self.assertEqual(cli(["score", str(tmp / "manifest.json"), str(tmp / "results.json"),
                                  "--pilot-manifest", str(PILOT),
                                  "--output", str(out), "--resamples", "50"]), 0)
            metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["video_level"]["A2"]["exclude"]["counts"]["tp"], 1)
            self.assertTrue((out / "per_video.csv").is_file())
            with self.assertRaises(FileExistsError):
                cli(["score", str(tmp / "manifest.json"), str(tmp / "results.json"), "--output", str(out),
                     "--pilot-manifest", str(PILOT)])
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
