"""Regression tests: visual coverage of short media and short candidate windows.

FFmpeg's fps filter (default nearest rounding) writes no frame when the sampled span is shorter than
half a sampling period: under 2.5 s for the Balanced coarse rate (0.2 fps) and under 0.5 s for the
1 fps dense rate. The image2 muxer then exits with "Nothing was written into output file", which
used to abort coarse sampling (no visual analysis at all) or the whole candidate refinement.
Synthetic, non-sensitive test patterns only.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from services.analysis.cache import AnalysisCache
from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import (
    AnalysisRunRequest,
    AnalysisSettings,
    AnalysisStatus,
    CandidateWindow,
    PrefilterFrameScore,
    TextEvidenceOutput,
    VLMReviewResponse,
)
from services.analysis.pipeline import AnalysisPipeline, AnalysisServices
from services.analysis.preflight import PreflightService
from services.analysis.process import CancellableProcessRunner
from services.analysis.visual_sampling import VisualSamplingService
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path
from services.infrastructure.ffmpeg.runner import FFmpegService

SHORT_DURATIONS = (0.5, 1.0, 1.5, 2.0, 2.49)
# Periodic frames of the unchanged Balanced coarse pass (0.2 fps, nearest rounding).
LONG_DURATIONS = {2.5: 1, 5.0: 1, 10.0: 2, 30.0: 6}


class RecordingRunner(CancellableProcessRunner):
    def __init__(self):
        super().__init__()
        self.commands = []

    def run(self, command, *, cancellation, check=True):
        self.commands.append([str(part) for part in command])
        return super().run(command, cancellation=cancellation, check=check)


class _SafePrefilter:
    warnings = ()

    def __init__(self, probability):
        self.probability, self.frames = probability, []

    def check_ready(self, _settings, cancellation):
        cancellation.raise_if_cancelled()

    def score_frames(self, frames, _settings, cancellation, progress_callback=None):
        self.frames.extend(frames)
        return [PrefilterFrameScore(frame=frame, nsfw_probability=self.probability) for frame in frames]

    def release(self):
        pass


class _NoText:
    def gather(self, *args, **kwargs):
        return TextEvidenceOutput()


class _Provider:
    model_id = "mock-local-vlm"
    warnings = []

    def __init__(self):
        self.batches = []

    def review_batch(self, batch, settings, cancellation):
        self.batches.append(batch)
        start = batch.frames[0].timestamp_seconds
        return VLMReviewResponse.model_validate({"suggestions": [{
            "category": "nudity", "confidence": 0.9, "start_seconds": float(start),
            "end_seconds": float(max(start + 0.1, batch.frames[-1].timestamp_seconds)),
            "evidence_timestamps": [float(start)], "reason": "Mocked evidence.", "needs_review": True}]})


class ShortMediaSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc))
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.videos = {d: cls.make_video(d) for d in (*SHORT_DURATIONS, *LONG_DURATIONS, 40.0)}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def make_video(cls, duration, name=None):
        path = cls.root / (name or f"clip_{duration:g}.mkv")
        # 100 frames/s makes every tested duration exact (2.49 s is 249 frames, not a rounded 2.5 s).
        subprocess.run([str(cls.ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=160x120:rate=100", "-t", f"{duration}", "-c:v", "libx264", "-pix_fmt",
                        "yuv420p", "-y", str(path)], check=True, capture_output=True)
        return path

    def service(self):
        runner = RecordingRunner()
        return VisualSamplingService(ffmpeg_service=FFmpegService(self.ffmpeg, self.ffprobe),
                                     process_runner=runner), runner

    def coarse(self, duration, workspace_name):
        service, runner = self.service()
        workspace = self.root / workspace_name
        frames = service.sample_coarse(self.videos[duration], workspace, duration, AnalysisSettings(),
                                       CancellationToken())
        return frames, runner

    def test_short_media_always_gets_coarse_frames(self):
        for duration in SHORT_DURATIONS:
            with self.subTest(duration=duration):
                frames, _ = self.coarse(duration, f"coarse-short-{duration}")
                self.assertGreaterEqual(len(frames), 1)
                self.assertEqual(frames[0].timestamp_seconds, 0.0)
                for frame in frames:
                    self.assertTrue(0.0 <= frame.timestamp_seconds <= duration)
                    with Image.open(frame.path) as image:
                        self.assertEqual(image.size, (384, 384))

    def test_longer_media_keeps_the_unchanged_coarse_commands_and_frames(self):
        for duration, periodic in LONG_DURATIONS.items():
            with self.subTest(duration=duration):
                frames, runner = self.coarse(duration, f"coarse-long-{duration}")
                # Exactly the two historical FFmpeg invocations (periodic, then scene); no fallback.
                self.assertEqual(len(runner.commands), 2)
                self.assertIn("fps=0.200000,scale=384:384:force_original_aspect_ratio=decrease,"
                              "pad=384:384:(ow-iw)/2:(oh-ih)/2", runner.commands[0])
                self.assertNotIn("-frames:v", runner.commands[0] + runner.commands[1])
                interval = sorted((self.root / f"coarse-long-{duration}" / "frames" / "interval").glob("frame_*.jpg"))
                self.assertEqual(len(interval), periodic)
                self.assertEqual(frames[0].timestamp_seconds, 0.0)

    def test_short_and_tail_candidate_windows_are_densely_sampled(self):
        service, runner = self.service()
        # Measured 2026-10-22: the dense pass writes nothing only when a window shorter than half a period
        # reaches the end of the stream (a sub-0.5 s video, or a short final window of a long video).
        # A short window in the middle of a video still gets a frame and is covered by the unchanged test below.
        short = self.make_video(0.4, "clip_0.4.mkv")
        cases = [(short, 0.4, CandidateWindow(window_id="short", start_seconds=0.0, end_seconds=0.4,
                                              peak_probability=0.9, evidence_timestamps=[0.0])),
                 (self.videos[40.0], 40.0, CandidateWindow(window_id="tail", start_seconds=39.7, end_seconds=40.0,
                                                           peak_probability=0.9, evidence_timestamps=[39.7]))]
        for video, duration, window in cases:
            with self.subTest(window=window.window_id):
                frames, batches = service.refine_candidates(video, self.root / f"dense-{window.window_id}", duration,
                                                            AnalysisSettings(), [window], [], CancellationToken())
                self.assertEqual(len(frames), 1)
                self.assertEqual(frames[0].timestamp_seconds, window.start_seconds)
                self.assertEqual(len(batches), 1)

    def test_normal_candidate_windows_keep_the_unchanged_dense_sampling(self):
        for window, expected in (
                (CandidateWindow(window_id="normal", start_seconds=10.0, end_seconds=15.0, peak_probability=0.9,
                                 evidence_timestamps=[10.0]), [10.0, 11.0, 12.0, 13.0, 14.0]),
                (CandidateWindow(window_id="mid-short", start_seconds=30.0, end_seconds=30.3, peak_probability=0.9,
                                 evidence_timestamps=[30.0]), [30.0])):
            with self.subTest(window=window.window_id):
                service, runner = self.service()
                frames, _ = service.refine_candidates(self.videos[40.0], self.root / f"dense-{window.window_id}", 40.0,
                                                      AnalysisSettings(), [window], [], CancellationToken())
                self.assertEqual([f.timestamp_seconds for f in frames], expected)
                self.assertEqual(len(runner.commands), 1)
                self.assertNotIn("-frames:v", runner.commands[0])

    def test_undecodable_media_still_fails_instead_of_being_masked(self):
        broken = self.root / "broken.mkv"
        broken.write_bytes(b"not a video stream" * 64)
        service, _ = self.service()
        with self.assertRaises(RuntimeError):
            service.sample_coarse(broken, self.root / "broken-workspace", 1.0, AnalysisSettings(),
                                  CancellationToken())

    def test_cancellation_is_never_turned_into_a_fallback(self):
        from services.analysis.cancellation import AnalysisCancelled

        class CancellingRunner(RecordingRunner):
            def run(self, command, *, cancellation, check=True):
                self.commands.append(command)
                raise AnalysisCancelled("cancelled")

        runner = CancellingRunner()
        service = VisualSamplingService(ffmpeg_service=FFmpegService(self.ffmpeg, self.ffprobe), process_runner=runner)
        with self.assertRaises(AnalysisCancelled):
            service.sample_coarse(self.videos[1.0], self.root / "cancelled", 1.0, AnalysisSettings(),
                                  CancellationToken())
        self.assertEqual(len(runner.commands), 1)

    def run_pipeline(self, duration, probability):
        cache = AnalysisCache(self.root / f"cache-{duration}-{probability}")
        prefilter, provider = _SafePrefilter(probability), _Provider()
        services = AnalysisServices(cache=cache, preflight=PreflightService(cache=cache), text_evidence=_NoText(),
                                    visual_sampling=VisualSamplingService(
                                        ffmpeg_service=FFmpegService(self.ffmpeg, self.ffprobe)),
                                    prefilter=prefilter, provider=provider)
        record = AnalysisPipeline(services).run(
            AnalysisRunRequest(video_path=self.videos[duration], settings=AnalysisSettings(model_id="mock-local-vlm",
                                                                                           use_gpu=False)),
            job_id=f"short-{duration}-{probability}")
        return record, prefilter, provider

    def test_short_media_pipeline_completes_and_reaches_the_vlm(self):
        for duration in (0.5, 1.5, 2.49):
            with self.subTest(duration=duration, prefilter="safe"):
                record, prefilter, provider = self.run_pipeline(duration, 0.05)
                self.assertEqual(record.status, AnalysisStatus.COMPLETED, record.errors)
                self.assertGreaterEqual(record.metrics["coarse_frame_count"], 1)
                self.assertGreaterEqual(len(prefilter.frames), 1)  # the gate scored real frames
                self.assertEqual(record.candidate_windows, [])
                self.assertEqual(provider.batches, [])
            with self.subTest(duration=duration, prefilter="alert"):
                record, prefilter, provider = self.run_pipeline(duration, 0.95)
                self.assertEqual(record.status, AnalysisStatus.COMPLETED, record.errors)
                self.assertEqual(len(record.candidate_windows), 1)
                self.assertGreaterEqual(len(provider.batches), 1)
                self.assertEqual(len(record.suggestions), 1)


if __name__ == "__main__":
    unittest.main()
