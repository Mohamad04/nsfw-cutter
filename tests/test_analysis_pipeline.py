import tempfile
import unittest
from pathlib import Path

from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisRunRequest,
    AnalysisSettings,
    AnalysisStatus,
    MediaSummary,
    NSFWCategory,
    PreflightResult,
    SampledFrame,
    TextEvidenceOutput,
    VisualBatch,
    VLMReviewItem,
    VLMReviewResponse,
)
from services.analysis.pipeline import (
    AnalysisPipeline,
    AnalysisServices,
    _invoke_fixed_sequence,
)
from services.analysis.providers.base import VLMProviderUnavailableError

_FINGERPRINT = f"sha256:{'a' * 64}"


class _FixedSequencePipeline(AnalysisPipeline):
    """Keep these service tests independent of the optional LangGraph package."""

    def _invoke_graph(self, state):
        return _invoke_fixed_sequence(state, self.services)


class _NoopTracer:
    def start_node(self, _node_name, _metadata):
        return None

    def finish_node(self, _run_id, _metadata, error=None):
        return None


class _FakePreflight:
    def __init__(self, cache):
        self.cache = cache

    def run(
        self,
        video_path,
        settings,
        cancellation,
        progress_callback=None,
        *,
        selected_subtitle=None,
    ):
        cancellation.raise_if_cancelled()
        result = PreflightResult(
            video_fingerprint=_FINGERPRINT,
            media=MediaSummary(
                duration_seconds=8.0,
                fps=24.0,
                format_name="mock",
                streams=[{"codec_type": "video", "codec_name": "mock"}],
            ),
            cache_key=self.cache.make_key(_FINGERPRINT, settings),
        )
        return Path(video_path).resolve(), result


class _CancellingTextEvidence:
    def gather(
        self,
        _video_path,
        _selected_subtitle,
        _workspace,
        _settings,
        cancellation,
        _progress_callback=None,
    ):
        cancellation.cancel()
        cancellation.raise_if_cancelled()


class _EmptyTextEvidence:
    def gather(
        self,
        _video_path,
        _selected_subtitle,
        _workspace,
        _settings,
        cancellation,
        _progress_callback=None,
    ):
        cancellation.raise_if_cancelled()
        return TextEvidenceOutput()


class _UnexpectedTextEvidence:
    def gather(self, *_args, **_kwargs):
        raise AssertionError("text analysis must not run when the visual model is unavailable")


class _UnexpectedSampling:
    def sample(self, *_args, **_kwargs):
        raise AssertionError("visual sampling must not run after cancellation")


class _TwoBatchSampling:
    def sample(
        self,
        _video_path,
        _workspace,
        _duration_seconds,
        _settings,
        cancellation,
        _progress_callback=None,
    ):
        cancellation.raise_if_cancelled()
        frames = [
            SampledFrame(
                timestamp_seconds=1.5,
                path=Path("mock-batch-1.jpg"),
                source="interval",
            ),
            SampledFrame(
                timestamp_seconds=4.5,
                path=Path("mock-batch-2.jpg"),
                source="interval",
            ),
        ]
        batches = [
            VisualBatch(
                batch_id="batch-1",
                start_seconds=1.0,
                end_seconds=2.0,
                frames=[frames[0]],
            ),
            VisualBatch(
                batch_id="batch-2",
                start_seconds=4.0,
                end_seconds=5.0,
                frames=[frames[1]],
            ),
        ]
        return frames, batches


class _UnexpectedProvider:
    def review_batch(self, *_args, **_kwargs):
        raise AssertionError("provider must not run after cancellation")


class _FirstBatchFailsProvider:
    def __init__(self):
        self.calls = []

    def review_batch(self, batch, _settings, cancellation):
        cancellation.raise_if_cancelled()
        self.calls.append(batch.batch_id)
        if batch.batch_id == "batch-1":
            raise RuntimeError(
                r"simulated provider failure at C:\Private Folder\video.mp4 "
                "with sk_abcdefghijklmnop"
            )
        return VLMReviewResponse(
            suggestions=[
                VLMReviewItem(
                    category=NSFWCategory.SEXUAL_CONTEXT,
                    confidence=0.88,
                    start_seconds=4.0,
                    end_seconds=5.0,
                    evidence_timestamps=[4.5],
                    reason="Visual context requiring review",
                    needs_review=True,
                )
            ]
        )


class _UnavailableProvider:
    def __init__(self):
        self.calls = []
        self.warnings = []

    def review_batch(self, batch, _settings, _cancellation):
        self.calls.append(batch.batch_id)
        raise VLMProviderUnavailableError("local model is not installed")


class _PreflightUnavailableProvider:
    def __init__(self):
        self.warnings = []

    def check_ready(self, _settings, cancellation):
        cancellation.raise_if_cancelled()
        raise VLMProviderUnavailableError("local model is not installed")

    def review_batch(self, *_args, **_kwargs):
        raise AssertionError("batch review must not run after a failed readiness check")


class CancellationTokenTests(unittest.TestCase):
    def test_cancel_sets_state_unblocks_waiters_and_raises(self):
        token = CancellationToken()

        self.assertFalse(token.is_cancelled)
        self.assertFalse(token.wait(0.0))
        token.cancel()

        self.assertTrue(token.is_cancelled)
        self.assertTrue(token.wait(0.0))
        with self.assertRaisesRegex(AnalysisCancelled, "cancelled"):
            token.raise_if_cancelled()


