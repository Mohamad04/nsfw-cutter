from __future__ import annotations

import re
import math
from collections.abc import Callable
from pathlib import Path

from services.analysis.cancellation import CancellationToken
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
        command = [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            video_path,
            "-map",
            "0:v:0",
            "-vf",
            f"fps={sample_rate_fps:.6f},{_CLASSIFIER_FRAME_FILTER}",
            "-q:v",
            "3",
            "-an",
            "-sn",
            "-dn",
            "-start_number",
            "0",
            output_pattern,
        ]
        self.process_runner.run(command, cancellation=cancellation)
        paths = sorted(output_dir.glob("frame_*.jpg"))
        return [
            SampledFrame(
                timestamp_seconds=min(duration_seconds, index / sample_rate_fps),
                path=path,
                source="interval",
            )
            for index, path in enumerate(paths)
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
        command = [
            self.ffmpeg_service.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{start_seconds:.6f}",
            "-i",
            video_path,
            "-t",
            f"{clip_duration:.6f}",
            "-map",
            "0:v:0",
            "-vf",
            f"fps={sample_rate_fps:.6f},{_REFINED_FRAME_FILTER}",
            "-q:v",
            "3",
            "-an",
            "-sn",
            "-dn",
            "-start_number",
            "0",
            output_pattern,
        ]
        self.process_runner.run(command, cancellation=cancellation)
        paths = sorted(output_dir.glob("frame_*.jpg"))
        return [
            SampledFrame(
                timestamp_seconds=min(
                    duration_seconds,
                    end_seconds,
                    start_seconds + index / sample_rate_fps,
                ),
                path=path,
                source="refined",
            )
            for index, path in enumerate(paths)
        ]


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
