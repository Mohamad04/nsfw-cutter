"""Regression tests: the timestamp attached to every sampled frame must be the time of the source frame it shows.

Each synthetic frame carries its own decoded-order index as a 16-bit bar code (16 vertical stripes in the
middle third of the picture), which survives the 384/512 letterbox scaling and JPEG encoding. The true
presentation time of every source frame comes independently from ffprobe on the generated file, so the
check also holds for variable frame rate media. A sampled frame is correct when its timestamp is within one
source frame duration of the presentation time of the frame it shows.

FFmpeg's ``fps`` filter rewrites output timestamps to its own tick grid (``pts_time`` after the filter is the
tick, not the source time), so neither the output index nor the post-filter ``pts_time`` identifies the
source frame. Synthetic, non-sensitive test patterns only.
"""

import math
import statistics
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from services.analysis.cancellation import CancellationToken
from services.analysis.contracts import AnalysisSettings, CandidateWindow, SampledFrame
from services.analysis.visual_sampling import VisualSamplingService
from services.infrastructure.ffmpeg.paths import FFmpegNotFoundError, get_ffmpeg_path, get_ffprobe_path
from services.infrastructure.ffmpeg.runner import FFmpegService

BITS = 16
# Bar code in the middle third; outside it the background alternates black/white every `scene_period`
# seconds (0 disables it), which gives the scene detector unambiguous cuts at known times.
_BARCODE = f"if(bitand(floor(N/pow(2,floor(X*{BITS}/W))),1),235,16)"
EPSILON = 0.001


def _geq(scene_period: float) -> str:
    background = f"if(mod(floor(T/{scene_period}),2),235,16)" if scene_period else "16"
    return f"geq=lum='if(between(Y,H/3,2*H/3),{_BARCODE},{background})'"


def decode_index(path: Path) -> int:
    """Read the bar code on the middle row of a letterboxed, scaled frame."""
    with Image.open(path) as image:
        gray = image.convert("L")
        width, height = gray.size
        row = height // 2
        return sum(1 << bit for bit in range(BITS) if gray.getpixel((int((bit + 0.5) * width / BITS), row)) > 128)


class TimestampFixture:
    """A synthetic clip and the presentation time of each of its frames, in decoded order.

    Times are on the timeline FFmpeg's -ss and the player use: relative to the container start time,
    which is not zero when ``ts_offset`` is set (``-output_ts_offset``) or an MP4 edit list shifts it.
    """

    def __init__(self, ffmpeg, ffprobe, path: Path, rate: str, duration: float, *, scene_period=0.0, setpts="",
                 ts_offset=0.0, b_frames=0):
        self.path = path
        chain = f"{_geq(scene_period)}" + (f",setpts='{setpts}'" if setpts else "")
        command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   f"color=c=black:s=320x180:r={rate}:d={duration},format=gray", "-vf", chain,
                   "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", "-bf", str(b_frames)]
        if setpts:
            command += ["-fps_mode", "passthrough"]
        if ts_offset:
            command += ["-output_ts_offset", f"{ts_offset}"]
        subprocess.run([*command, "-y", str(path)], check=True, capture_output=True)
        probe = subprocess.run([str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "frame=pts_time", "-of", "csv=p=0", str(path)], check=True, capture_output=True,
                               text=True)
        absolute = [float(line.strip().rstrip(",")) for line in probe.stdout.split() if line.strip()]
        format_probe = subprocess.run([str(ffprobe), "-v", "error", "-show_entries", "format=start_time,duration",
                                       "-of", "default=nw=1", str(path)], check=True, capture_output=True, text=True)
        fields = dict(line.split("=", 1) for line in format_probe.stdout.split())
        self.start_time = float(fields.get("start_time", 0.0))
        self.duration = float(fields["duration"])
        self.pts = [value - self.start_time for value in absolute]

    def frame_duration(self, index: int) -> float:
        if index + 1 < len(self.pts):
            return self.pts[index + 1] - self.pts[index]
        return self.duration - self.pts[index]


class SampledFrameTimestampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc))
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        make = lambda name, rate, duration, **kw: TimestampFixture(cls.ffmpeg, cls.ffprobe, cls.root / f"{name}.mkv",
                                                                   rate, duration, **kw)
        cls.ntsc = make("ntsc_23976", "24000/1001", 30.0)
        cls.pal = make("pal_25", "25", 30.0)
        cls.short = {d: make(f"short_{d:g}", "25", d) for d in (0.5, 1.0, 2.0, 3.0, 7.0, 10.0)}
        cls.scenes = make("scenes_25", "25", 12.0, scene_period=3.0)
        # Variable frame rate: every 25th frame is held 0.5 s longer than the others.
        cls.vfr = make("vfr", "25", 20.0, setpts="(N/25+floor(N/25)*0.5)/TB")
        # Non-zero container start times: an explicit 3 s offset, and an MP4 with B-frames (edit list).
        cls.offset = make("offset_3s", "24000/1001", 20.0, ts_offset=3.0)
        cls.mp4 = TimestampFixture(cls.ffmpeg, cls.ffprobe, cls.root / "bframes.mp4", "24000/1001", 20.0, b_frames=2,
                                   ts_offset=1.5)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def service(self):
        return VisualSamplingService(ffmpeg_service=FFmpegService(self.ffmpeg, self.ffprobe))

    def workdir(self, name):
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def measure(self, fixture: TimestampFixture, frames: list[SampledFrame]):
        rows = []
        for frame in frames:
            index = decode_index(frame.path)
            self.assertLess(index, len(fixture.pts), f"bar code {index} beyond the source frames ({frame.path})")
            rows.append({"source": frame.source, "assigned": frame.timestamp_seconds, "index": index,
                         "true": fixture.pts[index], "offset": frame.timestamp_seconds - fixture.pts[index],
                         "tolerance": fixture.frame_duration(index) + EPSILON})
        return rows

    def assert_timestamps_match_content(self, fixture, frames, label):
        rows = self.measure(fixture, frames)
        self.assertTrue(rows, f"{label}: no frames")
        wrong = [r for r in rows if abs(r["offset"]) > r["tolerance"]]
        if wrong:
            offsets = [r["true"] - r["assigned"] for r in wrong]
            sample = ", ".join(f"{r['source']} {r['assigned']:.3f}s shows frame {r['index']} @ {r['true']:.3f}s"
                               for r in wrong[:4])
            self.fail(f"{label}: {len(wrong)}/{len(rows)} frames show content from another time; content - "
                      f"assigned: median {statistics.median(offsets):+.3f}s, min {min(offsets):+.3f}s, "
                      f"max {max(offsets):+.3f}s. e.g. {sample}")
        return rows

    # ----------------------------------------------------------------- harness sanity

    def test_bar_code_and_probe_identify_the_exact_source_frame(self):
        """An accurate seek with -copyts reports the source time of the frame it decodes: harness check."""
        for fixture in (self.ntsc, self.pal, self.vfr):
            for seconds in (0.0, 3.3, 11.7, 19.04):
                with self.subTest(fixture=fixture.path.name, seconds=seconds):
                    output = self.root / f"probe_{fixture.path.stem}_{seconds}.jpg"
                    result = subprocess.run([str(self.ffmpeg), "-hide_banner", "-nostdin", "-ss", f"{seconds}",
                                             "-copyts", "-i", str(fixture.path), "-frames:v", "1", "-vf",
                                             "showinfo,scale=512:512:force_original_aspect_ratio=decrease,"
                                             "pad=512:512:(ow-iw)/2:(oh-ih)/2", "-y", str(output)],
                                            capture_output=True, text=True, check=True)
                    shown = float(result.stderr.split("pts_time:")[1].split()[0])
                    self.assertAlmostEqual(fixture.pts[decode_index(output)], shown, delta=EPSILON)

    # ----------------------------------------------------------------- coarse (interval) path

    def test_coarse_interval_frames_show_their_timestamp(self):
        for fixture in (self.ntsc, self.pal, self.vfr):
            with self.subTest(fixture=fixture.path.name):
                frames = self.service()._sample_intervals(fixture.path, self.workdir(f"coarse_{fixture.path.stem}"),
                                                          fixture.duration, 0.2, CancellationToken())
                self.assert_timestamps_match_content(fixture, frames, f"coarse {fixture.path.name}")

    def test_coarse_frames_of_short_media_show_their_timestamp(self):
        for duration, fixture in self.short.items():
            with self.subTest(duration=duration):
                workspace = self.root / f"coarse_short_{duration:g}"
                frames = self.service().sample_coarse(fixture.path, workspace, fixture.duration, AnalysisSettings(),
                                                      CancellationToken())
                self.assert_timestamps_match_content(fixture, frames, f"coarse short {duration:g}s")

    # ----------------------------------------------------------------- scene path

    def test_scene_frames_show_their_timestamp_and_land_on_the_cuts(self):
        frames = self.service()._sample_scenes(self.scenes.path, self.workdir("scenes"), self.scenes.duration,
                                               0.35, CancellationToken())
        rows = self.assert_timestamps_match_content(self.scenes, frames, "scene")
        cuts = sorted({round(r["true"], 3) for r in rows})
        self.assertEqual(cuts, [0.0, 3.0, 6.0, 9.0])

    # ----------------------------------------------------------------- dense path (-ss)

    def dense(self, fixture, start, end, name):
        return self.service()._sample_window_intervals(fixture.path, self.workdir(name), start, end, fixture.duration,
                                                       1.0, CancellationToken())

    def test_dense_window_frames_show_their_timestamp(self):
        for fixture in (self.ntsc, self.pal, self.vfr):
            for start, end in ((0.0, 10.0), (7.3, 17.3), (12.04, 18.5)):
                with self.subTest(fixture=fixture.path.name, window=(start, end)):
                    frames = self.dense(fixture, start, end, f"dense_{fixture.path.stem}_{start}")
                    self.assert_timestamps_match_content(fixture, frames,
                                                         f"dense {fixture.path.name} [{start}, {end}]")

    def test_dense_window_near_the_end_shows_its_timestamp(self):
        fixture = self.pal
        last = fixture.pts[-1]
        for start, end in ((fixture.duration - 2.7, fixture.duration), (last + 0.02, fixture.duration)):
            with self.subTest(window=(start, end)):
                frames = self.dense(fixture, start, end, f"dense_end_{start:.3f}")
                self.assert_timestamps_match_content(fixture, frames, f"dense end [{start:.3f}, {end:.3f}]")

    def test_refined_frames_reaching_the_batches_show_their_timestamp(self):
        """Production path: dense frames plus the in-window coarse frames, as grouped into VLM batches."""
        fixture, settings = self.pal, AnalysisSettings()
        service = self.service()
        coarse = service.sample_coarse(fixture.path, self.root / "refine_ws", fixture.duration, settings,
                                       CancellationToken())
        window = CandidateWindow(window_id="candidate-00000", start_seconds=8.2, end_seconds=20.2,
                                 peak_probability=0.6, evidence_timestamps=[13.2], trigger="visual")
        frames, batches = service.refine_candidates(fixture.path, self.root / "refine_ws", fixture.duration, settings,
                                                    [window], coarse, CancellationToken())
        self.assertTrue(batches)
        self.assert_timestamps_match_content(fixture, [f for b in batches for f in b.frames], "refined batches")

    # ----------------------------------------------------------------- sampling profile 2 guarantees

    def test_non_zero_container_start_times_share_the_start_relative_timeline(self):
        """Coarse, scene and dense passes agree when the container starts after zero (no -copyts drift)."""
        for fixture in (self.offset, self.mp4):
            with self.subTest(fixture=fixture.path.name, start_time=fixture.start_time):
                self.assertGreater(fixture.start_time, 0.5)
                coarse = self.service().sample_coarse(fixture.path, self.root / f"offset_ws_{fixture.path.stem}",
                                                      fixture.duration, AnalysisSettings(), CancellationToken())
                self.assert_timestamps_match_content(fixture, coarse, f"coarse {fixture.path.name}")
                dense = self.dense(fixture, 6.3, 12.3, f"offset_dense_{fixture.path.stem}")
                rows = self.assert_timestamps_match_content(fixture, dense, f"dense {fixture.path.name}")
                self.assertGreaterEqual(rows[0]["true"], 6.3 - EPSILON)

    def test_periodic_timestamps_are_the_source_presentation_times(self):
        """Exact up to FFmpeg's rebasing of the seek point to the stream time base (< 1 ms), not one frame."""
        cases = [("coarse", fixture, self.service()._sample_intervals(
                      fixture.path, self.workdir(f"exact_coarse_{fixture.path.stem}"), fixture.duration, 0.2,
                      CancellationToken())) for fixture in (self.ntsc, self.vfr, self.offset)]
        cases += [("dense", fixture, self.dense(fixture, 4.321, 14.321, f"exact_dense_{fixture.path.stem}"))
                  for fixture in (self.ntsc, self.vfr, self.offset, self.mp4)]
        for path, fixture, frames in cases:
            with self.subTest(path=path, fixture=fixture.path.name):
                offsets = [abs(r["offset"]) for r in self.measure(fixture, frames)]
                self.assertLessEqual(max(offsets), EPSILON, offsets)

    def test_periodic_sampling_leaves_no_gap_longer_than_one_period(self):
        """Short-event recall: any event longer than one period plus one frame contains a sampled frame.

        Each written frame is the first one at or after its grid tick, so consecutive frames are at most one
        period plus one source frame apart, the first frame is within one frame of the span start, and the last
        one is within one period plus one frame of the span end.
        """
        for fixture in (self.ntsc, self.pal, self.vfr):
            longest_frame = max(fixture.frame_duration(i) for i in range(len(fixture.pts)))
            spans = [("coarse", 0.0, fixture.duration, 0.2, self.service()._sample_intervals(
                fixture.path, self.workdir(f"gap_coarse_{fixture.path.stem}"), fixture.duration, 0.2,
                CancellationToken()))]
            for start in (0.0, 3.37, 9.81, 15.5):
                end = min(fixture.duration, start + 6.0)
                spans.append(("dense", start, end, 1.0, self.dense(fixture, start, end,
                                                                   f"gap_dense_{fixture.path.stem}_{start}")))
            for path, start, end, rate, frames in spans:
                with self.subTest(fixture=fixture.path.name, path=path, start=start):
                    times = [frame.timestamp_seconds for frame in frames]
                    self.assertEqual(times, sorted(times))
                    self.assertLessEqual(times[0] - start, longest_frame + EPSILON)
                    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
                    self.assertLessEqual(max(gaps, default=0.0), 1 / rate + longest_frame + EPSILON, gaps)
                    self.assertLessEqual(end - times[-1], 1 / rate + longest_frame + EPSILON)

    def test_one_frame_per_started_tick_and_an_exclusive_span_end(self):
        """ceil(span x rate) frames on constant frame rates, all strictly before the end of the span.

        The former fps sampler wrote about round(span x rate) frames: a span whose length is not a whole number
        of periods now gets one more frame (for example 7 instead of 6 for 6.46 s at 1 FPS). Contiguous candidate
        windows [a, b) and [b, c) never both keep a frame at b.
        """
        for fixture in (self.ntsc, self.pal):
            coarse = self.service()._sample_intervals(fixture.path, self.workdir(f"count_coarse_{fixture.path.stem}"),
                                                      fixture.duration, 0.2, CancellationToken())
            # One frame for every tick up to the last frame's presentation time (not the container duration).
            self.assertEqual(len(coarse), math.floor(fixture.pts[-1] * 0.2 + EPSILON) + 1)
            for start, length in ((12.04, 10.0), (12.04, 6.46), (12.04, 2.7), (12.04, 1.4), (3.37, 5.0)):
                with self.subTest(fixture=fixture.path.name, start=start, length=length):
                    frames = self.dense(fixture, start, start + length, f"count_{fixture.path.stem}_{start}_{length}")
                    self.assertEqual(len(frames), math.ceil(length - EPSILON))
                    self.assertLess(frames[-1].timestamp_seconds, start + length)


