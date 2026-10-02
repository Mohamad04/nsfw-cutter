import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from services.analysis.cache import (
    AnalysisBatchCheckpoint,
    AnalysisCache,
    BatchCheckpointStatus,
    PrefilterCheckpoint,
    PrefilterScoreItem,
)
from services.analysis.contracts import (
    AnalysisRecord,
    AnalysisSettings,
    AnalysisStatus,
    MediaSummary,
    SampledFrame,
    VisualBatch,
    VLMReviewResponse,
)


class AnalysisBatchKeyTests(unittest.TestCase):
    def test_key_is_stable_and_covers_visual_prompt_and_model_inputs(self):
        cache_key = "a" * 64
        settings = AnalysisSettings(use_gpu=False, max_new_tokens=128)
        batch = self._batch(
            "display-id",
            10.0,
            20.0,
            [(11.25, "first.jpg"), (18.75, "second.jpg")],
        )
        first = AnalysisCache.make_batch_key(
            cache_key,
            batch,
            settings,
            prompt_schema_version="qwen-json-v1",
        )
        relocated = self._batch(
            "renumbered-id",
            10.0,
            20.0,
            [(11.25, "relocated-a.jpg"), (18.75, "relocated-b.jpg")],
        )
        second = AnalysisCache.make_batch_key(
            cache_key.upper(),
            relocated,
            settings,
            prompt_schema_version=" qwen-json-v1 ",
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        changed_inputs = [
            AnalysisCache.make_batch_key(
                "b" * 64,
                batch,
                settings,
                prompt_schema_version="qwen-json-v1",
            ),
            AnalysisCache.make_batch_key(
                cache_key,
                self._batch(
                    "display-id",
                    9.5,
                    20.0,
                    [(11.25, "first.jpg"), (18.75, "second.jpg")],
                ),
                settings,
                prompt_schema_version="qwen-json-v1",
            ),
            AnalysisCache.make_batch_key(
                cache_key,
                self._batch(
                    "display-id",
                    10.0,
                    20.0,
                    [(11.5, "first.jpg"), (18.75, "second.jpg")],
                ),
                settings,
                prompt_schema_version="qwen-json-v1",
            ),
            AnalysisCache.make_batch_key(
                cache_key,
                batch,
                settings,
                prompt_schema_version="qwen-json-v2",
            ),
            AnalysisCache.make_batch_key(
                cache_key,
                batch,
                settings.model_copy(update={"max_new_tokens": 129}),
                prompt_schema_version="qwen-json-v1",
            ),
            AnalysisCache.make_batch_key(
                cache_key,
                batch,
                settings.model_copy(update={"model_revision": "revision-2"}),
                prompt_schema_version="qwen-json-v1",
            ),
        ]
        self.assertTrue(all(candidate != first for candidate in changed_inputs))

    @staticmethod
    def _batch(
        batch_id: str,
        start_seconds: float,
        end_seconds: float,
        frame_values: list[tuple[float, str]],
    ) -> VisualBatch:
        return VisualBatch(
            batch_id=batch_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            frames=[
                SampledFrame(
                    timestamp_seconds=timestamp,
                    path=Path(path),
                    source="interval",
                )
                for timestamp, path in frame_values
            ],
        )


class PrefilterCheckpointTests(unittest.TestCase):
    def test_scores_round_trip_without_frame_paths_and_key_tracks_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=True)
            frames = [
                SampledFrame(
                    timestamp_seconds=value,
                    path=Path(f"private-{index}.jpg"),
                    source="interval",
                )
                for index, value in enumerate((0.0, 5.0, 10.0))
            ]
            key = cache.make_prefilter_key("a" * 64, frames, settings)
            checkpoint = PrefilterCheckpoint(
                analysis_cache_key="a" * 64,
                score_key=key,
                model_id=settings.prefilter_model_id,
                model_revision=settings.prefilter_model_revision,
                scores=[
                    PrefilterScoreItem(
                        timestamp_seconds=frame.timestamp_seconds,
                        nsfw_probability=0.1 * (index + 1),
                    )
                    for index, frame in enumerate(frames)
                ],
            )

            path = cache.save_prefilter_checkpoint(checkpoint)
            loaded = cache.load_prefilter_checkpoint("a" * 64, key)

            self.assertEqual(loaded, checkpoint)
            self.assertNotIn("private-", path.read_text(encoding="utf-8"))
            self.assertNotEqual(
                key,
                cache.make_prefilter_key(
                    "a" * 64,
                    frames[1:],
                    settings,
                ),
            )

    def test_corrupt_prefilter_checkpoint_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            frames = [
                SampledFrame(
                    timestamp_seconds=1.0,
                    path=Path("one.jpg"),
                    source="scene",
                )
            ]
            key = cache.make_prefilter_key("a" * 64, frames, settings)
            path = cache.prefilter_checkpoint_path("a" * 64, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{invalid", encoding="utf-8")

            self.assertIsNone(cache.load_prefilter_checkpoint("a" * 64, key))


class AnalysisBatchCheckpointTests(unittest.TestCase):
    def test_completed_and_failed_checkpoints_round_trip_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            completed = self._checkpoint(
                analysis_cache_key="a" * 64,
                batch_key="1" * 64,
                status=BatchCheckpointStatus.COMPLETED,
                response=VLMReviewResponse(suggestions=[]),
                raw_output="  {malformed:true}  ",
                repaired_output='{"suggestions":[]}',
                repaired=True,
                stop_reason="eos_token",
                inference_seconds=3.25,
            )
            failed = self._checkpoint(
                analysis_cache_key="a" * 64,
                batch_key="2" * 64,
                status=BatchCheckpointStatus.FAILED,
                error="Schema validation failed",
                raw_output="{truncated",
                repaired_output="{still-invalid",
                stop_reason="max_new_tokens",
                attempt_count=2,
            )

            completed_path = cache.save_batch_checkpoint(completed)
            failed_path = cache.save_batch_checkpoint(failed)

            self.assertEqual(
                cache.load_batch_checkpoint(completed.analysis_cache_key, completed.batch_key),
                completed,
            )
            self.assertEqual(
                cache.load_batch_checkpoint(failed.analysis_cache_key, failed.batch_key),
                failed,
            )
            self.assertTrue(completed_path.is_file())
            self.assertTrue(failed_path.is_file())
            self.assertEqual(list(completed_path.parent.glob("*.tmp")), [])
            self.assertEqual(
                cache.load_batch_checkpoint(
                    completed.analysis_cache_key,
                    completed.batch_key,
                ).raw_output,
                "  {malformed:true}  ",
            )

    def test_invalid_terminal_shapes_are_rejected(self):
        common = {
            "analysis_cache_key": "a" * 64,
            "batch_key": "1" * 64,
            "batch_id": "batch-1",
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "frame_timestamps": [1.5],
            "prompt_schema_version": "qwen-json-v1",
            "model_id": "test/model",
            "model_revision": "revision",
        }
        with self.assertRaises(ValidationError):
            AnalysisBatchCheckpoint(
                **common,
                status=BatchCheckpointStatus.COMPLETED,
            )
        with self.assertRaises(ValidationError):
            AnalysisBatchCheckpoint(
                **common,
                status=BatchCheckpointStatus.FAILED,
            )

    def test_captured_outputs_are_bounded(self):
        common = {
            "analysis_cache_key": "a" * 64,
            "batch_key": "1" * 64,
            "batch_id": "batch-1",
            "start_seconds": 1.0,
            "end_seconds": 2.0,
            "frame_timestamps": [1.5],
            "prompt_schema_version": "qwen-json-v1",
            "model_id": "test/model",
            "model_revision": "revision",
            "status": BatchCheckpointStatus.FAILED,
            "error": "Invalid response",
        }
        maximum = "x" * (16 * 1024)
        checkpoint = AnalysisBatchCheckpoint(
            **common,
            raw_output=maximum,
            repaired_output=maximum,
            repaired=False,
            stop_reason="length",
        )
        self.assertEqual(checkpoint.raw_output, maximum)
        self.assertEqual(checkpoint.repaired_output, maximum)

        with self.assertRaises(ValidationError):
            AnalysisBatchCheckpoint(**common, raw_output=maximum + "x")
        with self.assertRaises(ValidationError):
            AnalysisBatchCheckpoint(**common, repaired_output=maximum + "x")

    def test_corrupt_checkpoint_is_isolated_from_other_batches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            corrupt = self._checkpoint(
                analysis_cache_key="a" * 64,
                batch_key="1" * 64,
                status=BatchCheckpointStatus.COMPLETED,
                response=VLMReviewResponse(suggestions=[]),
            )
            valid = self._checkpoint(
                analysis_cache_key="a" * 64,
                batch_key="2" * 64,
                status=BatchCheckpointStatus.FAILED,
                error="Timed out",
            )
            corrupt_path = cache.save_batch_checkpoint(corrupt)
            cache.save_batch_checkpoint(valid)
            corrupt_path.write_text("{not valid json", encoding="utf-8")
            (corrupt_path.parent / "not-a-digest.json").write_text(
                "{}",
                encoding="utf-8",
            )

            loaded = cache.load_batch_checkpoints("a" * 64)

            self.assertIsNone(cache.load_batch_checkpoint("a" * 64, "1" * 64))
            self.assertEqual(set(loaded), {"2" * 64})
            self.assertEqual(loaded["2" * 64], valid)

    @staticmethod
    def _checkpoint(
        *,
        analysis_cache_key: str,
        batch_key: str,
        status: BatchCheckpointStatus,
        response: VLMReviewResponse | None = None,
        error: str | None = None,
        raw_output: str | None = None,
        repaired_output: str | None = None,
        repaired: bool = False,
        stop_reason: str | None = None,
        attempt_count: int = 1,
        inference_seconds: float | None = None,
    ) -> AnalysisBatchCheckpoint:
        return AnalysisBatchCheckpoint(
            analysis_cache_key=analysis_cache_key,
            batch_key=batch_key,
            batch_id=f"batch-{batch_key[0]}",
            start_seconds=1.0,
            end_seconds=2.0,
            frame_timestamps=[1.25, 1.75],
            prompt_schema_version="qwen-json-v1",
            model_id="test/model",
            model_revision="revision",
            status=status,
            response=response,
            error=error,
            raw_output=raw_output,
            repaired_output=repaired_output,
            repaired=repaired,
            stop_reason=stop_reason,
            attempt_count=attempt_count,
            inference_seconds=inference_seconds,
        )


class CompletedRecordProtectionTests(unittest.TestCase):
    def test_incomplete_attempts_do_not_replace_existing_completed_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            key = cache.make_key("sha256:video", settings)
            completed = self._record(settings, AnalysisStatus.COMPLETED)
            cache.save(key, completed)

            for status in (
                AnalysisStatus.PARTIAL,
                AnalysisStatus.CANCELLED,
                AnalysisStatus.FAILED,
            ):
                with self.subTest(status=status):
                    cache.save_preserving_completed(key, self._record(settings, status))
                    loaded = cache.load(key, reusable_only=False)
                    self.assertIsNotNone(loaded)
                    self.assertEqual(loaded.status, AnalysisStatus.COMPLETED)
                    self.assertEqual(loaded.completed_at, completed.completed_at)

    def test_safe_save_stores_attempt_when_no_completed_record_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            key = cache.make_key("sha256:video", settings)
            partial = self._record(settings, AnalysisStatus.PARTIAL)

            cache.save_preserving_completed(key, partial)
            loaded_partial = cache.load(key, reusable_only=False)
            self.assertIsNotNone(loaded_partial)
            self.assertEqual(loaded_partial.status, AnalysisStatus.PARTIAL)

            completed = self._record(settings, AnalysisStatus.COMPLETED)
            cache.save_preserving_completed(key, completed)
            loaded_completed = cache.load(key, reusable_only=False)
            self.assertIsNotNone(loaded_completed)
            self.assertEqual(loaded_completed.status, AnalysisStatus.COMPLETED)

    @staticmethod
    def _record(
        settings: AnalysisSettings,
        status: AnalysisStatus,
    ) -> AnalysisRecord:
        now = datetime.now(UTC)
        return AnalysisRecord(
            video_fingerprint="sha256:video",
            model_id=settings.model_id,
            model_revision=settings.model_revision,
            settings_version=settings.settings_version,
            settings=settings.model_dump(mode="json"),
            status=status,
            media=MediaSummary(
                duration_seconds=10.0,
                fps=24.0,
                format_name="mock",
                streams=[{"codec_type": "video"}],
            ),
            started_at=now,
            completed_at=now,
        )


if __name__ == "__main__":
    unittest.main()