class AnalysisPipelineFailureTests(unittest.TestCase):
    def test_cooperative_cancellation_returns_and_persists_cancelled_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            token = CancellationToken()
            progress = []
            services = AnalysisServices(
                cache=cache,
                preflight=_FakePreflight(cache),
                text_evidence=_CancellingTextEvidence(),
                visual_sampling=_UnexpectedSampling(),
                provider=_UnexpectedProvider(),
                tracer=_NoopTracer(),
            )
            request = AnalysisRunRequest(
                video_path=Path(temp_dir) / "mock.mp4",
                settings=settings,
                force_reanalysis=True,
            )

            record = AnalysisPipeline(services).run(
                request,
                cancellation=token,
                progress_callback=lambda percent, message: progress.append(
                    (percent, message)
                ),
                job_id="cancel-job",
            )
            cache_key = cache.make_key(_FINGERPRINT, settings)
            persisted = cache.load(cache_key, reusable_only=False)

            self.assertFalse((cache.work_dir / "cancel-job").exists())

        self.assertEqual(record.status, AnalysisStatus.CANCELLED)
        self.assertEqual(record.video_fingerprint, _FINGERPRINT)
        self.assertTrue(token.is_cancelled)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, AnalysisStatus.CANCELLED)
        self.assertIn((0, "Video analysis cancelled"), progress)

    def test_failed_visual_batch_is_skipped_and_later_batch_yields_partial_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            provider = _FirstBatchFailsProvider()
            settings = AnalysisSettings(use_gpu=False)
            progress = []
            services = AnalysisServices(
                cache=cache,
                preflight=_FakePreflight(cache),
                text_evidence=_EmptyTextEvidence(),
                visual_sampling=_TwoBatchSampling(),
                provider=provider,
                tracer=_NoopTracer(),
            )
            request = AnalysisRunRequest(
                video_path=Path(temp_dir) / "mock.mp4",
                settings=settings,
                force_reanalysis=True,
            )

            record = _FixedSequencePipeline(services).run(
                request,
                progress_callback=lambda percent, message: progress.append(
                    (percent, message)
                ),
                job_id="partial-job",
            )
            persisted = cache.load(
                cache.make_key(_FINGERPRINT, settings),
                reusable_only=False,
            )

        self.assertEqual(provider.calls, ["batch-1", "batch-2"])
        self.assertEqual(record.status, AnalysisStatus.PARTIAL)
        self.assertEqual(len(record.visual_evidence), 1)
        self.assertEqual(record.visual_evidence[0].batch_id, "batch-2")
        self.assertEqual(len(record.suggestions), 1)
        self.assertEqual(
            record.suggestions[0].category,
            NSFWCategory.SEXUAL_CONTEXT,
        )
        self.assertTrue(record.suggestions[0].needs_review)
        self.assertTrue(
            any("Visual batch 1 failed" in error for error in record.errors)
        )
        serialized_record = record.model_dump_json()
        self.assertNotIn("Private Folder", serialized_record)
        self.assertNotIn("abcdefghijklmnop", serialized_record)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, AnalysisStatus.PARTIAL)
        self.assertTrue(
            any(
                percent == 100 and "warnings" in message
                for percent, message in progress
            )
        )

    def test_unavailable_provider_fails_fast_without_retrying_every_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            provider = _UnavailableProvider()
            settings = AnalysisSettings(use_gpu=False)
            services = AnalysisServices(
                cache=cache,
                preflight=_FakePreflight(cache),
                text_evidence=_EmptyTextEvidence(),
                visual_sampling=_TwoBatchSampling(),
                provider=provider,
                tracer=_NoopTracer(),
            )
            request = AnalysisRunRequest(
                video_path=Path(temp_dir) / "mock.mp4",
                settings=settings,
                force_reanalysis=True,
            )

            record = _FixedSequencePipeline(services).run(
                request,
                job_id="unavailable-provider-job",
            )

        self.assertEqual(provider.calls, ["batch-1"])
        self.assertEqual(record.status, AnalysisStatus.PARTIAL)
        self.assertEqual(record.suggestions, [])
        self.assertTrue(
            any("Visual model unavailable" in error for error in record.errors)
        )

    def test_readiness_failure_skips_expensive_text_and_frame_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = AnalysisCache(temp_dir)
            settings = AnalysisSettings(use_gpu=False)
            services = AnalysisServices(
                cache=cache,
                preflight=_FakePreflight(cache),
                text_evidence=_UnexpectedTextEvidence(),
                visual_sampling=_UnexpectedSampling(),
                provider=_PreflightUnavailableProvider(),
                tracer=_NoopTracer(),
            )
            request = AnalysisRunRequest(
                video_path=Path(temp_dir) / "mock.mp4",
                settings=settings,
                force_reanalysis=True,
            )

            record = _FixedSequencePipeline(services).run(
                request,
                job_id="readiness-failure-job",
            )

            self.assertEqual(list(cache.work_dir.iterdir()), [])

        self.assertEqual(record.status, AnalysisStatus.PARTIAL)
        self.assertEqual(record.suggestions, [])
        self.assertTrue(
            any("Visual model unavailable" in error for error in record.errors)
        )


if __name__ == "__main__":
    unittest.main()