class SamplingProfileCacheIdentityTests(unittest.TestCase):
    """Profile 2 results never reuse records, Marqo scores or VLM checkpoints computed with profile 1 timestamps."""

    def test_profile_2_has_its_own_record_prefilter_and_checkpoint_keys(self):
        from services.analysis.cache import AnalysisCache
        from services.analysis.contracts import VisualBatch

        current = AnalysisSettings()
        previous = current.model_copy(update={"sampling_profile_revision": 1})
        self.assertEqual(current.sampling_profile_revision, 2)
        fingerprint = "sha256:" + "ab" * 32
        keys = {revision: AnalysisCache.make_key(fingerprint, settings)
                for revision, settings in ((1, previous), (2, current))}
        self.assertNotEqual(keys[1], keys[2])
        frames = [SampledFrame(timestamp_seconds=5.0 * i, path=Path(f"f{i}.jpg"), source="interval") for i in range(3)]
        self.assertNotEqual(AnalysisCache.make_prefilter_key(keys[1], frames, previous),
                            AnalysisCache.make_prefilter_key(keys[2], frames, current))
        batch = VisualBatch(batch_id="candidate-00000-00000", start_seconds=0.0, end_seconds=10.5, frames=frames)
        self.assertNotEqual(AnalysisCache.make_batch_key(keys[1], batch, previous, prompt_schema_version="3"),
                            AnalysisCache.make_batch_key(keys[2], batch, current, prompt_schema_version="3"))


