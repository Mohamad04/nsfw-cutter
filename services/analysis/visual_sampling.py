from __future__ import annotations

import re
import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Literal

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisSettings,
    CandidateWindow,
    SampledFrame,
    VisualBatch,
)
from services.analysis.process import CancellableProcessRunner
from services.infrastructure.ffmpeg.runner import FFmpegService

ProgressCallback = Callable[[int, str], None]
_PTS_TIME_PATTERN = re.compile(r"\bpts_time:(-?\d+(?:\.\d+)?)")
_SHOWINFO_FRAME_PATTERN = re.compile(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:(\S+)")
_SHOWINFO_TIME_BASE_PATTERN = re.compile(r"\bconfig in time_base:\s*(\d+)/(\d+)")
# Absorbs float rounding of source timestamps that fall exactly on a sampling tick.
_GRID_EPSILON = "0.000001"
_CLASSIFIER_FRAME_FILTER = (
    "scale=384:384:force_original_aspect_ratio=decrease,"
    "pad=384:384:(ow-iw)/2:(oh-ih)/2"
)
_REFINED_FRAME_FILTER = (
    "scale=512:512:force_original_aspect_ratio=decrease,"
    "pad=512:512:(ow-iw)/2:(oh-ih)/2"
)


class VisualSamplingService:
    def __init__(
        self,
        *,
        ffmpeg_service: FFmpegService | None = None,
        process_runner: CancellableProcessRunner | None = None,
    ) -> None:
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.process_runner = process_runner or CancellableProcessRunner()

    def sample(
        self,
        video_path: str | Path,
        workspace: str | Path,
        duration_seconds: float,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[SampledFrame], list[VisualBatch]]:
        """Compatibility wrapper for callers which still request direct batching.

        The production pipeline uses ``sample_coarse`` followed by
        ``refine_candidates`` so safe portions of a movie never reach Qwen.
        """
        frames = self.sample_coarse(
            video_path,
            workspace,
            duration_seconds,
            settings,
            cancellation,
            progress_callback,
        )
        batches = _build_batches(
            frames,
            settings.batch_size,
            duration_seconds,
            contact_sheet_dir=Path(workspace) / "frames" / "contact_sheets",
        )
        return frames, batches

    def sample_coarse(
        self,
        video_path: str | Path,
        workspace: str | Path,
        duration_seconds: float,
        settings: AnalysisSettings,
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
    ) -> list[SampledFrame]:
        cancellation.raise_if_cancelled()
        workspace_path = Path(workspace)
        interval_dir = workspace_path / "frames" / "interval"
        scene_dir = workspace_path / "frames" / "scene"
        interval_dir.mkdir(parents=True, exist_ok=True)
        scene_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback is not None:
            progress_callback(0, "Sampling coarse movie frames")
        interval_frames = self._sample_intervals(
            video_path,
            interval_dir,
            duration_seconds,
            settings.resolved_coarse_sample_rate_fps,
            cancellation,
        )
        cancellation.raise_if_cancelled()
        if progress_callback is not None:
            progress_callback(50, "Detecting scene changes")
        scene_frames = self._sample_scenes(
            video_path,
            scene_dir,
            duration_seconds,
            settings.scene_threshold,
            cancellation,
        )

        frames = _deduplicate_frames(interval_frames + scene_frames)
        if not frames:
            raise RuntimeError("FFmpeg did not produce any readable sampled frames")
        if progress_callback is not None:
            progress_callback(100, f"Prepared {len(frames)} coarse frames")
        return frames

    def refine_candidates(
        self,
        video_path: str | Path,
        workspace: str | Path,
        duration_seconds: float,
        settings: AnalysisSettings,
        candidates: list[CandidateWindow],
        coarse_frames: list[SampledFrame],
        cancellation: CancellationToken,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[SampledFrame], list[VisualBatch]]:
        """Densely sample only candidate windows and build compact contact sheets."""
        cancellation.raise_if_cancelled()
        workspace_path = Path(workspace)
        refined_root = workspace_path / "frames" / "refined"
        contact_sheet_dir = workspace_path / "frames" / "contact_sheets"
        refined_root.mkdir(parents=True, exist_ok=True)
        contact_sheet_dir.mkdir(parents=True, exist_ok=True)

        all_frames: list[SampledFrame] = []
        batches: list[VisualBatch] = []
        for candidate_index, candidate in enumerate(candidates):
            cancellation.raise_if_cancelled()
            if progress_callback is not None:
                progress_callback(
                    int(100 * candidate_index / max(1, len(candidates))),
                    f"Refining candidate {candidate_index + 1} of {len(candidates)}",
                )
            output_dir = refined_root / _safe_identifier(candidate.window_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            dense_frames = self._sample_window_intervals(
                video_path,
                output_dir,
                candidate.start_seconds,
                candidate.end_seconds,
                duration_seconds,
                settings.resolved_dense_sample_rate_fps,
                cancellation,
            )
            in_window_coarse = [
                frame
                for frame in coarse_frames
                if candidate.start_seconds <= frame.timestamp_seconds <= candidate.end_seconds
            ]
            window_frames = _deduplicate_frames(dense_frames + in_window_coarse)
            if not window_frames:
                continue
            all_frames.extend(window_frames)
            window_batches = _build_batches(
                window_frames,
                settings.batch_size,
                duration_seconds,
                batch_prefix=candidate.window_id,
                candidate_window_id=candidate.window_id,
                interval_bounds=(candidate.start_seconds, candidate.end_seconds),
                contact_sheet_dir=contact_sheet_dir,
            )
            batches.extend(window_batches)
        return _deduplicate_frames(all_frames), batches

    def _sample_intervals(
        self,
        video_path: str | Path,
        output_dir: Path,
        duration_seconds: float,
        sample_rate_fps: float,
        cancellation: CancellationToken,
    ) -> list[SampledFrame]:
        output_pattern = output_dir / "frame_%08d.jpg"
        command = _FrameCommand(
            [
                self.ffmpeg_service.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostats",
                "-nostdin",
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-vf",
                f"{_periodic_select_filter(sample_rate_fps)},showinfo,{_CLASSIFIER_FRAME_FILTER}",
                "-fps_mode",
                "passthrough",
                "-q:v",
                "3",
                "-an",
                "-sn",
                "-dn",
                "-start_number",
                "0",
                output_pattern,
            ]
        )
        timed_paths = self._extract_frames(
            command,
            [
                _first_frame_command(
                    self.ffmpeg_service.ffmpeg_path, video_path, output_pattern, _CLASSIFIER_FRAME_FILTER
                )
            ],
            output_dir,
            cancellation,
        )
        return [
            SampledFrame(
                timestamp_seconds=max(0.0, min(duration_seconds, seconds)),
                path=path,
                source="interval",
            )
            for path, seconds in timed_paths
        ]

    def _sample_scenes(
        self,
        video_path: str | Path,
        output_dir: Path,
        duration_seconds: float,
        scene_threshold: float,
        cancellation: CancellationToken,
    ) -> list[SampledFrame]:
        output_pattern = output_dir / "scene_%08d.jpg"
        # Always select the first frame so FFmpeg can initialize its image encoder even
        # when a quiet video has no scene-change frames above the configured threshold.
        filter_expression = (
            f"select=eq(n\\,0)+gt(scene\\,{scene_threshold:.6f}),"
            f"showinfo,{_CLASSIFIER_FRAME_FILTER}"
        )
        command = [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-nostdin",
            "-i",
            video_path,
            "-map",
            "0:v:0",
            "-vf",
            filter_expression,
            "-fps_mode",
            "vfr",
            "-q:v",
            "3",
            "-an",
            "-sn",
            "-dn",
            "-start_number",
            "0",
            output_pattern,
        ]
        result = self.process_runner.run(command, cancellation=cancellation)
        timestamps = [
            max(0.0, min(duration_seconds, float(match.group(1))))
            for match in _PTS_TIME_PATTERN.finditer(result.stderr)
        ]
        paths = sorted(output_dir.glob("scene_*.jpg"))
        return [
            SampledFrame(timestamp_seconds=timestamp, path=path, source="scene")
            for path, timestamp in zip(paths, timestamps, strict=False)
        ]

    def _sample_window_intervals(
        self,
        video_path: str | Path,
        output_dir: Path,
        start_seconds: float,
        end_seconds: float,
        duration_seconds: float,
        sample_rate_fps: float,
        cancellation: CancellationToken,
    ) -> list[SampledFrame]:
        output_pattern = output_dir / "frame_%08d.jpg"
        clip_duration = max(0.001, end_seconds - start_seconds)
        # Without -copyts FFmpeg rebases timestamps to the seek point on the same start-relative
        # timeline as the coarse and scene passes (-copyts would add the container start time).
        # The input -t bounds decoding before the filters; the selection also bounds the span on source time.
        command = _FrameCommand(
            [
                self.ffmpeg_service.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "info",
                "-nostats",
                "-nostdin",
                "-ss",
                f"{start_seconds:.6f}",
                "-t",
                f"{clip_duration:.6f}",
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-vf",
                f"{_periodic_select_filter(sample_rate_fps, clip_duration)},showinfo,{_REFINED_FRAME_FILTER}",
                "-fps_mode",
                "passthrough",
                "-q:v",
                "3",
                "-an",
                "-sn",
                "-dn",
                "-start_number",
                "0",
                output_pattern,
            ],
            origin_seconds=start_seconds,
        )
        timed_paths = self._extract_frames(
            command,
            [
                _first_frame_command(
                    self.ffmpeg_service.ffmpeg_path,
                    video_path,
                    output_pattern,
                    _REFINED_FRAME_FILTER,
                    start_seconds=start_seconds,
                ),
                # A final window can start after the last frame but before the container
                # duration (within the last frame's display time): keep the displayed frame.
                _displayed_frame_command(
                    self.ffmpeg_service.ffmpeg_path,
                    video_path,
                    output_dir / "frame_00000000.jpg",
                    _REFINED_FRAME_FILTER,
                    start_seconds=start_seconds,
                ),
            ],
            output_dir,
            cancellation,
        )
        return [
            SampledFrame(
                timestamp_seconds=max(0.0, min(duration_seconds, seconds)),
                path=path,
                source="refined",
            )
            for path, seconds in timed_paths
        ]

    def _extract_frames(
        self,
        command: _FrameCommand,
        fallback_commands: list[_FrameCommand],
        output_dir: Path,
        cancellation: CancellationToken,
    ) -> list[tuple[Path, float]]:
        """Run a periodic sampling command and return each written frame with its source time.

        Every command places ``showinfo`` after the frame selection and before scaling, so the time
        attached to a written frame is the presentation time of the source frame it shows, never an
        index multiplied by a sampling period (FFmpeg's ``fps`` filter used to be the selector: it
        rewrites timestamps to its own tick grid and showed content about half a period later).

        The periodic selection keeps the first decoded frame, so it writes nothing only when the
        sampled span decodes no frame at all: a final candidate window that starts after the last
        frame but before the container duration. The image2 muxer then fails with "Nothing was
        written into output file", and the fallback commands run in order until one writes the frame
        shown at the start of the span. A command that wrote frames keeps its output (and its
        failure, if any); media that cannot be decoded still raise, and cancellation is never turned
        into a fallback.
        """
        failure: RuntimeError | None = None
        result = None
        try:
            result = self.process_runner.run(command.arguments, cancellation=cancellation)
        except AnalysisCancelled:
            raise
        except RuntimeError as error:
            failure = error
        paths = sorted(output_dir.glob("frame_*.jpg"))
        if paths:
            if failure is not None:
                raise failure
            return _timed_paths(command, paths, result.stderr)
        for fallback_command in fallback_commands:
            cancellation.raise_if_cancelled()
            try:
                result = self.process_runner.run(fallback_command.arguments, cancellation=cancellation)
            except AnalysisCancelled:
                raise
            except RuntimeError as error:
                failure = failure or error
                continue
            paths = sorted(output_dir.glob("frame_*.jpg"))
            if paths:
                return _timed_paths(fallback_command, paths, result.stderr)
        raise failure or RuntimeError("FFmpeg did not produce any readable sampled frames")


@dataclass(frozen=True)
class _FrameCommand:
    """An FFmpeg frame extraction whose ``showinfo`` log times the frames it writes.

    ``origin_seconds`` is the input seek point, to which FFmpeg rebases timestamps. ``keep`` says which
    timed frames were written: all of them, the first one (``-frames:v 1`` may filter a frame more
    than it writes) or the last one (``-update 1`` overwrites a single image).
    """

    arguments: list
    origin_seconds: float = 0.0
    keep: Literal["all", "first", "last"] = "all"


def _periodic_select_filter(sample_rate_fps: float, span_seconds: float | None = None) -> str:
    """Select the first frame, then the first frame at or after each later tick of the grid.

    Ticks are ``k / sample_rate_fps`` seconds after the (seek) origin of the input timeline. The
    decision uses source timestamps only, so variable frame rates are handled and a frame held
    across several ticks is written once; ``select`` never changes the timestamps that follow it.
    With ``span_seconds`` only frames before the end of the span are kept: an input ``-t`` counts
    from the first decoded frame, so it can let through a frame a few milliseconds past the end.
    """
    rate = f"{sample_rate_fps:.6f}"
    previous_tick = f"floor(prev_selected_t*{rate}+{_GRID_EPSILON})"
    periodic = f"if(isnan(prev_selected_t)\\,1\\,gte(t\\,({previous_tick}+1)/{rate}-{_GRID_EPSILON}))"
    if span_seconds is None:
        return f"select={periodic}"
    return f"select=lt(t\\,{span_seconds:.6f})*{periodic}"


def _showinfo_seconds(stderr: str) -> list[float]:
    """Presentation times logged by ``showinfo``, computed exactly from integer pts and time base."""
    time_base = _SHOWINFO_TIME_BASE_PATTERN.search(stderr or "")
    seconds = []
    for match in _SHOWINFO_FRAME_PATTERN.finditer(stderr or ""):
        if time_base is not None and int(time_base.group(2)) > 0:
            value = Fraction(int(match.group(1)) * int(time_base.group(1)), int(time_base.group(2)))
            seconds.append(float(value))
        else:
            seconds.append(float(match.group(2)))
    return seconds


def _timed_paths(command: _FrameCommand, paths: list[Path], stderr: str) -> list[tuple[Path, float]]:
    seconds = _showinfo_seconds(stderr)
    if command.keep == "all" and len(seconds) == len(paths):
        selected = seconds
    elif command.keep != "all" and len(paths) == 1 and seconds:
        selected = seconds[:1] if command.keep == "first" else seconds[-1:]
    else:
        # Never guess which source frame an image shows.
        raise RuntimeError(
            f"FFmpeg reported {len(seconds)} frame time(s) for {len(paths)} sampled frame(s)"
        )
    return [
        (path, command.origin_seconds + value)
        for path, value in zip(paths, selected, strict=True)
    ]


def _first_frame_command(
    ffmpeg_path,
    video_path: str | Path,
    output_pattern: Path,
    frame_filter: str,
    *,
    start_seconds: float | None = None,
) -> _FrameCommand:
    seek = ["-ss", f"{start_seconds:.6f}"] if start_seconds is not None else []
    return _FrameCommand(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-nostats",
            "-nostdin",
            *seek,
            "-i",
            video_path,
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            f"showinfo,{frame_filter}",
            "-q:v",
            "3",
            "-an",
            "-sn",
            "-dn",
            "-start_number",
            "0",
            output_pattern,
        ],
        origin_seconds=start_seconds or 0.0,
        keep="first",
    )


def _displayed_frame_command(
    ffmpeg_path,
    video_path: str | Path,
    output_path: Path,
    frame_filter: str,
    *,
    start_seconds: float,
    lookback_seconds: float = 1.0,
) -> _FrameCommand:
    """Keep the last frame decoded from shortly before ``start_seconds`` to the end of the stream.

    Only used once no frame starts at or after ``start_seconds``, so that last frame is the one
    displayed at ``start_seconds``; it is timed at its own presentation time, just before the span.
    """
    seek_seconds = max(0.0, start_seconds - lookback_seconds)
    return _FrameCommand(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-nostats",
            "-nostdin",
            "-ss",
            f"{seek_seconds:.6f}",
            "-i",
            video_path,
            "-map",
            "0:v:0",
            "-vf",
            f"showinfo,{frame_filter}",
            "-update",
            "1",
            "-q:v",
            "3",
            "-an",
            "-sn",
            "-dn",
            output_path,
        ],
        origin_seconds=seek_seconds,
        keep="last",
    )


