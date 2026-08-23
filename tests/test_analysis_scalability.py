import tempfile
import unittest
from pathlib import Path

from services.analysis.cache import AnalysisCache
from services.analysis.contracts import (
    AnalysisMode,
    AnalysisProgressEvent,
    AnalysisRunRequest,
    AnalysisSettings,
    AnalysisStage,
    AnalysisStatus,
    MediaSummary,
    PrefilterFrameScore,
    PreflightResult,
    ProviderDiagnostics,
    SampledFrame,
    TextEvidenceOutput,
    VisualBatch,
    VLMReviewResponse,
)
from services.analysis.pipeline import (
    AnalysisPipeline,
    AnalysisServices,
    _invoke_fixed_sequence,
)

_FINGERPRINT = f"sha256:{'b' * 64}"


class _FixedSequencePipeline(AnalysisPipeline):
    def _invoke_graph(self, state):
        return _invoke_fixed_sequence(state, self.services)


class _NoopTracer:
    def start_node(self, _node_name, _metadata):
        return None

    def finish_node(self, _run_id, _metadata, error=None):
        return None


class _ConfigurablePreflight:
    def __init__(self, cache: AnalysisCache, duration_seconds: float) -> None:
        self.cache = cache
        self.duration_seconds = duration_seconds

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
        if progress_callback is not None:
            progress_callback(100, "Synthetic preflight complete")
        return Path(video_path).resolve(), PreflightResult(
            video_fingerprint=_FINGERPRINT,
            media=MediaSummary(
                duration_seconds=self.duration_seconds,
                fps=24.0,
                format_name="synthetic",
                streams=[{"codec_type": "video", "codec_name": "synthetic"}],
            ),
            cache_key=self.cache.make_key(_FINGERPRINT, settings),
        )


class _NoTextEvidence:
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


class _StaticPrefilter:
    warnings = ()

    def __init__(self, probability_by_timestamp=None, default_probability=0.01):
        self.probability_by_timestamp = probability_by_timestamp or {}
        self.default_probability = default_probability
        self.scored_frame_count = 0
        self.release_count = 0

    def check_ready(self, _settings, cancellation):
        cancellation.raise_if_cancelled()

    def score_frames(
        self,
        frames,
        _settings,
        cancellation,
        progress_callback=None,
    ):
        cancellation.raise_if_cancelled()
        self.scored_frame_count += len(frames)
        scores = [
            PrefilterFrameScore(
                frame=frame,
                nsfw_probability=self.probability_by_timestamp.get(
                    frame.timestamp_seconds,
                    self.default_probability,
                ),
            )
            for frame in frames
        ]
        if progress_callback is not None:
            progress_callback(100, "Synthetic prefilter complete")
        return scores

    def release(self):
        self.release_count += 1


class _RecordingProvider:
    warnings = ()

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []
        self.diagnostics = ProviderDiagnostics(
            device_mode="hybrid",
            device_name="Synthetic RTX",
            precision="float16",
            quantization="4-bit",
            gpu_layer_count=20,
            cpu_layer_count=1,
        )

    def check_ready(self, _settings, cancellation):
        cancellation.raise_if_cancelled()

    def review_batch(self, batch, _settings, cancellation):
        cancellation.raise_if_cancelled()
        self.calls.append(batch.batch_id)
        outcome = self.outcomes.get(batch.batch_id, "complete")
        if outcome == "fail":
            raise RuntimeError("synthetic later-batch failure")
        if outcome == "cancel":
            cancellation.cancel()
            cancellation.raise_if_cancelled()
        return VLMReviewResponse(suggestions=[])


class _LegacyBatchedSampling:
    """Exercises the compatibility seam where candidate filtering selects batches."""

    def __init__(self, frames, batches):
        self.frames = frames
        self.batches = batches

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
        return list(self.frames), list(self.batches)


class _SyntheticCoarseSampling:
    def __init__(self):
        self.generated_count = 0
        self.refine_calls = 0

    def sample_coarse(
        self,
        _video_path,
        _workspace,
        duration_seconds,
        settings,
        cancellation,
        progress_callback=None,
    ):
        cancellation.raise_if_cancelled()
        sample_rate = settings.resolved_coarse_sample_rate_fps
        self.generated_count = int(duration_seconds * sample_rate)
        frames = [
            SampledFrame(
                timestamp_seconds=index / sample_rate,
                path=Path(f"synthetic-coarse-{index:05d}.jpg"),
                source="interval",
            )
            for index in range(self.generated_count)
        ]
        if progress_callback is not None:
            progress_callback(100, "Synthetic coarse sampling complete")
        return frames

    def refine_candidates(self, *_args, **_kwargs):
        self.refine_calls += 1
        raise AssertionError("safe coarse frames must never trigger dense sampling")


