from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
from pydantic import ValidationError

from scripts.evaluate_stage1 import main as evaluate_cli_main
from services.analysis.frame_extraction import ExtractedFrame
from services.analysis.preprocessing_contracts import (
    FrameDisposition,
    FrameSample,
    PreprocessingConfig,
    SampleReason,
)
from services.analysis.stage1_evaluation import (
    GroundTruthArtifact,
    GroundTruthInterval,
    GroundTruthVideo,
    Stage1EvaluationConfiguration,
    Stage1EvaluationDataError,
    Stage1ScoreArtifact,
    Stage1ScoreModel,
    Stage1ScoreSample,
    Stage1ScoreVideo,
    create_ground_truth_template,
    evaluate_thresholds,
    load_ground_truth_artifact,
    load_score_artifact,
    write_json_artifact,
    write_policy_csv,
)
from services.analysis.stage1_safety import (
    CPU_EXECUTION_PROVIDER,
    MODEL_SHA256,
    ResolvedSafetyModelArtifact,
    SafetyONNXSession,
)
from services.analysis.stage1_score_export import export_stage1_scores


def _score_sample(
    timestamp_seconds: float,
    *,
    nsfl: float = 0.05,
    nsfw: float = 0.05,
    sample_id: str | None = None,
) -> Stage1ScoreSample:
    sfw = 1.0 - nsfl - nsfw
    probabilities = (nsfl, nsfw, sfw)
    labels = ("NSFL", "NSFW", "SFW")
    return Stage1ScoreSample(
        sample_id=sample_id or f"sample-{timestamp_seconds:g}",
        timestamp_us=round(timestamp_seconds * 1_000_000),
        nsfl=nsfl,
        nsfw=nsfw,
        sfw=sfw,
        selected_label=labels[int(np.argmax(probabilities))],
        sample_reasons=("temporal_safety",),
    )


def _scores(
    samples: tuple[Stage1ScoreSample, ...],
    *,
    duration_seconds: float = 30.0,
    filename: str = "movie.mp4",
) -> Stage1ScoreArtifact:
    return Stage1ScoreArtifact(
        generated_at_utc="2026-01-01T00:00:00Z",
        video=Stage1ScoreVideo(
            filename=filename,
            duration_us=round(duration_seconds * 1_000_000),
            fingerprint=f"sha256:{'a' * 64}",
        ),
        model=Stage1ScoreModel(
            repo_id="OwenElliott/image-safety-classifier-s",
            revision="pinned",
            sha256="b" * 64,
            runtime="onnxruntime:test",
            providers=(CPU_EXECUTION_PROVIDER,),
        ),
        preprocessing=PreprocessingConfig(),
        samples=samples,
    )


def _ground_truth(
    intervals: tuple[GroundTruthInterval, ...],
    *,
    filename: str = "movie.mp4",
) -> GroundTruthArtifact:
    return GroundTruthArtifact(
        video=GroundTruthVideo(filename=filename),
        intervals=intervals,
    )


def _config(
    *,
    nsfw=(0.5,),
    nsfl=(0.5,),
    tolerance=5.0,
    context=5.0,
    merge_gap=2.0,
    minimum_recall=None,
) -> Stage1EvaluationConfiguration:
    return Stage1EvaluationConfiguration(
        nsfw_thresholds=nsfw,
        nsfl_thresholds=nsfl,
        tolerance_seconds=tolerance,
        window_context_seconds=context,
        window_merge_gap_seconds=merge_gap,
        minimum_recall=minimum_recall,
    )


