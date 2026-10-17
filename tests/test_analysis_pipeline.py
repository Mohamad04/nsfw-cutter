import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
from services.analysis.text_evidence import TextEvidenceService

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
    def __init__(self, cache, has_audio=False):
        self.cache = cache
        self.has_audio = has_audio

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
                streams=[{"codec_type": "video", "codec_name": "mock"}]
                + ([{"codec_type": "audio", "codec_name": "mock"}] if self.has_audio else []),
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
        *,
        has_audio=True,
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
        *,
        has_audio=True,
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
    def test_text_availability_and_failures_preserve_visual_suggestions(self):
        # Simulate the old unconditional extraction as the reference. Both graph
        # orchestration paths use the real text service, fusion and persistence.
        for pipeline_type in (_FixedSequencePipeline, AnalysisPipeline):
            reference = None
            for scenario in ("before_fix", "silent", "audio", "extraction_failure", "transcription_failure"):
                with self.subTest(pipeline=pipeline_type.__name__, scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                    cache = AnalysisCache(tmp)
                    runner, transcriber = Mock(), Mock()
                    transcriber.transcribe.return_value = ([], [])
                    if scenario in ("before_fix", "extraction_failure"):
                        runner.run.side_effect = RuntimeError("synthetic extraction failure")
                    if scenario == "transcription_failure":
                        transcriber.transcribe.side_effect = RuntimeError("synthetic transcription failure")
                    text = TextEvidenceService(ffmpeg_service=SimpleNamespace(ffmpeg_path="ffmpeg"),
                                               process_runner=runner, transcriber=transcriber)
                    if scenario == "before_fix":
                        gather = text.gather
                        text.gather = lambda *args, **kwargs: gather(*args, has_audio=True)
                    provider = Mock()
                    provider.warnings = []
                    provider.review_batch.return_value = VLMReviewResponse(suggestions=[
                        VLMReviewItem(category=NSFWCategory.NUDITY, confidence=0.9,
                                      start_seconds=4.0, end_seconds=5.0,
                                      evidence_timestamps=[4.5], reason="synthetic visual event",
                                      needs_review=True)])
                    services = AnalysisServices(cache=cache,
                        preflight=_FakePreflight(cache, has_audio=scenario not in ("before_fix", "silent")),
                        text_evidence=text, visual_sampling=_TwoBatchSampling(),
                        provider=provider, tracer=_NoopTracer())
                    record = pipeline_type(services).run(AnalysisRunRequest(
                        video_path=Path(tmp) / "synthetic.mp4", settings=AnalysisSettings(use_gpu=False),
                        force_reanalysis=True))
                    failed = scenario in ("before_fix", "extraction_failure", "transcription_failure")
                    self.assertEqual(record.status, AnalysisStatus.PARTIAL if failed else AnalysisStatus.COMPLETED)
                    self.assertEqual(len(record.errors), 1 if failed else 0)
                    self.assertEqual(record.metrics["completed_batches"], 2)
                    self.assertTrue(record.suggestions)
                    suggestions = [s.model_dump(mode="json") for s in record.suggestions]
                    if reference is None:
                        reference = suggestions
                    self.assertEqual(suggestions, reference)
                    self.assertEqual(record.text_evidence, [])
                    if scenario == "silent":
                        runner.run.assert_not_called()
                        transcriber.transcribe.assert_not_called()
                        self.assertIn("not applicable", record.warnings[0])
                    else:
                        runner.run.assert_called_once()

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