def _deduplicate_frames(frames: list[SampledFrame], tolerance: float = 0.2) -> list[SampledFrame]:
    ordered = sorted(frames, key=lambda frame: (frame.timestamp_seconds, frame.source != "scene"))
    result: list[SampledFrame] = []
    for frame in ordered:
        if result and abs(frame.timestamp_seconds - result[-1].timestamp_seconds) <= tolerance:
            if frame.source == "scene" and result[-1].source != "scene":
                result[-1] = frame
            continue
        result.append(frame)
    return result


def _build_batches(
    frames: list[SampledFrame],
    batch_size: int,
    duration_seconds: float,
    *,
    batch_prefix: str = "batch",
    candidate_window_id: str = "",
    interval_bounds: tuple[float, float] | None = None,
    contact_sheet_dir: Path | None = None,
) -> list[VisualBatch]:
    batches = []
    for offset in range(0, len(frames), batch_size):
        batch_frames = frames[offset : offset + batch_size]
        batch_id = f"{_safe_identifier(batch_prefix)}-{offset // batch_size:05d}"
        start_bound = interval_bounds[0] if interval_bounds else 0.0
        end_bound = interval_bounds[1] if interval_bounds else duration_seconds
        batch_start = max(start_bound, batch_frames[0].timestamp_seconds - 0.5)
        batch_end = min(end_bound, batch_frames[-1].timestamp_seconds + 0.5)
        if batch_end <= batch_start:
            batch_end = min(duration_seconds, batch_start + 0.1)
        sheet_path = None
        if contact_sheet_dir is not None:
            sheet_path = contact_sheet_dir / f"{batch_id}.jpg"
            _create_contact_sheet(batch_frames, sheet_path)
        batches.append(
            VisualBatch(
                batch_id=batch_id,
                start_seconds=batch_start,
                end_seconds=batch_end,
                frames=batch_frames,
                candidate_window_id=candidate_window_id,
                contact_sheet_path=sheet_path,
            )
        )
    return batches


def _create_contact_sheet(frames: list[SampledFrame], output_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    cell_size = 384
    caption_height = 28
    columns = min(2, len(frames))
    rows = int(math.ceil(len(frames) / columns))
    sheet = Image.new("RGB", (columns * cell_size, rows * (cell_size + caption_height)), "black")
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(frames):
        with Image.open(frame.path) as source:
            image = ImageOps.fit(source.convert("RGB"), (cell_size, cell_size))
        x = (index % columns) * cell_size
        y = (index // columns) * (cell_size + caption_height)
        sheet.paste(image, (x, y))
        draw.rectangle((x, y + cell_size, x + cell_size, y + cell_size + caption_height), fill="black")
        draw.text(
            (x + 8, y + cell_size + 6),
            f"frame {index + 1}  {frame.timestamp_seconds:.2f}s",
            fill="white",
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="JPEG", quality=86, optimize=True)


def _safe_identifier(value: str) -> str:
    normalized = "".join(
        character for character in str(value) if character.isalnum() or character in "-_"
    )
    return normalized[:96] or "window"
