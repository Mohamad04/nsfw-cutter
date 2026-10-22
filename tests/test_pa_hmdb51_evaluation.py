"""PA-HMDB51 evaluation tooling: annotation parsing, verified conversion, analysis and review scoring.

Synthetic, non-sensitive data only (FFmpeg test patterns and mocked pipeline outputs).
"""

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from evaluation.pa_hmdb51 import annotations as pa
from evaluation.pa_hmdb51 import prepare
from evaluation.pa_hmdb51.analyze import REVIEW_COLUMNS, analyze
from evaluation.pa_hmdb51.review import score_review, validate_row
from tests.test_benchmark_runner import HEALTHY, NOT_APPLICABLE, PILOT, Campaign

FFMPEG = prepare.FFMPEG_BIN / "ffmpeg.exe"
ENTRY = {"face": [[0, 9, 2]], "gender": [[0, 9, [1, 2]]], "skin_color": [[0, 9, 1]],
         "nudity": [[0, 4, 0], [5, 9, 2]], "relationship": [[0, 9, 1]], "review": False, "note": ""}


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class AnnotationTests(unittest.TestCase):
    def test_segments_values_and_nudity_levels(self):
        video = pa.parse_video("x_kiss_h_cm_np2_ri_goo_1.avi", ENTRY)
        self.assertEqual(video.issues, [])
        self.assertEqual(video.nudity_frames(), {0: 5, 1: 0, 2: 5})
        self.assertEqual(video.max_nudity(), 2)
        self.assertEqual(video.attribute("gender")[0].values, (1, 2))  # coexisting people
        self.assertEqual(video.extent(), (0, 9))

    def test_unannotated_frames_and_undefined_values_are_reported_not_fixed(self):
        entry = {**ENTRY, "nudity": [[1, 4, 0], [7, 9, 5]]}
        issues = pa.parse_video("v.avi", entry).issues
        self.assertIn("nudity: frames 0-0 unannotated", issues)
        self.assertIn("nudity: frames 5-6 unannotated", issues)
        self.assertIn("nudity: undefined value(s) [5]", issues)
        overlap = pa.parse_video("v.avi", {**ENTRY, "nudity": [[0, 5, 0], [5, 9, 1]]})  # as in hug.json
        self.assertIn("nudity: frames 5-5 annotated twice", overlap.issues)
        with self.assertRaises(ValueError):
            pa.parse_video("v.avi", {**ENTRY, "nudity": [[5, 9, 1], [0, 4, 0]]})
        with self.assertRaises(ValueError):
            pa.parse_video("v.avi", {**ENTRY, "unexpected": 1})

    def test_no_privacy_value_is_a_reference_nsfw_label(self):
        self.assertEqual(pa.relation("nudity", 2)[0], "needs_human_review")
        self.assertEqual({pa.relation("nudity", v)[0] for v in (0, 1)}, {"presumption"})
        self.assertEqual(pa.NOT_COVERED, ("sexual_activity", "sexual_context"))
        usable = {u for attribute in pa.RELATION.values() for u, _ in attribute.values()}
        self.assertNotIn("reference_label", usable)

    def test_batch_selection_uses_privacy_attributes_only(self):
        annotated = {"a.avi": pa.parse_video("a.avi", ENTRY),
                     "b.avi": pa.parse_video("b.avi", {**ENTRY, "nudity": [[0, 9, 1]]})}
        members = {"a.avi": {}, "b.avi": {}, "c.avi": {}}
        self.assertEqual(prepare.select_members("all", members, annotated), ["a.avi", "b.avi", "c.avi"])
        self.assertEqual(prepare.select_members("annotated", members, annotated), ["a.avi", "b.avi"])
        self.assertEqual(prepare.select_members("pa_nudity2", members, annotated), ["a.avi"])
        with self.assertRaisesRegex(ValueError, "scopes must"):
            prepare.prepare(Path("."), Path("."), Path("."), actions=("kiss",), action_scopes={"dive": "all"})

    def test_hmdb_names_parse_with_the_known_action(self):
        tags = pa.parse_hmdb_name("BASE_JUMP!!!_dive_f_cm_np1_fr_bad_4.avi", "dive")
        self.assertEqual((tags["source"], tags["body"], tags["people"], tags["clip"]), ("BASE_JUMP!!!", "f", 1, 4))
        self.assertEqual(pa.parse_hmdb_name("a_b_climb_stairs_f_nm_np1_le_med_0.avi", "climb_stairs")["source"], "a_b")
        self.assertFalse(pa.parse_hmdb_name("unrelated.avi", "kiss")["parsed"])