class Stage1EvaluationSchemaTests(unittest.TestCase):
    def test_score_schema_validates_probability_timestamp_and_order_invariants(self):
        with self.assertRaisesRegex(ValidationError, "sum to one"):
            Stage1ScoreSample(
                sample_id="bad",
                timestamp_us=0,
                nsfl=0.2,
                nsfw=0.2,
                sfw=0.2,
                selected_label="SFW",
                sample_reasons=("temporal_safety",),
            )
        with self.assertRaisesRegex(ValidationError, "sorted"):
            _scores((_score_sample(2), _score_sample(1)))
        with self.assertRaisesRegex(ValidationError, "movie duration"):
            _scores((_score_sample(31),), duration_seconds=30)

    def test_annotation_schema_rejects_malformed_reversed_and_out_of_range_times(self):
        for start, end in (
            ("bad", "00:00:02.000"),
            ("00:00:02.000", "00:00:01.000"),
            ("-1:00:00", "00:00:01.000"),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValidationError):
                GroundTruthInterval(start=start, end=end)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gt.json"
            path.write_text(
                _ground_truth(
                    (GroundTruthInterval(start="00:00:29", end="00:00:31"),)
                ).model_dump_json(),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(Stage1EvaluationDataError, "movie duration"):
                load_ground_truth_artifact(
                    path,
                    duration_us=30_000_000,
                    default_video_filename="movie.mp4",
                )

    def test_existing_cut_json_is_accepted_without_category_or_severity(self):
        payload = {
            "version": 1,
            "video": {"filename": "movie.mp4", "duration": 30.0},
            "cuts": [
                {"start": "00:00:10.000", "end": "00:00:12.000"},
                {"start": 11.0, "end": 15.0},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cuts.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            artifact, source = load_ground_truth_artifact(
                path,
                duration_us=30_000_000,
                default_video_filename="fallback.mp4",
            )

        self.assertEqual(source, "cut_json")
        self.assertEqual(len(artifact.intervals), 2)
        self.assertTrue(all(interval.category is None for interval in artifact.intervals))

    def test_json_score_export_reload_template_and_csv_round_trip(self):
        scores = _scores((_score_sample(1), _score_sample(2)))
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:00", end="00:00:03"),)
        )
        report = evaluate_thresholds(scores, ground_truth, _config())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score_path = write_json_artifact(scores, root / "scores.json")
            report_path = write_json_artifact(report, root / "report.json")
            csv_path = write_policy_csv(report, root / "policies.csv")
            reloaded = load_score_artifact(score_path)
            template = create_ground_truth_template(reloaded)

            self.assertEqual(reloaded, scores)
            self.assertEqual(template.video.filename, "movie.mp4")
            self.assertEqual(template.intervals, ())
            self.assertEqual(json.loads(report_path.read_text())["schema_version"], 1)
            self.assertIn("nsfw_threshold,nsfl_threshold", csv_path.read_text())
            self.assertFalse(any(path.suffix == ".tmp" for path in root.iterdir()))


class Stage1MetricTests(unittest.TestCase):
    def test_exact_tolerant_recall_and_missed_detail(self):
        scores = _scores(
            (
                _score_sample(9, nsfw=0.7),
                _score_sample(20, nsfw=0.1),
            )
        )
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:10", end="00:00:12"),)
        )

        result = evaluate_thresholds(scores, ground_truth, _config()).policies[0]

        self.assertEqual(result.detected_intervals, 0)
        self.assertEqual(result.missed_intervals, 1)
        self.assertEqual(result.interval_recall, 0.0)
        self.assertEqual(result.tolerant_interval_recall_5s, 1.0)
        detail = result.missed_interval_details[0]
        self.assertTrue(detail.tolerant_detected)
        self.assertIsNone(detail.max_nsfw_probability_exact)
        self.assertEqual(detail.max_nsfw_probability_tolerant, 0.7)
        self.assertEqual(detail.nearest_representative_timestamp_us, 9_000_000)
        self.assertEqual(detail.nearest_representative_distance_us, 1_000_000)

    def test_nsfw_nsfl_or_policy_and_threshold_equality(self):
        scores = _scores(
            (
                _score_sample(2, nsfw=0.5, nsfl=0.0),
                _score_sample(12, nsfw=0.0, nsfl=0.5),
            )
        )
        ground_truth = _ground_truth(
            (
                GroundTruthInterval(start="00:00:01", end="00:00:03"),
                GroundTruthInterval(start="00:00:11", end="00:00:13"),
            )
        )

        nsfw_only = evaluate_thresholds(
            scores,
            ground_truth,
            _config(nsfw=(0.5,), nsfl=(1.0,)),
        ).policies[0]
        nsfl_only = evaluate_thresholds(
            scores,
            ground_truth,
            _config(nsfw=(1.0,), nsfl=(0.5,)),
        ).policies[0]
        either = evaluate_thresholds(
            scores,
            ground_truth,
            _config(nsfw=(0.5,), nsfl=(0.5,)),
        ).policies[0]

        self.assertEqual(nsfw_only.detected_intervals, 1)
        self.assertEqual(nsfl_only.detected_intervals, 1)
        self.assertEqual(either.detected_intervals, 2)
        self.assertEqual(either.candidate_samples, 2)

    def test_no_candidates_all_candidates_rate_and_frame_precision(self):
        scores = _scores(
            (
                _score_sample(5, nsfw=0.2),
                _score_sample(20, nsfw=0.2),
            )
        )
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:04", end="00:00:06"),)
        )

        none = evaluate_thresholds(
            scores,
            ground_truth,
            _config(nsfw=(1.0,), nsfl=(1.0,)),
        ).policies[0]
        all_candidates = evaluate_thresholds(
            scores,
            ground_truth,
            _config(nsfw=(0.0,), nsfl=(0.0,)),
        ).policies[0]

        self.assertEqual(none.candidate_samples, 0)
        self.assertEqual(none.candidate_sample_rate, 0.0)
        self.assertIsNone(none.frame_candidate_precision)
        self.assertEqual(all_candidates.candidate_samples, 2)
        self.assertEqual(all_candidates.candidate_sample_rate, 1.0)
        self.assertEqual(all_candidates.candidate_samples_inside_gt, 1)
        self.assertEqual(all_candidates.candidate_samples_outside_gt, 1)
        self.assertEqual(all_candidates.frame_candidate_precision, 0.5)

    def test_overlaps_remain_distinct_and_category_severity_recall_is_aggregated(self):
        scores = _scores(
            (
                _score_sample(12, nsfw=0.8),
                _score_sample(25, nsfw=0.1),
            )
        )
        ground_truth = _ground_truth(
            (
                GroundTruthInterval(
                    start="00:00:05",
                    end="00:00:15",
                    category="nudity",
                    severity="high",
                ),
                GroundTruthInterval(
                    start="00:00:10",
                    end="00:00:20",
                    category="violence",
                    severity="high",
                ),
                GroundTruthInterval(
                    start="00:00:24",
                    end="00:00:26",
                    category="violence",
                    severity="low",
                ),
            )
        )

        report = evaluate_thresholds(scores, ground_truth, _config())
        result = report.policies[0]

        self.assertEqual(result.detected_intervals, 2)
        self.assertEqual(result.candidate_samples_inside_gt, 1)
        self.assertEqual(report.ground_truth.overlapping_interval_pairs, 1)
        categories = {item.value: item for item in result.category_recall}
        severities = {item.value: item for item in result.severity_recall}
        self.assertEqual(categories["nudity"].interval_recall, 1.0)
        self.assertEqual(categories["violence"].interval_recall, 0.5)
        self.assertEqual(severities["high"].interval_recall, 1.0)
        self.assertEqual(severities["low"].interval_recall, 0.0)

    def test_estimated_windows_apply_context_merge_gap_and_movie_fraction(self):
        scores = _scores(
            (
                _score_sample(2, nsfw=0.8),
                _score_sample(8, nsfw=0.8),
                _score_sample(25, nsfw=0.8),
            )
        )
        result = evaluate_thresholds(
            scores,
            _ground_truth(()),
            _config(context=5.0, merge_gap=2.0),
        ).policies[0]
        workload = result.estimated_vlm_workload

        self.assertEqual(workload.raw_candidate_samples, 3)
        self.assertEqual(workload.merged_candidate_windows, 2)
        self.assertEqual(workload.total_candidate_window_seconds, 23.0)
        self.assertAlmostEqual(workload.movie_fraction, 23 / 30)
        self.assertEqual(workload.average_window_seconds, 11.5)
        self.assertEqual(workload.maximum_window_seconds, 13.0)
        self.assertIsNone(result.interval_recall)
        self.assertIsNone(result.candidate_samples_inside_gt)
        self.assertIsNone(result.candidate_samples_outside_gt)
        self.assertIsNone(result.frame_candidate_precision)

    def test_threshold_cartesian_product_filter_and_sort_are_deterministic(self):
        scores = _scores(
            (
                _score_sample(5, nsfw=0.8, nsfl=0.1),
                _score_sample(20, nsfw=0.4, nsfl=0.4),
            )
        )
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:04", end="00:00:06"),)
        )
        configuration = _config(
            nsfw=(0.3, 0.7),
            nsfl=(0.2, 0.6),
            minimum_recall=1.0,
        )

        first = evaluate_thresholds(scores, ground_truth, configuration)
        second = evaluate_thresholds(scores, ground_truth, configuration)

        self.assertEqual(len(first.policies), 4)
        self.assertEqual(
            [
                (item.policy.nsfw_threshold, item.policy.nsfl_threshold)
                for item in first.policies
            ],
            [(0.3, 0.2), (0.3, 0.6), (0.7, 0.2), (0.7, 0.6)],
        )
        self.assertTrue(
            all(item.interval_recall >= 1.0 for item in first.high_recall_policies)
        )
        self.assertEqual(first.high_recall_policies, second.high_recall_policies)
        sort_keys = [
            (
                -item.interval_recall,
                item.estimated_vlm_movie_fraction,
                item.candidate_sample_rate,
                item.nsfw_threshold,
                item.nsfl_threshold,
            )
            for item in first.high_recall_policies
        ]
        self.assertEqual(sort_keys, sorted(sort_keys))