class EndToEndTimestampTests(unittest.TestCase):
    """Extraction -> contact sheet -> simulated VLM (frame numbers) -> fusion -> suggestion shown by the app.

    The simulated VLM reads the bar codes from the contact sheet itself, flags the frames of a known event and
    answers with one-based frame numbers, exactly like Qwen's compact wire format; the production conversion
    (providers.qwen._wire_response_to_review) turns them into seconds.
    """

    # Frames of the event in the 25 fps fixture, 9.60 s to 11.64 s: it contains the 10 s coarse frame, so the
    # gate opens a candidate window around it.
    EVENT = (240, 290)

    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg, cls.ffprobe = get_ffmpeg_path(), get_ffprobe_path()
        except FFmpegNotFoundError as exc:
            raise unittest.SkipTest(str(exc))
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.fixture = TimestampFixture(cls.ffmpeg, cls.ffprobe, cls.root / "e2e_25.mkv", "25", 30.0)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_suggestion_times_point_at_the_frames_the_vlm_flagged(self):
        from controllers.app.app_controller import _normalize_ai_suggestion
        from services.analysis.cache import AnalysisCache
        from services.analysis.contracts import (AnalysisRunRequest, AnalysisStatus, PrefilterFrameScore,
                                                 TextEvidenceOutput, VLMWireResponse)
        from services.analysis.pipeline import AnalysisPipeline, AnalysisServices
        from services.analysis.preflight import PreflightService
        from services.analysis.providers.qwen import _wire_response_to_review

        fixture, first, last = self.fixture, *self.EVENT
        in_event = lambda index: first <= index <= last

        class Prefilter:
            warnings = ()

            def check_ready(self, _settings, cancellation):
                cancellation.raise_if_cancelled()

            def score_frames(self, frames, _settings, cancellation, progress_callback=None):
                return [PrefilterFrameScore(frame=f, nsfw_probability=0.9 if in_event(decode_index(f.path)) else 0.02)
                        for f in frames]

            def release(self):
                pass

        class Text:
            def gather(self, *args, **kwargs):
                return TextEvidenceOutput()

        class SheetReadingProvider:
            model_id, warnings = "mock-local-vlm", []

            def __init__(self):
                self.shown = {}  # timestamp attached to a frame -> bar code read on the contact sheet

            def review_batch(self, batch, settings, cancellation):
                with Image.open(batch.contact_sheet_path) as sheet:
                    sheet = sheet.convert("L")
                    indices = []
                    for number in range(len(batch.frames)):
                        x0, y0 = (number % 2) * 384, (number // 2) * (384 + 28)
                        indices.append(sum(1 << bit for bit in range(BITS)
                                           if sheet.getpixel((x0 + int((bit + 0.5) * 384 / BITS), y0 + 192)) > 128))
                for frame, index in zip(batch.frames, indices, strict=True):
                    self.shown[frame.timestamp_seconds] = index
                flagged = [number + 1 for number, index in enumerate(indices) if in_event(index)]
                wire = VLMWireResponse.model_validate({"suggestions": [{
                    "category": "nudity", "confidence": 0.9, "first_frame": flagged[0], "last_frame": flagged[-1],
                    "evidence_frames": flagged[:8], "reason": "Synthetic event."}] if flagged else []})
                return _wire_response_to_review(wire, batch)

        cache = AnalysisCache(self.root / "cache")
        provider = SheetReadingProvider()
        services = AnalysisServices(cache=cache, preflight=PreflightService(cache=cache), text_evidence=Text(),
                                    visual_sampling=VisualSamplingService(
                                        ffmpeg_service=FFmpegService(self.ffmpeg, self.ffprobe)),
                                    prefilter=Prefilter(), provider=provider)
        settings = AnalysisSettings(model_id="mock-local-vlm", use_gpu=False)
        record = AnalysisPipeline(services).run(AnalysisRunRequest(video_path=fixture.path, settings=settings),
                                                job_id="e2e-timestamps")
        self.assertEqual(record.status, AnalysisStatus.COMPLETED, record.errors)
        self.assertEqual(len(record.suggestions), 1, record.suggestions)
        suggestion = record.suggestions[0]

        # 1. Every evidence timestamp is the presentation time of the frame the VLM saw on the contact sheet.
        for timestamp in suggestion.evidence_timestamps:
            index = provider.shown[timestamp]
            self.assertTrue(in_event(index), (timestamp, index))
            self.assertAlmostEqual(timestamp, fixture.pts[index], delta=EPSILON)
        # 2. The suggestion covers the true event; its start is the first flagged frame minus the documented
        #    0.5 s frame margin and 0.75 s context padding (no hidden offset).
        event_start, event_end = fixture.pts[first], fixture.pts[last] + fixture.frame_duration(last)
        first_seen = min(suggestion.evidence_timestamps)
        self.assertLessEqual(suggestion.start_seconds, event_start)
        self.assertGreaterEqual(suggestion.end_seconds, fixture.pts[last])
        self.assertLessEqual(first_seen - event_start, 1.0 + fixture.frame_duration(first) + EPSILON)
        self.assertAlmostEqual(suggestion.start_seconds, first_seen - 0.5 - settings.context_padding_seconds,
                               delta=EPSILON)
        self.assertLessEqual(suggestion.end_seconds - event_end, 0.5 + settings.context_padding_seconds + EPSILON)
        # 3. The application shows the same instants (hh:mm:ss.mmm) and keeps the exact seconds.
        shown = _normalize_ai_suggestion(suggestion.model_dump(mode="json"))
        self.assertEqual(shown["start_seconds"], suggestion.start_seconds)
        hours, minutes, seconds = shown["start"].split(":")
        self.assertAlmostEqual(int(hours) * 3600 + int(minutes) * 60 + float(seconds), suggestion.start_seconds,
                               delta=0.0005)


if __name__ == "__main__":
    unittest.main()