class ConversionTests(unittest.TestCase):
    def setUp(self):
        if not FFMPEG.is_file():
            self.skipTest("project FFmpeg not available")
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_avi(self, name="x_kiss_h_cm_np2_ri_goo_1.avi"):
        path = self.tmp / name
        subprocess.run([str(FFMPEG), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=30",
                        "-t", "1", "-c:v", "mpeg4", "-bf", "2", "-vtag", "DX50", str(path)], check=True)
        return path

    def test_lossless_conversion_is_verified_frame_by_frame(self):
        avi = self.make_avi()
        entry = {"size": avi.stat().st_size, "crc32": prepare.crc32(avi)}
        record = prepare.prepare_video(avi, self.tmp / "out" / "x.mkv", entry)
        self.assertEqual(record["problems"], [])
        self.assertTrue(record["transformation"]["decoded_frames_identical"])
        self.assertEqual(record["original"]["decoded_frames"], record["evaluated"]["decoded_frames"], 30)
        self.assertEqual(record["evaluated"]["video_codec"], "h264")
        self.assertEqual(record["evaluated"]["app_validation"], "accepted")
        self.assertLessEqual(record["transformation"]["max_timeline_deviation_seconds"], 0.0011)
        self.assertAlmostEqual(record["frame_times_seconds"][3], 0.1, places=2)

    def test_corrupt_extraction_and_modified_output_are_detected(self):
        avi = self.make_avi()
        record = prepare.prepare_video(avi, self.tmp / "x.mkv", {"size": avi.stat().st_size, "crc32": "00000000"})
        self.assertIn("extraction_crc_or_size_mismatch", record["problems"])
        # An evaluated file that does not decode to the original frames is refused, never trusted.
        other = self.tmp / "other.mkv"
        subprocess.run([str(FFMPEG), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x48:rate=30",
                        "-t", "1", "-c:v", "libx264", str(other)], check=True)
        record = prepare.prepare_video(avi, other, {"size": avi.stat().st_size, "crc32": prepare.crc32(avi)})
        self.assertIn("decoded_frames_differ", record["problems"])

    def test_only_a_consistent_validator_rejection_excludes_a_video(self):
        from unittest import mock
        record = self.tmp / "item.json"
        self.assertEqual(prepare.validation_outcome(record, self.tmp / "x.mkv", "accepted"), ("accepted", ["accepted"]))
        with mock.patch.object(prepare, "app_validation", side_effect=["accepted"] * 3):
            outcome = prepare.validation_outcome(record, self.tmp / "x.mkv", "rejected:corrupted_media:media.incomplete")
        self.assertEqual(outcome[0], "intermittent")
        self.assertEqual(len(outcome[1]), 4)
        # The re-check is recorded once and reused, never silently redone.
        with mock.patch.object(prepare, "app_validation", side_effect=AssertionError("not re-run")):
            self.assertEqual(prepare.validation_outcome(record, self.tmp / "x.mkv", "rejected:x:y"),
                             ("intermittent", ["rejected:x:y", "accepted", "accepted", "accepted"]))
        other = self.tmp / "other.json"
        with mock.patch.object(prepare, "app_validation", side_effect=["rejected:x:y"] * 3):
            self.assertEqual(prepare.validation_outcome(other, self.tmp / "x.mkv", "rejected:x:y")[0], "rejected")

    def test_annotation_frames_map_to_decoded_presentation_times(self):
        video = pa.parse_video("v.avi", ENTRY)
        times = [i / 30 for i in range(10)]
        rows = prepare.mapping_rows("item", "kiss", video, times, 1 / 30)
        nudity2 = next(r for r in rows if r["attribute"] == "nudity" and r["value"] == 2)
        self.assertEqual((nudity2["start_seconds"], nudity2["end_seconds"]), (round(5 / 30, 4), round(10 / 30, 4)))
        self.assertEqual(nudity2["nsfw_usability"], "needs_human_review")
        short = prepare.mapping_rows("item", "kiss", video, times[:8], 1 / 30)
        self.assertFalse(next(r for r in short if r["attribute"] == "nudity" and r["value"] == 2)
                         ["within_decoded_frames"])
        self.assertEqual(len([r for r in rows if r["attribute"] == "gender"]), 2)  # one row per coexisting value