class Stage1ScoreExportAndIsolationTests(unittest.TestCase):
    def test_score_generation_preserves_metadata_and_persists_no_pixels(self):
        frame = ExtractedFrame(
            timestamp_us=1_000_000,
            source_pts=10,
            source_time_base="1/10",
            processing_chunk_index=0,
            sample_reasons=frozenset(
                {SampleReason.TEMPORAL_SAFETY, SampleReason.SCENE_TRANSITION}
            ),
            width=4,
            height=4,
            content_rect=(0, 0, 4, 4),
            scene_score=0.9,
            rgb_bytes=Image.new("RGB", (4, 4), "red").tobytes(),
        )
        sample = FrameSample(
            timestamp_us=frame.timestamp_us,
            source_pts=frame.source_pts,
            source_time_base=frame.source_time_base,
            owning_chunk_index=0,
            sample_reasons=frame.sample_reasons,
            width=4,
            height=4,
            content_rect=(0, 0, 4, 4),
            disposition=FrameDisposition.REPRESENTATIVE,
        )

        class Resolver:
            local_only = None

            def resolve(self, *, local_files_only=False):
                self.local_only = local_files_only
                return ResolvedSafetyModelArtifact(Path("model.onnx"), MODEL_SHA256)

        class Runtime:
            def run(self, _names, feed):
                batch_size = feed["image"].shape[0]
                return [np.tile(np.array([[0.1, 0.8, 0.1]], np.float32), (batch_size, 1))]

        class SessionFactory:
            def create(self, _artifact):
                return SafetyONNXSession(
                    session=Runtime(),
                    onnxruntime_version="test",
                    execution_providers=(CPU_EXECUTION_PROVIDER,),
                )

        class Preprocessor:
            def preprocess(self, _path, *, config, cancellation, representative_callback):
                representative_callback(frame, sample, cancellation)
                representative_callback.flush(cancellation)
                return SimpleNamespace(
                    representative_frames=(sample,),
                    statistics=SimpleNamespace(movie_duration_us=2_000_000),
                    config=config,
                )

        resolver = Resolver()
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "movie.mp4"
            video.write_bytes(b"movie")
            artifact, output = export_stage1_scores(
                video,
                Path(directory) / "scores.json",
                batch_size=4,
                local_files_only=True,
                artifact_resolver=resolver,
                session_factory=SessionFactory(),
                preprocessing_service=Preprocessor(),
                fingerprint_service=SimpleNamespace(
                    fingerprint=lambda *_args: f"sha256:{'c' * 64}"
                ),
            )
            serialized = output.read_text(encoding="utf-8")

        self.assertTrue(resolver.local_only)
        self.assertEqual(len(artifact.samples), 1)
        self.assertAlmostEqual(artifact.samples[0].nsfw, 0.8)
        self.assertEqual(
            artifact.samples[0].sample_reasons,
            ("scene_transition", "temporal_safety"),
        )
        self.assertNotIn("rgb_bytes", serialized)
        self.assertNotIn("tensor", serialized)

    def test_threshold_changes_do_not_access_preprocessing_inference_movie_or_onnx(self):
        scores = _scores((_score_sample(5, nsfw=0.6),))
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:04", end="00:00:06"),)
        )

        with (
            patch(
                "services.analysis.preprocessing.MoviePreprocessingService.preprocess",
                side_effect=AssertionError("preprocessing must not run"),
            ),
            patch(
                "services.analysis.stage1_safety.Stage1SafetyClassifier.classify",
                side_effect=AssertionError("inference must not run"),
            ),
            patch.object(Path, "is_file", side_effect=AssertionError("movie access")),
        ):
            low = evaluate_thresholds(scores, ground_truth, _config(nsfw=(0.5,)))
            high = evaluate_thresholds(scores, ground_truth, _config(nsfw=(0.7,)))

        self.assertEqual(low.policies[0].candidate_samples, 1)
        self.assertEqual(high.policies[0].candidate_samples, 0)

    def test_evaluation_cli_uses_only_json_artifacts(self):
        scores = _scores((_score_sample(5, nsfw=0.8),))
        ground_truth = _ground_truth(
            (GroundTruthInterval(start="00:00:04", end="00:00:06"),)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            score_path = write_json_artifact(scores, root / "scores.json")
            gt_path = write_json_artifact(ground_truth, root / "gt.json")
            output_path = root / "report.json"
            return_code = evaluate_cli_main(
                [
                    "--scores",
                    str(score_path),
                    "--ground-truth",
                    str(gt_path),
                    "--threshold-start",
                    "0.5",
                    "--threshold-stop",
                    "0.7",
                    "--threshold-step",
                    "0.2",
                    "--json-output",
                    str(output_path),
                ]
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(return_code, 0)
        self.assertEqual(len(payload["policies"]), 4)


if __name__ == "__main__":
    unittest.main()