def _frames_and_batches(timestamps):
    frames = [
        SampledFrame(
            timestamp_seconds=float(timestamp),
            path=Path(f"synthetic-{index}.jpg"),
            source="interval",
        )
        for index, timestamp in enumerate(timestamps)
    ]
    batches = [
        VisualBatch(
            batch_id=f"batch-{index + 1}",
            start_seconds=max(0.0, frame.timestamp_seconds - 0.4),
            end_seconds=frame.timestamp_seconds + 0.4,
            frames=[frame],
        )
        for index, frame in enumerate(frames)
    ]
    return frames, batches


def _services(
    cache,
    *,
    duration_seconds,
    sampling,
    prefilter,
    provider,
):
    return AnalysisServices(
        cache=cache,
        preflight=_ConfigurablePreflight(cache, duration_seconds),
        text_evidence=_NoTextEvidence(),
        visual_sampling=sampling,
        prefilter=prefilter,
        provider=provider,
        tracer=_NoopTracer(),
    )


def _request(root: Path, settings: AnalysisSettings) -> AnalysisRunRequest:
    return AnalysisRunRequest(
        video_path=root / "synthetic-movie.mp4",
        settings=settings,
    )


class ScalableAnalysisPipelineTests(unittest.TestCase):
    def test_all_safe_prefilter_means_zero_qwen_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = AnalysisCache(root / "cache")
            settings = AnalysisSettings(
                use_gpu=False,
                candidate_padding_seconds=1.0,
            )
            frames, batches = _frames_and_batches([2.0, 20.0, 50.0])
            prefilter = _StaticPrefilter(default_probability=0.01)
            provider = _RecordingProvider()
            services = _services(
                cache,
                duration_seconds=60.0,
                sampling=_LegacyBatchedSampling(frames, batches),
                prefilter=prefilter,
                provider=provider,
            )

            record = _FixedSequencePipeline(services).run(
                _request(root, settings),
                job_id="all-safe",
            )

        self.assertEqual(record.status, AnalysisStatus.COMPLETED)
        self.assertEqual(provider.calls, [])
        self.assertEqual(record.candidate_windows, [])
        self.assertEqual(record.metrics["prefilter_frame_count"], 3)
        self.assertEqual(record.metrics["candidate_count"], 0)
        self.assertEqual(record.metrics["total_batches"], 0)
        self.assertEqual(prefilter.release_count, 1)

    def test_only_batches_intersecting_a_candidate_window_are_reviewed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = AnalysisCache(root / "cache")
            settings = AnalysisSettings(
                use_gpu=False,
                candidate_padding_seconds=1.0,
            )
            frames, batches = _frames_and_batches([2.0, 20.0, 50.0])
            prefilter = _StaticPrefilter(
                probability_by_timestamp={20.0: 0.95},
                default_probability=0.01,
            )
            provider = _RecordingProvider()
            services = _services(
                cache,
                duration_seconds=60.0,
                sampling=_LegacyBatchedSampling(frames, batches),
                prefilter=prefilter,
                provider=provider,
            )

            record = _FixedSequencePipeline(services).run(
                _request(root, settings),
                job_id="candidate-only",
            )

        self.assertEqual(record.status, AnalysisStatus.COMPLETED)
        self.assertEqual(provider.calls, ["batch-2"])
        self.assertEqual(len(record.candidate_windows), 1)
        self.assertEqual(record.metrics["candidate_count"], 1)
        self.assertEqual(record.metrics["total_batches"], 1)
        self.assertEqual(record.metrics["completed_batches"], 1)

    def test_completed_batch_resumes_after_later_failure_or_cancellation(self):
        for terminal_outcome, expected_status in (
            ("fail", AnalysisStatus.PARTIAL),
            ("cancel", AnalysisStatus.CANCELLED),
        ):
            with self.subTest(terminal_outcome=terminal_outcome):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    cache = AnalysisCache(root / "cache")
                    settings = AnalysisSettings(
                        use_gpu=False,
                        candidate_padding_seconds=1.0,
                    )
                    frames, batches = _frames_and_batches([2.0, 20.0])
                    sampling = _LegacyBatchedSampling(frames, batches)
                    prefilter = _StaticPrefilter(default_probability=0.95)
                    first_provider = _RecordingProvider(
                        outcomes={"batch-2": terminal_outcome}
                    )
                    first_services = _services(
                        cache,
                        duration_seconds=30.0,
                        sampling=sampling,
                        prefilter=prefilter,
                        provider=first_provider,
                    )

                    first_record = _FixedSequencePipeline(first_services).run(
                        _request(root, settings),
                        job_id=f"first-{terminal_outcome}",
                    )

                    second_provider = _RecordingProvider()
                    second_prefilter = _StaticPrefilter(default_probability=0.95)
                    second_services = _services(
                        cache,
                        duration_seconds=30.0,
                        sampling=sampling,
                        prefilter=second_prefilter,
                        provider=second_provider,
                    )
                    progress_events: list[AnalysisProgressEvent] = []
                    second_record = _FixedSequencePipeline(second_services).run(
                        _request(root, settings),
                        event_callback=progress_events.append,
                        job_id=f"resumed-{terminal_outcome}",
                    )

                    checkpoints = cache.load_batch_checkpoints(
                        cache.make_key(_FINGERPRINT, settings)
                    )

                self.assertEqual(first_record.status, expected_status)
                self.assertEqual(first_provider.calls, ["batch-1", "batch-2"])
                self.assertEqual(second_record.status, AnalysisStatus.COMPLETED)
                self.assertEqual(second_provider.calls, ["batch-2"])
                self.assertEqual(second_record.metrics["resumed_batches"], 1)
                self.assertEqual(second_record.metrics["prefilter_cache_hits"], 1)
                self.assertEqual(second_prefilter.scored_frame_count, 0)
                self.assertEqual(second_record.metrics["completed_batches"], 2)
                self.assertEqual(len(checkpoints), 2)

                resume_events = [
                    event
                    for event in progress_events
                    if event.stage == AnalysisStage.VLM_REVIEW
                    and event.resumed_units == 1
                    and event.total_units == 2
                ]
                self.assertTrue(resume_events)
                self.assertTrue(all(event.candidate_count == 2 for event in resume_events))
                self.assertTrue(all(event.cache_hits == 1 for event in resume_events))
                self.assertTrue(
                    all(
                        event.device == "GPU + CPU offload 4-bit"
                        for event in resume_events
                    )
                )
                self.assertTrue(
                    all(event.completed_units <= event.total_units for event in resume_events)
                )

    def test_synthetic_two_hour_safe_movie_plans_sparse_work_without_vlm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = AnalysisCache(root / "cache")
            duration_seconds = 2 * 60 * 60
            settings = AnalysisSettings(
                analysis_mode=AnalysisMode.BALANCED,
                use_gpu=False,
            )
            sampling = _SyntheticCoarseSampling()
            prefilter = _StaticPrefilter(default_probability=0.01)
            provider = _RecordingProvider()
            services = _services(
                cache,
                duration_seconds=duration_seconds,
                sampling=sampling,
                prefilter=prefilter,
                provider=provider,
            )
            progress_events: list[AnalysisProgressEvent] = []

            record = _FixedSequencePipeline(services).run(
                _request(root, settings),
                event_callback=progress_events.append,
                job_id="synthetic-two-hour",
            )

        expected_coarse_count = int(
            duration_seconds * settings.resolved_coarse_sample_rate_fps
        )
        self.assertEqual(expected_coarse_count, 1440)
        self.assertEqual(sampling.generated_count, expected_coarse_count)
        self.assertLess(expected_coarse_count, duration_seconds)
        self.assertEqual(record.status, AnalysisStatus.COMPLETED)
        self.assertEqual(record.metrics["coarse_frame_count"], expected_coarse_count)
        self.assertEqual(record.metrics["prefilter_frame_count"], expected_coarse_count)
        self.assertEqual(record.metrics["candidate_count"], 0)
        self.assertEqual(record.metrics["total_batches"], 0)
        self.assertEqual(provider.calls, [])
        self.assertEqual(sampling.refine_calls, 0)
        overall_progress = [event.overall_percent for event in progress_events]
        self.assertTrue(overall_progress)
        self.assertEqual(overall_progress, sorted(overall_progress))
        self.assertEqual(overall_progress[-1], 100)


if __name__ == "__main__":
    unittest.main()
