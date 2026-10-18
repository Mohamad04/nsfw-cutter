"""Frame-level verification helpers for Fast/Smart Cutting exports.

Synthetic pattern (320x180, 25 fps, 30 s): left half luma = 16 + 8*floor(T) (source second),
right half luma = 16 + 8*(N mod 25) (frame within the second). Decoding any exported frame
therefore identifies its exact source frame. Optional audio: 40 ms 1 kHz click at every
integer second, used to measure audio/video offset after cutting.

Every subprocess started here has a timeout so a hung FFmpeg (known defect D1) cannot block
a test run.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

FPS = 25
DURATION_SECONDS = 30
SOURCE_FRAMES = FPS * DURATION_SECONDS
GOP_FRAMES = 50
DEFAULT_TIMEOUT_SECONDS = 120
TIME_EPSILON = 1e-6

PATTERN = (
    f"color=c=black:s=320x180:r={FPS}:d={DURATION_SECONDS},format=yuv420p,"
    f"geq=lum='if(lt(X,W/2),16+8*floor(T),16+8*mod(N,{FPS}))':cb=128:cr=128"
)
CLICKS = f"aevalsrc='if(lt(mod(t,1),0.04),0.5*sin(2*PI*1000*t),0)':s=48000:d={DURATION_SECONDS}"


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    audio: bool = True
    open_gop: bool = False
    container: str = "mp4"
    gop_frames: int = GOP_FRAMES


FIXTURES = {
    "h264_aac_mp4": FixtureSpec("h264_aac_mp4"),
    "h264_noaudio_mp4": FixtureSpec("h264_noaudio_mp4", audio=False),
    "h264_aac_opengop_mp4": FixtureSpec("h264_aac_opengop_mp4", open_gop=True),
    "h264_aac_mkv": FixtureSpec("h264_aac_mkv", container="mkv"),
}


def run(command: list[str], timeout: float = DEFAULT_TIMEOUT_SECONDS, text: bool = True):
    return subprocess.run(command, capture_output=True, text=text, timeout=timeout, check=False)


def generate_fixture(ffmpeg: Path, spec: FixtureSpec, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{spec.name}.{spec.container}"
    # Fixed B-frame placement makes x264 emit real open GOPs (leading B-frames decoded after the I-frame).
    x264_params = "open-gop=1:b-adapt=0" if spec.open_gop else "open-gop=0"
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-f", "lavfi", "-i", PATTERN,
    ]
    if spec.audio:
        command += ["-f", "lavfi", "-i", CLICKS]
    command += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        "-g", str(spec.gop_frames), "-keyint_min", str(spec.gop_frames), "-sc_threshold", "0", "-bf", "2",
        "-x264-params", x264_params,
    ]
    command += ["-c:a", "aac", "-b:a", "128k", "-shortest"] if spec.audio else ["-an"]
    command.append(str(output_path))
    completed = run(command)
    if completed.returncode != 0:
        raise RuntimeError(f"Fixture generation failed for {spec.name}: {completed.stderr[-400:]}")
    return output_path


def decode_frames(ffmpeg: Path, ffprobe: Path, path: Path) -> list[tuple[float | None, int | None]]:
    """Return [(pts_seconds, source_frame_index or None)] for every decoded video frame."""
    probe = run([str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path)])
    pts = []
    for line in probe.stdout.split():
        value = line.split(",")[0]
        pts.append(float(value) if value not in ("", "N/A") else None)
    raw = run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0",
               "-vf", "extractplanes=y,scale=2:1:flags=area", "-fps_mode", "passthrough",
               "-f", "rawvideo", "-"], text=False).stdout
    frames = []
    for position in range(0, len(raw) - 1, 2):
        second, within = (raw[position] - 16) / 8, (raw[position + 1] - 16) / 8
        identified = (
            abs(second - round(second)) < 0.3
            and abs(within - round(within)) < 0.3
            and 0 <= round(within) < FPS
        )
        index = round(second) * FPS + round(within) if identified else None
        frame_pts = pts[position // 2] if position // 2 < len(pts) else None
        frames.append((frame_pts, index))
    return frames


def is_removed(frame_index: int, removed: list[tuple[float, float]]) -> bool:
    """Half-open semantics: a source frame is removed iff its PTS lies in some [start, end)."""
    pts = frame_index / FPS
    return any(start - TIME_EPSILON <= pts < end - TIME_EPSILON for start, end in removed)


def removal_report(frames, removed: list[tuple[float, float]], total: int = SOURCE_FRAMES) -> dict:
    indices = [index for _, index in frames]
    present = [index for index in indices if index is not None]
    expected = [index for index in range(total) if not is_removed(index, removed)]
    present_set, expected_set = set(present), set(expected)
    leaked = sorted(present_set - expected_set)
    missing = sorted(expected_set - present_set)
    duplicates = len(present) - len(present_set)
    monotonic = all(later > earlier for earlier, later in pairwise(present))
    return {
        "decoded_frames": len(indices),
        "undecodable_frames": indices.count(None),
        "expected_frames": len(expected),
        "leaked_removed_frames": len(leaked),
        "leaked_runs": _runs(leaked),
        "missing_kept_frames": len(missing),
        "missing_runs": _runs(missing),
        "duplicate_frames": duplicates,
        "monotonic": monotonic,
        "frame_exact": not leaked and not missing and not duplicates and monotonic
        and indices.count(None) == 0,
    }


_SILENCE_END = re.compile(r"silence_end: ([0-9.]+)")


def av_sync(ffmpeg: Path, path: Path, frames) -> dict:
    """Click onsets versus decoded video: offset = video source time at onset - nearest second."""
    completed = run([str(ffmpeg), "-hide_banner", "-nostdin", "-i", str(path), "-map", "0:a:0",
                     "-af", "silencedetect=n=-30dB:d=0.005", "-f", "null", "-"])
    if completed.returncode != 0:
        return {"audio": False}
    onsets = [float(value) for value in _SILENCE_END.findall(completed.stderr)]
    audio_end = stream_durations(ffmpeg.with_name(ffmpeg.name.replace("ffmpeg", "ffprobe")), path).get("audio")
    timeline = [(pts, index) for pts, index in frames if pts is not None and index is not None]
    errors = []
    for onset in onsets:
        if audio_end is not None and onset >= audio_end - 0.05:
            continue  # silencedetect reports a silence end at end of stream: not a click
        prior = [(pts, index) for pts, index in timeline if pts <= onset + TIME_EPSILON]
        if not prior:
            continue
        pts, index = prior[-1]
        window = [other for other_pts, other in timeline if pts - 2.5 / FPS <= other_pts <= pts + 3.5 / FPS]
        if any(later != earlier + 1 for earlier, later in pairwise(window)):
            continue  # onset within two frames of a splice (possibly a click cut in half): excluded
        source_time = index / FPS + (onset - pts)
        errors.append(round((source_time - round(source_time)) * 1000, 1))
    absolute = sorted(abs(error) for error in errors)
    return {
        "audio": True,
        "onsets": len(onsets),
        "measured_onsets": len(errors),
        "median_abs_offset_ms": absolute[len(absolute) // 2] if absolute else None,
        "max_abs_offset_ms": absolute[-1] if absolute else None,
    }


def stream_durations(ffprobe: Path, path: Path) -> dict:
    completed = run([str(ffprobe), "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration",
                     "-of", "default=nw=1", str(path)])
    durations: dict = {}
    codec_type = None
    for line in completed.stdout.splitlines():
        key, _, value = line.partition("=")
        if key == "codec_type":
            codec_type = value
        elif key == "duration" and value not in ("", "N/A"):
            durations[codec_type or "format"] = round(float(value), 3)
            codec_type = None
    return durations


def expected_kept_duration(removed: list[tuple[float, float]]) -> float:
    kept = [index for index in range(SOURCE_FRAMES) if not is_removed(index, removed)]
    return round(len(kept) / FPS, 3)


def _runs(values: list[int]) -> list[str]:
    runs: list[list[int]] = []
    for value in values:
        if runs and value == runs[-1][1] + 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    return [f"{first}-{last} (src {first / FPS:.2f}s, {(last - first + 1) / FPS:.2f}s)" for first, last in runs][:10]
