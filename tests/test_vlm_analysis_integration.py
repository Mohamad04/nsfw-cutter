import subprocess
import tempfile
import unittest
from pathlib import Path

from services.analysis.cache import AnalysisCache
from services.analysis.contracts import (
    AnalysisRunRequest,
    AnalysisSettings,
    AnalysisStatus,
    PrefilterFrameScore,
    TextEvidenceOutput,
    VLMReviewResponse,
)
from services.analysis.pipeline import AnalysisPipeline, AnalysisServices
from services.analysis.preflight import PreflightService
from services.analysis.visual_sampling import VisualSamplingService
from services.infrastructure.ffmpeg.paths import (
    FFmpegNotFoundError,
    get_ffmpeg_path,
    get_ffprobe_path,
)
from services.infrastructure.ffmpeg.runner import FFmpegService


class _NoTextEvidence:
    def gather(self, *args, **kwargs):
        return TextEvidenceOutput()


class _MockVLMProvider:
    model_id = "mock-local-vlm"

    def __init__(self):
        self.calls = 0
        self.warnings = []

    def review_batch(self, batch, settings, cancellation):
        self.calls += 1
        if batch.contact_sheet_path is None or not batch.contact_sheet_path.is_file():
            raise AssertionError("candidate review must use a generated contact sheet")
        start = batch.frames[0].timestamp_seconds
        evidence_timestamp = batch.frames[min(1, len(batch.frames) - 1)].timestamp_seconds
        end = max(start + 0.1, batch.frames[-1].timestamp_seconds)
        return VLMReviewResponse.model_validate(
            {
                "suggestions": [
                    {
                        "category": "nudity",
                        "confidence": 0.9,
                        "start_seconds": float(start),
                        "end_seconds": float(end),
                        "evidence_timestamps": [float(evidence_timestamp)],
                        "reason": "Mocked visual evidence for deterministic testing.",
                        "needs_review": True,
                    }
                ]
            }
        )


class _MockPrefilter:
    warnings = ()

    def __init__(self):
        self.calls = 0
        self.release_calls = 0

    def check_ready(self, _settings, cancellation):
        cancellation.raise_if_cancelled()

    def score_frames(self, frames, _settings, cancellation, progress_callback=None):
        cancellation.raise_if_cancelled()
        self.calls += 1
        if progress_callback is not None:
            progress_callback(100, "Mock prefilter complete")
        return [
            PrefilterFrameScore(frame=frame, nsfw_probability=0.95)
            for frame in frames
        ]

    def release(self):
        self.release_calls += 1


class VLMAnalysisIntegrationTests(unittest.TestCase):
    def test_generated_video_runs_with_mocked_model_and_reuses_cache(self):
        try:
            ffmpeg_path = get_ffmpeg_path()
            ffprobe_path = get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            self.skipTest(str(exc))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video_path = root / "generated.mp4"
            completed = subprocess.run(
                [
                    str(ffmpeg_path),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=duration=2.5:size=160x90:rate=5",
                    "-c:v",
                    "mpeg4",
                    "-pix_fmt",
                    "yuv420p",
                    "-y",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                self.fail(completed.stderr)

            cache = AnalysisCache(root / "analysis-cache")
            provider = _MockVLMProvider()
            prefilter = _MockPrefilter()
            ffmpeg_service = FFmpegService(ffmpeg_path, ffprobe_path)
            services = AnalysisServices(
                cache=cache,
                preflight=PreflightService(cache=cache),
                text_evidence=_NoTextEvidence(),
                visual_sampling=VisualSamplingService(ffmpeg_service=ffmpeg_service),
                prefilter=prefilter,
                provider=provider,
            )
            pipeline = AnalysisPipeline(services)
            request = AnalysisRunRequest(
                video_path=video_path,
                settings=AnalysisSettings(
                    model_id="mock-local-vlm",
                    use_gpu=False,
                    sample_rate_fps=1.0,
                    scene_threshold=0.95,
                    batch_size=8,
                ),
            )

            first = pipeline.run(request, job_id="integration-first")
            second = pipeline.run(request, job_id="integration-second")

            self.assertEqual(first.status, AnalysisStatus.COMPLETED)
            self.assertEqual(len(first.suggestions), 1)
            self.assertEqual(first.suggestions[0].category, "nudity")
            self.assertTrue(first.suggestions[0].needs_review)
            self.assertEqual(second.video_fingerprint, first.video_fingerprint)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(prefilter.calls, 1)
            self.assertEqual(prefilter.release_calls, 1)
            self.assertNotIn(str(video_path.resolve()), first.model_dump_json())
            self.assertEqual(list(cache.work_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
