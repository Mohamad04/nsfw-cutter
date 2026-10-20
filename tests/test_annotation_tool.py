"""Single-reviewer annotation tool: rules, session safety, blinding and benchmark compatibility.

Synthetic, non-sensitive fixtures only (random bytes and an FFmpeg test pattern); no model is loaded.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.annotation.coverage import (
    PlaybackTracker,
    covered_seconds,
    fully_played,
    unplayed_seconds,
    unplayed_segments,
)
from evaluation.annotation.record import empty_record, validate, video_label
from evaluation.annotation.session import (
    VISIBLE_FIELDS,
    LockedError,
    Session,
    to_reference,
)
from evaluation.benchmark.labels import apply_reference_labels
from evaluation.benchmark.manifest import (
    BenchmarkManifest,
    load_manifest,
    manifest_digest,
)
from evaluation.benchmark.report import score
from evaluation.benchmark.results import ResultsFile

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "tests" / "fixtures" / "pilot" / "synthetic.json"
GUIDE = ROOT / "docs" / "nsfw_annotation_guide.md"
FFMPEG = ROOT / "vendor" / "ffmpeg" / "bin" / "ffmpeg.exe"
UNKNOWN = {"nudity": "unknown", "sexual_activity": "unknown", "sexual_context": "unknown"}


def sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def write_campaign(tmp: Path, names=("a", "b", "c", "d"), media=None):
    """Technical-track manifest with unreviewed items, its media and a provenance hint the tool must hide."""
    media_root = tmp / "media"
    media_root.mkdir()
    items = []
    for n, name in enumerate(names):
        data = (media or {}).get(name) or f"synthetic-{name}".encode() * 64
        (media_root / f"{name}.mp4").write_bytes(data)
        items.append({"item_id": name, "group_id": f"g{n % 3}", "split": "test", "file_name": f"{name}.mp4",
                      "sha256": sha(data), "duration_seconds": 30.0, "has_audio": True, "video_label": "missing",
                      "category_labels": UNKNOWN,
                      "provenance": {"stratum": "hard", "scene": "Bathroom", "pilot5_integration_validation": True,
                                     "charades_activity": "SECRET-HINT"}})
    manifest = {"schema_version": 1, "benchmark_id": "synthetic_annotation", "track": "technical",
                "synthetic_fixture": True,
                "dataset": {"dataset_id": "synthetic", "name": "Synthetic", "publisher": "tests",
                            "homepage": "https://example.org/s", "version": "1", "license_id": "CC0-1.0",
                            "license_evidence": [{"url": "https://example.org/l", "retrieved": "2026-10-20",
                                                  "statement": "synthetic"}],
                            "access": "ungated", "permitted_use": "tests", "redistribution_allowed": True,
                            "content": "synthetic"},
                "annotation": {"version": "0", "source": "project_annotators", "guideline": "none yet"},
                "items": items}
    path = tmp / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, media_root


def negative(record):
    record.update(categories={"nudity": "absent", "sexual_activity": "absent", "sexual_context": "absent"},
                  watched_in_full=True, played_intervals=[[0.0, record["duration_seconds"]]], audio_listened=True)
    return record


def positive(record, category="nudity", context="nonsexual_everyday"):
    record["categories"] = {"nudity": "absent", "sexual_activity": "absent", "sexual_context": "absent",
                            category: "present"}
    record["nudity_context"] = context if category == "nudity" else None
    record["events"] = [{"category": category, "start_seconds": 4.0, "end_seconds": 9.5}]
    record.update(watched_in_full=True, played_intervals=[[0.0, record["duration_seconds"]]], audio_listened=True)
    return record


class RecordRuleTests(unittest.TestCase):
    def blank(self):
        return empty_record("a", "0" * 64, 30.0, True)

    def test_valid_label_and_category_combinations(self):
        self.assertEqual((video_label(negative(self.blank())), validate(negative(self.blank()))), ("negative", []))
        self.assertEqual((video_label(positive(self.blank())), validate(positive(self.blank()))), ("positive", []))
        for category in ("sexual_activity", "sexual_context"):
            self.assertEqual(validate(positive(self.blank(), category)), [])
        self.assertIsNone(video_label(self.blank()))
        self.assertTrue(validate(self.blank()))  # every category must be chosen explicitly

    def test_nudity_context_is_required_only_for_nudity(self):
        record = positive(self.blank())
        record["nudity_context"] = None
        self.assertTrue(any("nudity_context" in p for p in validate(record)))
        record = negative(self.blank())
        record["nudity_context"] = "sexual"
        self.assertTrue(any("only applies" in p for p in validate(record)))
        record = positive(self.blank(), context="nonsexual_medical")
        self.assertEqual(video_label(record), "positive")  # context never changes the label

    def test_negative_requires_full_viewing_coverage_and_listening(self):
        for change in ({"watched_in_full": False}, {"audio_listened": False}):
            record = negative(self.blank())
            record.update(change)
            self.assertEqual(video_label(record), "uncertain")
            self.assertTrue(any("notes" in p for p in validate(record)))  # must explain, never silently negative
            record["notes"] = "stopped at 20 s: interrupted"
            self.assertEqual(validate(record), [])
        record = negative(self.blank())
        record["played_intervals"] = [[0.0, 18.0], [20.0, 30.0]]  # 2 s skipped, then ticked anyway
        record["playback_coverage"] = 1.0  # a stored percentage is never trusted
        self.assertNotEqual(video_label(record), "negative")
        self.assertTrue(any("2.0 s unplayed" in p for p in validate(record)))
        record["played_intervals"] = [[0.0, 29.6]]  # end-of-stream timing within the 0.5 s tolerance
        self.assertEqual(video_label(record), "negative")
        silent = negative(empty_record("a", "0" * 64, 30.0, False))
        silent["audio_listened"] = False
        self.assertEqual(video_label(silent), "negative")  # no audio stream, nothing to listen to

    def test_uncertain_and_excluded_records(self):
        record = negative(self.blank())
        record["categories"]["sexual_context"] = "uncertain"
        self.assertTrue(any("at least one interval" in p for p in validate(record)))
        record["events"] = [{"category": "sexual_context", "start_seconds": 1.0, "end_seconds": 3.0}]
        self.assertEqual((video_label(record), validate(record)), ("uncertain", []))
        stopped = self.blank()
        stopped["escalation"] = "age_uncertain"
        self.assertTrue(any("exclusion reason" in p for p in validate(stopped)))
        stopped["exclusion_reason"] = "age_uncertain"
        self.assertEqual((video_label(stopped), validate(stopped)), ("excluded", []))  # categories may stay blank
        unreadable = self.blank()
        unreadable["exclusion_reason"] = "unreadable_media"
        self.assertEqual(video_label(unreadable), "excluded")

    def test_temporal_interval_validation(self):
        cases = [({"start_seconds": 9.0, "end_seconds": 4.0}, "start < end"),
                 ({"start_seconds": 25.0, "end_seconds": 31.0}, "start < end"),
                 ({"start_seconds": -1.0, "end_seconds": 2.0}, "start < end"),
                 ({"category": "sexual_activity"}, "not present or uncertain"),
                 ({"category": "violence"}, "unknown category")]
        for change, message in cases:
            record = positive(self.blank())
            record["events"] = [{**record["events"][0], **change}]
            with self.subTest(change=change):
                self.assertTrue(any(message in p for p in validate(record)), validate(record))
        record = positive(self.blank())
        record["events"].append({"category": "nudity", "start_seconds": 10.5, "end_seconds": 12.0})
        self.assertTrue(any("merged" in p for p in validate(record)))  # 1 s gap: one interval per the guide
        record["events"][1] = {"category": "nudity", "start_seconds": 12.0, "end_seconds": 14.0}
        self.assertEqual(validate(record), [])


class PlaybackTrackerTests(unittest.TestCase):
    """Positions reported every 50 ms of wall-clock time, as the player does while playing."""

    def play(self, tracker, start, end, rate=1.0, wall=0.0, step=0.05):
        tracker.observe(start, wall, rate)
        k, position = 0, start
        while position < end:
            k += 1
            position = min(end, round(start + k * rate * step, 6))
            tracker.observe(position, round(wall + k * step, 6), rate)
        return round(wall + k * step, 6)

    def test_continuous_playback_at_any_speed_is_fully_counted(self):
        for rate in (0.5, 1.0, 2.0):
            tracker = PlaybackTracker()
            self.play(tracker, 0.0, 30.0, rate=rate)
            with self.subTest(rate=rate):
                self.assertEqual(tracker.intervals, [[0.0, 30.0]])
                self.assertTrue(fully_played(tracker.intervals, 30.0))

    def test_seeking_never_counts_skipped_content(self):
        tracker = PlaybackTracker()
        wall = self.play(tracker, 0.0, 10.0)
        tracker.interrupt()  # the interface interrupts on every seek
        wall = self.play(tracker, 20.0, 30.0, wall=wall)
        self.assertEqual(tracker.intervals, [[0.0, 10.0], [20.0, 30.0]])
        self.assertEqual(unplayed_segments(tracker.intervals, 30.0), [[10.0, 20.0]])
        self.assertFalse(fully_played(tracker.intervals, 30.0))
        # A jump that the interface did not announce is still rejected: it outruns the wall clock.
        unannounced = PlaybackTracker()
        unannounced.observe(5.0, 0.0, 1.0)
        self.assertFalse(unannounced.observe(9.0, 0.05, 1.0))
        self.assertFalse(unannounced.observe(3.0, 0.10, 1.0))  # backwards
        self.assertEqual(unannounced.intervals, [])

    def test_fast_forward_reports_inconsistent_with_the_rate_are_rejected(self):
        tracker = PlaybackTracker()
        tracker.observe(0.0, 0.0, 1.0)
        self.assertFalse(tracker.observe(1.0, 0.05, 1.0))  # 1 s of media in 50 ms at 1x
        self.assertTrue(tracker.observe(1.1, 0.10, 1.0))
        self.assertFalse(tracker.observe(1.3, 0.15, 2.0))  # rate changed without interruption: not counted

    def test_replay_counts_each_segment_once(self):
        tracker = PlaybackTracker()
        wall = self.play(tracker, 0.0, 12.0)
        tracker.interrupt()
        wall = self.play(tracker, 5.0, 12.0, wall=wall)
        self.assertEqual(tracker.intervals, [[0.0, 12.0]])
        self.assertAlmostEqual(covered_seconds(tracker.intervals, 30.0), 12.0)

    def test_interrupted_playback_resumes_without_counting_the_pause(self):
        tracker = PlaybackTracker()
        wall = self.play(tracker, 0.0, 14.0)
        tracker.interrupt()  # pause for ten minutes
        self.play(tracker, 14.0, 30.0, wall=wall + 600)
        self.assertEqual(tracker.intervals, [[0.0, 30.0]])
        resumed = PlaybackTracker(tracker.intervals[:1])  # restored from a saved draft
        self.assertTrue(fully_played(resumed.intervals, 30.0))

    def test_incomplete_viewing_cannot_be_confirmed(self):
        tracker = PlaybackTracker()
        self.play(tracker, 0.0, 28.0)
        self.assertAlmostEqual(unplayed_seconds(tracker.intervals, 30.0), 2.0)
        record = negative(empty_record("a", "0" * 64, 30.0, True))
        record["played_intervals"] = tracker.intervals
        self.assertEqual(video_label(record), "uncertain")
        self.assertTrue(any("unplayed" in p for p in validate(record)))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.manifest, self.media = write_campaign(self.tmp)
        self.session = Session.create(self.tmp / "session", self.manifest, self.media, reviewer_id="R1",
                                      guide_path=GUIDE, seed=1001)

    def tearDown(self):
        self._tmp.cleanup()

    def record(self, item_id):
        return self.session.load(item_id)[0]

    def test_review_order_is_seeded_and_matches_the_blinded_kit_shuffle(self):
        expected = ["a", "b", "c", "d"]
        random.Random(1001).shuffle(expected)
        self.assertEqual(self.session.order, expected)
        self.assertTrue(self.session.identity["single_reviewer"])
        self.assertEqual(self.session.identity["guide_sha256"], sha(GUIDE.read_bytes()))

    def test_drafts_resume_after_interruption_and_are_replaced_atomically(self):
        draft = self.record("a")
        draft["categories"]["nudity"] = "absent"
        draft["notes"] = "half done"
        self.session.save_draft(draft)
        reopened = Session(self.tmp / "session", self.manifest, self.media)  # e.g. after a crash or restart
        record, state = reopened.load("a")
        self.assertEqual((state, record["notes"], record["categories"]["nudity"]), ("draft", "half done", "absent"))
        self.assertEqual(reopened.progress()["drafts"], 1)
        self.assertEqual(list((self.tmp / "session" / "drafts").glob(".*.tmp")), [])

    def test_locked_records_are_never_overwritten(self):
        first = self.session.lock(negative(self.record("a")))
        original = first.read_bytes()
        self.assertEqual(self.session.load("a")[1], "locked")
        self.assertFalse((self.tmp / "session" / "drafts" / "a.json").exists())
        with self.assertRaises(LockedError):
            self.session.save_draft(negative(self.record("a")))
        with self.assertRaises(LockedError):
            self.session.lock(negative(self.record("a")))
        amended = positive(self.record("a"))
        second = self.session.lock(amended, amendment_reason="nudity seen on second viewing")
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(second.name, "v002.json")
        locked = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(locked["amends_sha256"], sha(original))
        self.assertEqual(self.session.load("a")[0]["categories"]["nudity"], "present")
        events = [json.loads(line)["event"] for line in (self.tmp / "session" / "audit.jsonl").read_text().splitlines()]
        self.assertIn("locked", events)
        self.assertIn("amended", events)

    def test_invalid_records_cannot_be_locked(self):
        with self.assertRaises(ValueError):
            self.session.lock(self.record("a"))  # nothing chosen
        foreign = negative(self.record("a"))
        foreign["sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            self.session.save_draft(foreign)

    def test_source_hashes_are_verified_before_locking(self):
        (self.media / "b.mp4").write_bytes(b"modified on disk")
        reopened = Session(self.tmp / "session", self.manifest, self.media)
        self.assertFalse(reopened.verify_media("b"))
        with self.assertRaises(ValueError):
            reopened.lock(negative(reopened.load("b")[0]))
        excluded = reopened.load("b")[0]
        excluded["exclusion_reason"] = "sha256_mismatch"
        reopened.lock(excluded)
        self.assertTrue(reopened.verify_media("a"))
        audit = (self.tmp / "session" / "audit.jsonl").read_text()
        self.assertIn("media_sha256_mismatch", audit)

    def test_session_is_bound_to_its_manifest_file(self):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["items"][0]["duration_seconds"] = 31.0
        other = self.tmp / "other.json"
        other.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            Session(self.tmp / "session", other, self.media)
        with self.assertRaises(FileExistsError):
            Session.create(self.tmp / "session", self.manifest, self.media, reviewer_id="R1", guide_path=GUIDE,
                           seed=1)


class BlindingTests(unittest.TestCase):
    def test_the_interface_view_exposes_no_identity_hint_or_prediction(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, media = write_campaign(Path(tmp))
            session = Session.create(Path(tmp) / "s", manifest, media, reviewer_id="R1", guide_path=GUIDE, seed=3)
            view = session.view("a")
            self.assertEqual(set(view), {*VISIBLE_FIELDS, "media_path"})
            text = json.dumps(view)
            for hint in ("SECRET-HINT", "Bathroom", "hard", "pilot5", "g0"):
                self.assertNotIn(hint, text)

    def test_the_tool_never_reads_campaign_outputs_or_imports_model_code(self):
        sources = "".join((ROOT / "evaluation" / "annotation" / name).read_text(encoding="utf-8")
                          for name in ("record.py", "session.py", "app.py", "__main__.py"))
        for forbidden in ("benchmark-runs", "results.json", "metrics.json", "per_video", "observations.jsonl",
                          "record.json", "evaluation.benchmark.runner", "evaluation.benchmark.report",
                          "services.analysis"):
            self.assertNotIn(forbidden, sources)
        probe = ("import sys, evaluation.annotation.session, evaluation.annotation.app, evaluation.annotation.__main__;"
                 "bad = [m for m in ('torch', 'transformers', 'faster_whisper', 'ctranslate2', 'open_clip',"
                 " 'services.analysis', 'evaluation.benchmark.runner', 'evaluation.benchmark.report') if m in sys.modules];"
                 "print(bad)")
        output = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, timeout=120,
                                check=False,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        self.assertEqual(output.stdout.strip(), "[]", output.stderr)


class BenchmarkCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.manifest, self.media = write_campaign(self.tmp)
        self.session = Session.create(self.tmp / "s", self.manifest, self.media, reviewer_id="R1", guide_path=GUIDE,
                                      seed=7)

    def tearDown(self):
        self._tmp.cleanup()

    def annotate_all(self):
        records = {i: self.session.load(i)[0] for i in self.session.order}
        self.session.lock(negative(records["a"]))
        self.session.lock(positive(records["b"]))  # NSFW discovered in the presumed-negative corpus
        uncertain = negative(records["c"])
        uncertain["categories"]["sexual_context"] = "uncertain"
        uncertain["events"] = [{"category": "sexual_context", "start_seconds": 2.0, "end_seconds": 5.0}]
        self.session.lock(uncertain)
        stopped = records["d"]
        stopped.update(escalation="consent_uncertain", exclusion_reason="consent_uncertain")
        self.session.lock(stopped)

    def results(self, manifest):
        rows = []
        for item in manifest.items:
            for config in ("A2", "A1"):
                identity = {"sha256": item.sha256} if config == "A2" else {
                    "sha256": sha(item.sha256.encode()), "derived_from_sha256": item.sha256,
                    "video_packets_verified_identical": True}
                alert = item.item_id in ("a", "b")
                rows.append({"item_id": item.item_id, "config": config, "status": "completed", "input": identity,
                             "suggestions": [{"id": "s", "start_seconds": 4.0, "end_seconds": 9.0, "category": "nudity",
                                              "final_confidence": 0.9}] if alert else [],
                             "marqo_scores": [{"timestamp_seconds": 0.0, "probability": 0.5 if alert else 0.1}],
                             "pipeline_seconds": 10.0, "start_mode": "cold_process"})
        return ResultsFile.model_validate({
            "schema_version": 1, "benchmark_id": manifest.benchmark_id, "manifest_digest": manifest_digest(manifest),
            "environment": {"commit": "2399e950aeb33dd7925690c78d3f5f25d50d07cb", "model_revisions": {"q": "r"},
                            "whisper_backend": "cuda_float16", "gpu": "synthetic", "driver": "0"},
            "results": rows})

    def test_export_requires_a_complete_review(self):
        self.session.lock(negative(self.session.load("a")[0]))
        with self.assertRaises(ValueError):
            self.session.export_labels(self.tmp / "labels.json")
        self.assertFalse((self.tmp / "labels.json").exists())

    def test_exported_labels_satisfy_the_benchmark_manifest_contract(self):
        self.annotate_all()
        labels = self.session.export_labels(self.tmp / "labels.json")
        with self.assertRaises(FileExistsError):
            self.session.export_labels(self.tmp / "labels.json")
        base = load_manifest(self.manifest)
        labelled, record = apply_reference_labels(base, labels)
        self.assertIsInstance(labelled, BenchmarkManifest)
        self.assertTrue(record["single_reviewer"])
        items = {i.item_id: i for i in labelled.items}
        self.assertEqual((items["a"].video_label, items["a"].review_basis, items["a"].excluded),
                         ("negative", "complete", False))
        self.assertEqual((items["b"].video_label, items["b"].exclusion_reason), ("positive", "nsfw_discovered"))
        self.assertEqual(items["b"].provenance["nudity_context"], "nonsexual_everyday")
        self.assertEqual(items["b"].temporal.events[0].categories, ["nudity"])
        self.assertEqual(items["c"].video_label, "uncertain")
        self.assertEqual(items["c"].category_labels["sexual_context"], "unknown")  # never absent
        self.assertEqual(items["c"].temporal.excluded_intervals[0].kind, "ambiguous")
        self.assertEqual((items["d"].excluded, items["d"].exclusion_reason), (True, "consent_uncertain"))
        self.assertEqual(manifest_digest(base), labels["base_manifest_digest"])  # base manifest untouched

    def test_labels_score_existing_results_without_rewriting_them(self):
        self.annotate_all()
        labels = self.session.export_labels(self.tmp / "labels.json")
        base = load_manifest(self.manifest)
        results = self.results(base)
        report = score(base, results, pilot_manifest=PILOT, resamples=50, labels=labels)
        self.assertEqual(report["manifest_digest"], manifest_digest(base))
        self.assertIn("single reviewer", report["annotation_warning"])
        self.assertEqual(report["sample_sizes"]["excluded_by_reason"], {"consent_uncertain": 1, "nsfw_discovered": 1})
        self.assertEqual(report["sample_sizes"]["excluded_reference_positives"], 1)
        counts = report["video_level"]["A2"]["exclude"]["counts"]
        self.assertEqual((counts["fp"], counts["tn"], counts["uncertain_label"]), (1, 0, 1))
        unlabelled = score(base, results, pilot_manifest=PILOT, resamples=50)
        self.assertIn("withheld", unlabelled["video_level"])

    def test_labels_for_another_manifest_or_media_are_refused(self):
        self.annotate_all()
        labels = self.session.export_labels(self.tmp / "labels.json")
        base = load_manifest(self.manifest)
        wrong = json.loads(json.dumps(labels))
        wrong["base_manifest_digest"] = "0" * 64
        with self.assertRaises(ValueError):
            apply_reference_labels(base, wrong)
        wrong = json.loads(json.dumps(labels))
        wrong["items"]["a"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            apply_reference_labels(base, wrong)
        wrong = json.loads(json.dumps(labels))
        del wrong["items"]["a"]
        with self.assertRaises(ValueError):
            apply_reference_labels(base, wrong)

    def test_discovered_positives_stay_visible_with_their_labels_and_alerts(self):
        self.annotate_all()
        labels = self.session.export_labels(self.tmp / "labels.json")
        base = load_manifest(self.manifest)
        report = score(base, self.results(base), pilot_manifest=PILOT, resamples=20, labels=labels)
        outcomes = report["excluded_reference_positives_outcomes"]
        self.assertEqual(outcomes["count"], 1)
        row = outcomes["items"][0]
        self.assertEqual((row["item_id"], row["exclusion_reason"]), ("b", "nsfw_discovered"))
        self.assertEqual(row["category_labels"]["nudity"], "present")
        self.assertEqual(row["events"], [{"start_seconds": 4.0, "end_seconds": 9.5, "categories": ["nudity"]}])
        self.assertEqual(row["alerts"], {"A1": True, "A2": True, "A0@0.15": True, "A0@0.45": True})
        self.assertEqual(row["media_sha256"], base.items[1].sha256)
        self.assertEqual(row["reference_record_sha256"], labels["items"]["b"]["record"]["sha256"])
        self.assertIn("not an independent measure", outcomes["note"])
        self.assertNotIn("b", [r["item_id"] for r in report["per_video"]])  # never scored as a negative
        # A sensitivity subset may still name an item that review already excluded.
        subset = {"subset_id": "without_b_subject", "reason": "test", "exclude_item_ids": ["b"]}
        scored = score(base, self.results(base), pilot_manifest=PILOT, resamples=20, labels=labels, subset=subset)
        self.assertEqual(scored["subset"]["already_excluded"], {"b": "nsfw_discovered"})
        self.assertEqual(scored["excluded_reference_positives_outcomes"]["count"], 1)

    def test_reference_mapping_keeps_partial_judgements_of_stopped_reviews(self):
        record = empty_record("x", "0" * 64, 30.0, True)
        record["categories"]["nudity"] = "present"
        record.update(escalation="age_uncertain", exclusion_reason="age_uncertain")
        mapped = to_reference(record, "technical")
        self.assertEqual((mapped["video_label"], mapped["excluded"], mapped["temporal"]), ("positive", True, None))
        self.assertEqual(mapped["category_labels"]["sexual_activity"], "unknown")


@unittest.skipUnless(FFMPEG.exists(), "vendored FFmpeg required for the synthetic test pattern")
class ReviewWindowSmokeTests(unittest.TestCase):
    """Offscreen: builds the window on a synthetic test pattern; does not rely on real-time playback."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_window_records_choices_coverage_and_escalation(self):
        from evaluation.annotation.app import ReviewWindow
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp = Path(tmp)
            video = tmp / "pattern.mp4"
            subprocess.run([str(FFMPEG), "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=3",
                            "-pix_fmt", "yuv420p", str(video)], check=True, timeout=120)
            manifest, media = write_campaign(tmp, names=("a", "b"), media={"a": video.read_bytes(),
                                                                         "b": video.read_bytes() + b"\0"})
            session = Session.create(tmp / "s", manifest, media, reviewer_id="R1", guide_path=GUIDE, seed=1)
            window = ReviewWindow(session)
            try:
                item = window.item_id
                for text in (window.windowTitle(), window.header.text()):
                    self.assertNotIn(item, text)
                    self.assertNotIn(".mp4", text)
                self.assertFalse(window.watched.isEnabled())  # nothing played yet
                for n in range(301):  # 15 s of continuous position reports, then a jump to the end
                    window.observe(n * 0.05, n * 0.05, 1.0)
                window.observe(30.0, 15.1, 1.0)
                self.assertFalse(window.fully_played())
                self.assertFalse(window.watched.isEnabled())
                window.tracker.interrupt()
                for n in range(301):  # the second half genuinely played
                    window.observe(15.0 + n * 0.05, 100 + n * 0.05, 1.0)
                self.assertTrue(window.fully_played())
                self.assertTrue(window.watched.isEnabled())
                for group in window.category_groups.values():
                    next(b for b in group.buttons() if b.property("state") == "absent").click()
                window.watched.setChecked(True)
                window.listened.setChecked(True)
                self.assertIn("NÉGATIVE", window.label_view.text())
                window.save_draft()
                saved = json.loads((tmp / "s" / "drafts" / f"{item}.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["categories"]["nudity"], "absent")
                self.assertEqual(saved["played_intervals"], [[0.0, 30.0]])
                window.escalation.setCurrentText("age_uncertain")
                self.assertTrue(window.player.source().isEmpty())  # video unloaded immediately
                self.assertIn("EXCLUE", window.label_view.text())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