def analysis_band_check():
    from evaluation.pa_hmdb51.analyze import duration_band
    return [duration_band(s) for s in (2.467, 2.5, 7.499, 7.5)]


def prepared_tables(directory: Path, campaign: Campaign):
    """Minimal prepare outputs for the synthetic campaign items."""
    manifest = json.loads(campaign.manifest.read_text())
    rows = [{"item_id": item["item_id"], "action": "kiss" if index % 2 == 0 else "dive",
             "subset": "pilot" if index == 0 else "extension", "original_file_name": f"{item['item_id']}.avi",
             "pa_annotated": str(index == 0), "pa_max_nudity": "2" if index == 0 else "",
             "pa_relationship_identifiable_frames": "", "pa_review_flag": "", "excluded": "False"}
            for index, item in enumerate(manifest["items"])]
    write_csv(directory / "dataset_manifest.csv", rows)
    write_csv(directory / "annotation_mapping.csv", [
        {"item_id": rows[0]["item_id"], "attribute": "nudity", "value": "2", "start_seconds": "0.5",
         "end_seconds": "1.5"}])


class AnalysisAndReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.campaign = Campaign(self.tmp, names=("v1", "v2", "v3"))
        self.campaign.behaviour.update({
            "v1.mp4": {"alert": True, "marqo": 0.6, "warnings": [NOT_APPLICABLE]},
            "v2.mp4": {"marqo": 0.2, "warnings": [NOT_APPLICABLE]},
            "v3.mp4": {"marqo": 0.01, "warnings": [NOT_APPLICABLE]}})
        self.assertIsNone(self.campaign.run(configs=("A2",), sampler=lambda pid: HEALTHY)["stopped_at"])
        (self.tmp / "prepared").mkdir()
        prepared_tables(self.tmp / "prepared", self.campaign)
        self.out = self.tmp / "analysis"
        self.summary = analyze([(self.campaign.manifest, self.campaign.dir)], prepared=self.tmp / "prepared",
                               media_root=self.campaign.media_root, pilot_manifest=PILOT, output=self.out)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tables_metrics_and_withheld_accuracy(self):
        self.assertEqual((self.summary["completed"], self.summary["alerts_A2"], self.summary["events"]), (3, 1, 1))
        metrics = json.loads((self.out / "metrics.json").read_text(encoding="utf-8"))
        for level in ("binary_detection", "per_category", "temporal_localization"):
            self.assertEqual(metrics[level]["status"], "withheld")
        self.assertEqual(metrics["sampling_study"]["by_duration_band"]["<2.5 s"]["videos"], 3)  # 2.0 s fixtures
        self.assertEqual(analysis_band_check(), ["<2.5 s", "2.5-7.5 s", "2.5-7.5 s", ">=7.5 s"])
        self.assertIn("not false-positive rates", metrics["scope_warning"])
        self.assertEqual(metrics["label_free_alerts"]["A0@0.15"]["all"]["alerted_videos"], 2)
        self.assertEqual(metrics["label_free_alerts"]["A2"]["all"]["alerted_videos"], 1)
        self.assertEqual(metrics["technical"]["status_counts"], {"completed": 3})
        comparison = metrics["privacy_attribute_comparison"]
        self.assertEqual(comparison["alerts_by_pa_max_nudity"]["2"], {"A2": 1, "A0@0.15": 1, "A0@0.45": 1,
                                                                      "videos": 1})
        self.assertEqual(comparison["predicted_overlap_with_pa_nudity2_seconds"], 0.5)  # [0,1) and [0.5,1.5)
        predictions = read_csv(self.out / "predictions.csv")
        self.assertEqual([(p["item_id"], p["category"]) for p in predictions], [("v1", "nudity")])
        self.assertEqual(len(read_csv(self.out / "timings.csv")), 3)

    def test_review_sheet_is_blind_and_keyed(self):
        sheet = read_csv(self.out / "manual_review.csv")
        self.assertEqual(list(sheet[0]), list(REVIEW_COLUMNS))
        self.assertFalse({"A2_alert", "category", "pa_max_nudity", "item_id"} & set(sheet[0]))
        key = {r["review_id"]: r for r in read_csv(self.out / "manual_review_key.csv")}
        self.assertEqual(set(key), {r["review_id"] for r in sheet})
        self.assertEqual(next(r["selection"] for r in key.values() if r["item_id"] == "v1"), "A2_alert")
        self.assertEqual(next(r["selection"] for r in key.values() if r["item_id"] == "v2"), "random_audit")

    def test_partial_runs_are_reviewed_but_never_revealed(self):
        from evaluation.pa_hmdb51.analyze import review_sheet
        rows = [{"item_id": f"i{n}", "status": status, "A2_alert": alert, "A0@0.45_alert": False, "pa_annotated": "False",
                 "original_path": f"i{n}.avi", "duration_seconds": 2.0, "evaluated_sha256": "0" * 64}
                for n, (status, alert) in enumerate([("completed", True), ("partial", None), ("failed", None)])]
        out = self.tmp / "sheet"
        out.mkdir()
        summary = review_sheet(rows, out)
        key = {r["item_id"]: r["selection"] for r in read_csv(out / "manual_review_key.csv")}
        self.assertEqual(key, {"i0": "A2_alert", "i1": "random_audit"})  # failed runs have no usable input record
        self.assertEqual(summary["rows"], 2)
        self.assertNotIn("status", read_csv(out / "manual_review.csv")[0])

    def fill(self, labels):
        """labels: {item_id: dict of review columns}; returns the filled sheet path."""
        key = {r["review_id"]: r["item_id"] for r in read_csv(self.out / "manual_review_key.csv")}
        sheet = read_csv(self.out / "manual_review.csv")
        for row in sheet:
            row.update(labels.get(key[row["review_id"]], {}))
        path = self.tmp / "filled.csv"
        write_csv(path, sheet)
        return path

    NEG = {"reviewer_id": "r1", "watched_in_full": "yes", "nudity": "absent", "sexual_activity": "absent",
           "sexual_context": "absent", "video_label": "negative", "events": ""}

    def test_partial_review_publishes_confirmed_alerts_only(self):
        report = score_review(self.fill({"v1": self.NEG}), self.out)
        self.assertEqual(report["status"], "partial_review")
        self.assertNotIn("video_level", report)
        self.assertIn("withheld", report)
        self.assertEqual(report["alert_review"]["confirmed_false_alerts"], 1)
        self.assertEqual(report["precision_of_alerts_ci"]["estimate"], 0.0)
        self.assertIn("annotation_warning", report)

    def test_complete_review_scores_binary_category_and_localization(self):
        positive = {**self.NEG, "nudity": "present", "video_label": "positive", "events": "0.5-1.5:nudity"}
        report = score_review(self.fill({"v1": positive, "v2": self.NEG, "v3": self.NEG}), self.out)
        self.assertEqual(report["status"], "complete_review")
        video = report["video_level"]["exclude"]
        self.assertEqual((video["tp"], video["fp"], video["fn"], video["tn"]), (1, 0, 0, 2))
        self.assertEqual((video["precision"], video["recall"], video["f1"]), (1.0, 1.0, 1.0))
        self.assertEqual(report["classification_by_category"]["nudity"]["tp"], 1)
        self.assertEqual(report["category_errors_on_true_alerts"]["exact_category_match"], 1)
        binary = report["event_level"]["binary"]["event_metrics"]["0.25"]
        self.assertEqual((binary["tp"], binary["fp"], binary["fn"]), (1, 0, 0))  # IoU([0,1),[0.5,1.5)) = 1/3
        self.assertEqual(report["event_level"]["binary"]["event_metrics"]["0.50"]["tp"], 0)
        self.assertNotIn("scope_warning", report)

    def test_without_reference_positive_recall_is_undefined_not_zero(self):
        report = score_review(self.fill({v: self.NEG for v in ("v1", "v2", "v3")}), self.out)
        video = report["video_level"]["exclude"]
        self.assertIsNone(video["recall"])
        self.assertEqual(video["specificity"], 2 / 3)
        self.assertIn("scope_warning", report)

    def test_inconsistent_labels_are_rejected_and_not_scored(self):
        self.assertTrue(validate_row({**self.NEG, "watched_in_full": "no"}, 2.0))
        self.assertTrue(validate_row({**self.NEG, "nudity": "present"}, 2.0))
        self.assertTrue(validate_row({**self.NEG, "events": "1-0:nudity"}, 2.0))
        self.assertTrue(validate_row({**self.NEG, "video_label": "excluded"}, 2.0))  # no reason
        report = score_review(self.fill({"v1": {**self.NEG, "nudity": "present"}}), self.out)
        self.assertEqual(len(report["invalid_rows"]), 1)
        self.assertEqual(report["reviewed"], 0)

    def test_blind_package_is_built_from_the_manifest_only_and_scores_any_analysis(self):
        import hashlib

        from evaluation.pa_hmdb51.review import blind_package
        package = self.tmp / "package"
        record = blind_package(self.campaign.manifest, self.campaign.media_root, package)
        sheet, key = read_csv(package / "manual_review.csv"), read_csv(package / "manual_review_key.csv")
        self.assertEqual((record["videos"], record["prediction_independent"]), (3, True))
        self.assertEqual(list(sheet[0]), list(REVIEW_COLUMNS))
        self.assertFalse(any(item in json.dumps(sheet) for item in ("v1", "v2", "v3")))  # anonymous files
        for row, entry in zip(sheet, key):
            copy = package / row["file_to_watch"]
            self.assertEqual(hashlib.sha256(copy.read_bytes()).hexdigest(), entry["evaluated_sha256"])
        again = blind_package(self.campaign.manifest, self.campaign.media_root, self.tmp / "package2")
        self.assertEqual(again["key_sha256"], record["key_sha256"])  # deterministic order
        with self.assertRaises(FileExistsError):
            blind_package(self.campaign.manifest, self.campaign.media_root, package)
        by_item = {k["item_id"]: k["review_id"] for k in key}
        for row in sheet:
            row.update(self.NEG)
        filled = self.tmp / "package_filled.csv"
        write_csv(filled, sheet)
        report = score_review(filled, self.out, key_csv=package / "manual_review_key.csv")
        self.assertEqual(report["status"], "complete_review")
        self.assertEqual(report["video_level"]["exclude"]["fp"], 1)  # v1 alerted, reviewed negative
        self.assertIn("v1", by_item)

    def test_analysis_never_overwrites(self):
        with self.assertRaises(FileExistsError):
            analyze([(self.campaign.manifest, self.campaign.dir)], prepared=self.tmp / "prepared",
                    media_root=self.campaign.media_root, pilot_manifest=PILOT, output=self.out)


class CliTests(unittest.TestCase):
    def test_run_requires_explicit_inference_permission(self):
        from evaluation.pa_hmdb51.__main__ import main
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Campaign(tmp)
            with self.assertRaises(PermissionError):
                main(["run", str(campaign.manifest), "--media-root", str(campaign.media_root),
                      "--campaign", str(Path(tmp) / "c"), "--pilot-manifest", str(PILOT)])
