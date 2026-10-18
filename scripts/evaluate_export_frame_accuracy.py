"""Run the Fast/Smart Cutting frame-accuracy matrix against the current export code.

Usage:
    python scripts/evaluate_export_frame_accuracy.py --output-dir artifacts/<run> [--label after]

Generates deterministic synthetic fixtures, runs real FFmpeg exports through the production
services and writes <output-dir>/<label>_results.json. Every subprocess (including those
started by the production services) is given a timeout so the known audio-rebuild hang (D1)
is recorded as TIMEOUT instead of blocking the run.
"""

from __future__ import annotations

# Direct execution requires the project root before application imports.
# ruff: noqa: E402, I001, RUF100

import argparse
import functools
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation import export_frame_accuracy as efa
from services.infrastructure.ffmpeg.bounded_runner import BoundedProcessRunner, FFmpegTimeoutError


SUBPROCESS_TIMEOUT_SECONDS = 90

SMART = "smart"
FAST = "fast"
# expectation: "exact" = must complete frame-exact; "reject" = must refuse without output;
# "exact_or_reject" = either is acceptable, a completed export must be frame-exact.
TEN_ALIGNED_HALF_SECOND = [(1.0 + 2.5 * k, 1.5 + 2.5 * k) for k in range(10)]
TEN_UNALIGNED = [(round(1.013 + 2.5 * k, 3), round(1.517 + 2.5 * k, 3)) for k in range(10)]
TEN_KEYFRAME_ALIGNED = [(1.0 + 2 * k, 2.0 + 2 * k) for k in range(10)]

CASES = [
    ("S01", SMART, "h264_aac_mp4", [(7.3, 12.7)], "exact", "Non-keyframe cut"),
    ("S02", SMART, "h264_aac_mp4", [(6.0, 7.0)], "exact", "Cut starting exactly on a keyframe"),
    ("S03", SMART, "h264_aac_mp4", TEN_ALIGNED_HALF_SECOND, "exact", "Ten separate cuts (two start on keyframes)"),
    ("S04", SMART, "h264_aac_mp4", [(5.0, 6.0), (6.0, 7.3)], "exact", "Adjacent cuts"),
    ("S05", SMART, "h264_aac_mp4", [(5.0, 8.0), (7.0, 9.3)], "exact", "Overlapping cuts"),
    ("S06", SMART, "h264_aac_mp4", [(0.0, 2.3), (27.7, 30.0)], "exact", "Cuts at beginning and end"),
    ("S07", SMART, "h264_aac_mp4", [(25.3, 40.0)], "exact", "End beyond duration (clamped)"),
    ("S08", SMART, "h264_noaudio_mp4", [(7.3, 12.7)], "exact", "No-audio MP4, non-keyframe cut"),
    ("S09", SMART, "h264_aac_mp4", TEN_UNALIGNED, "exact", "Ten cuts off the frame grid (A/V drift)"),
    ("S10", SMART, "h264_aac_opengop_mp4", [(7.3, 12.7), (16.0, 17.0)], "exact_or_reject",
     "Open-GOP source (copy segments not cleanly copyable)"),
    ("S11", SMART, "h264_aac_mkv", [(7.3, 12.7)], "exact_or_reject", "MKV H.264 (known D2)"),
    ("S12", SMART, "h264_aac_mp4", [(0.0, 1.5), (10.0, 16.3), (28.7, 30.0)], "exact_or_reject",
     "Known D1 trigger ranges (audio rebuild may hang)"),
    ("F01", FAST, "h264_noaudio_mp4", [(7.3, 12.7)], "reject", "Non-keyframe cut"),
    ("F02", FAST, "h264_noaudio_mp4", [(8.0, 12.0)], "exact", "Keyframe-aligned cut"),
    ("F03", FAST, "h264_noaudio_gop25_mp4", TEN_KEYFRAME_ALIGNED, "exact", "Ten keyframe-aligned cuts (1 s GOP)"),
    ("F04", FAST, "h264_noaudio_mp4", TEN_ALIGNED_HALF_SECOND, "reject", "Ten cuts, most not on keyframes"),
    ("F05", FAST, "h264_noaudio_mp4", [(6.0, 8.0), (8.0, 10.0)], "exact", "Adjacent keyframe-aligned cuts"),
    ("F06", FAST, "h264_noaudio_mp4", [(6.0, 10.0), (8.0, 12.0)], "exact", "Overlapping keyframe-aligned cuts"),
    ("F07", FAST, "h264_noaudio_mp4", [(0.0, 2.0), (28.0, 30.0)], "exact", "Cuts at beginning and end"),
    ("F08", FAST, "h264_noaudio_mp4", [(26.0, 40.0)], "exact", "End beyond duration (clamped)"),
    ("F09", FAST, "h264_aac_mp4", [(8.0, 12.0)], "reject", "Source with audio (audio cannot be cut exactly)"),
    ("F10", FAST, "h264_noaudio_mkv", [(8.0, 12.0)], "exact_or_reject", "MKV, keyframe-aligned (known D2 seek)"),
    ("F11", FAST, "h264_noaudio_opengop_mp4", [(8.0, 12.0)], "exact_or_reject", "Open-GOP source, keyframe times"),
]

EXTRA_FIXTURES = {
    "h264_noaudio_gop25_mp4": efa.FixtureSpec("h264_noaudio_gop25_mp4", audio=False, gop_frames=25),
    "h264_noaudio_mkv": efa.FixtureSpec("h264_noaudio_mkv", audio=False, container="mkv"),
    "h264_noaudio_opengop_mp4": efa.FixtureSpec("h264_noaudio_opengop_mp4", audio=False, open_gop=True),
}
STALL_TIMEOUT_SECONDS = 20


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--label", default="run")
    parser.add_argument("--cases", nargs="*", help="Optional subset of case ids")
    parser.add_argument("--ffmpeg-bin", type=Path,
                        help="Directory with ffmpeg.exe/ffprobe.exe to use instead of the bundled build (comparison only)")
    parser.add_argument("--remeasure", action="store_true",
                        help="Re-score the existing outputs of <label> with the current measurement code (no export)")
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _install_subprocess_timeout(SUBPROCESS_TIMEOUT_SECONDS)

    from services.infrastructure.ffmpeg import paths
    from services.infrastructure.ffmpeg.paths import get_ffmpeg_path, get_ffprobe_path

    if args.ffmpeg_bin:
        override = args.ffmpeg_bin.resolve()
        paths.find_executable = lambda name: override / (name if name.endswith(".exe") else f"{name}.exe")

    ffmpeg, ffprobe = get_ffmpeg_path(), get_ffprobe_path()
    if args.remeasure:
        return remeasure(output_dir, args.label, ffmpeg, ffprobe)
    fixtures_dir = output_dir / "fixtures"
    specs = {**efa.FIXTURES, **EXTRA_FIXTURES}
    fixtures = {}
    for name, spec in specs.items():
        existing = fixtures_dir / f"{spec.name}.{spec.container}"
        fixtures[name] = existing if existing.is_file() else efa.generate_fixture(ffmpeg, spec, fixtures_dir)

    selected = [case for case in CASES if not args.cases or case[0] in args.cases]
    results = []
    for case_id, engine, fixture, removed, expectation, title in selected:
        print(f"[{case_id}] {engine} {title} ...", flush=True)
        result = run_case(case_id, engine, fixtures[fixture], removed, expectation, output_dir / args.label, ffmpeg, ffprobe)
        result.update({"title": title, "fixture": fixture})
        print(f"[{case_id}] {result['status']}: {result['summary']}", flush=True)
        results.append(result)

    payload = {
        "label": args.label,
        "git_head": _git(["rev-parse", "HEAD"]),
        "git_dirty_files": _git(["status", "--porcelain"]).splitlines(),
        "ffmpeg_version": efa.run([str(ffmpeg), "-version"]).stdout.splitlines()[0],
        "subprocess_timeout_seconds": SUBPROCESS_TIMEOUT_SECONDS,
        "results": results,
    }
    out_path = output_dir / f"{args.label}_results.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print(json.dumps(counts), out_path)
    return 0


def remeasure(output_dir: Path, label: str, ffmpeg, ffprobe) -> int:
    source = output_dir / f"{label}_results.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    rescored = []
    for old in payload["results"]:
        if old["outcome"] != "completed":
            rescored.append(old)
            continue
        output_path = next((output_dir / label / old["id"] / "out").iterdir())
        removed = [tuple(interval) for interval in old["removed"]]
        frames = efa.decode_frames(ffmpeg, ffprobe, output_path)
        result = _finish(old["id"], old["engine"], removed, old["expectation"], time.perf_counter(),
                         outcome="completed", seconds=old["seconds"], content=efa.removal_report(frames, removed),
                         av_sync=efa.av_sync(ffmpeg, output_path, frames),
                         durations=efa.stream_durations(ffprobe, output_path),
                         expected_duration=efa.expected_kept_duration(removed), details=old.get("details"),
                         leftovers=old.get("leftovers", []))
        result.update({"title": old["title"], "fixture": old["fixture"]})
        rescored.append(result)
        print(f"[{result['id']}] {result['status']}: {result['summary']}", flush=True)
    payload.update(results=rescored, remeasured_from=source.name)
    (output_dir / f"{label}_remeasured.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


def run_case(case_id, engine, fixture: Path, removed, expectation, work_dir: Path, ffmpeg, ffprobe) -> dict:
    case_dir = work_dir / case_id
    shutil.rmtree(case_dir, ignore_errors=True)
    output_dir, cache_dir = case_dir / "out", case_dir / "cache"
    output_dir.mkdir(parents=True)
    started = time.perf_counter()
    try:
        output_path, details = (_run_smart if engine == SMART else _run_fast)(fixture, removed, output_dir, cache_dir)
    except FFmpegTimeoutError as exc:
        return _finish(case_id, engine, removed, expectation, started, outcome="timeout",
                       error=str(exc), leftovers=_leftovers(output_dir, cache_dir))
    except subprocess.TimeoutExpired as exc:
        return _finish(case_id, engine, removed, expectation, started, outcome="timeout",
                       error=f"Subprocess exceeded {exc.timeout}s: {' '.join(map(str, exc.cmd))[:300]}",
                       leftovers=_leftovers(output_dir, cache_dir))
    except Exception as exc:  # noqa: BLE001 - product refusal or failure: recorded, never hidden
        return _finish(case_id, engine, removed, expectation, started, outcome="rejected",
                       error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-1500:],
                       leftovers=_leftovers(output_dir, cache_dir))
    seconds = round(time.perf_counter() - started, 3)
    frames = efa.decode_frames(ffmpeg, ffprobe, output_path)
    content = efa.removal_report(frames, removed)
    sync = efa.av_sync(ffmpeg, output_path, frames)
    durations = efa.stream_durations(ffprobe, output_path)
    return _finish(case_id, engine, removed, expectation, started, outcome="completed", seconds=seconds,
                   content=content, av_sync=sync, durations=durations,
                   expected_duration=efa.expected_kept_duration(removed), details=details,
                   leftovers=_leftovers(output_dir, cache_dir, exclude=output_path))


def _run_smart(fixture: Path, removed, output_dir: Path, cache_dir: Path):
    from services.export.smart_cutting_export_service import SmartCuttingExportService

    segments = [
        {"index": index, "requested_start_seconds": start, "requested_end_seconds": end}
        for index, (start, end) in enumerate(removed, start=1)
    ]
    runner = BoundedProcessRunner(stall_timeout_seconds=STALL_TIMEOUT_SECONDS)
    payload = SmartCuttingExportService(cache_dir=cache_dir, process_runner=runner).export(
        {"input_path": str(fixture), "output_dir": str(output_dir), "segments": segments,
         "export_mode": "remove_intervals"}
    )
    result = payload["result"]
    details = {
        "plan": [(s["type"], s["start_seconds"], s["end_seconds"]) for s in result["plan"]["segments"]],
        "ffmpeg_command_count": len(result["ffmpeg_commands"]),
        "video_fallbacks": result.get("video_fallbacks", "field absent"),
        "verification": result.get("verification", "field absent"),
    }
    return Path(result["merged_output_path"]), details


def _run_fast(fixture: Path, removed, output_dir: Path, cache_dir: Path):
    from schemas.video_cut_schema import VideoCutRequest
    from services.editing.cut_execution_service import CutExecutionService

    request = VideoCutRequest(
        input_path=fixture,
        output_dir=output_dir,
        export_mode="remove_intervals",
        segments=[
            {"index": index, "start_seconds": start, "end_seconds": end,
             "requested_start_seconds": start, "requested_end_seconds": end}
            for index, (start, end) in enumerate(removed, start=1)
        ],
    )
    runner = BoundedProcessRunner(stall_timeout_seconds=STALL_TIMEOUT_SECONDS)
    result = CutExecutionService(cache_dir=cache_dir, command_runner=runner, probe_runner=runner).export_segments(request)
    details = {
        "ffmpeg_command_count": len(result.ffmpeg_commands),
        "duration_warning": result.duration_warning,
        "app_expected_duration": result.expected_output_duration_seconds,
        "app_actual_duration": result.actual_output_duration_seconds,
    }
    return Path(result.merged_output_path), details


def _finish(case_id, engine, removed, expectation, started, *, outcome, **fields) -> dict:
    fields.setdefault("seconds", round(time.perf_counter() - started, 3))
    content = fields.get("content")
    sync = fields.get("av_sync") or {}
    problems = []
    if outcome == "completed":
        if not content["frame_exact"]:
            problems.append(
                f"leaked={content['leaked_removed_frames']} missing={content['missing_kept_frames']} "
                f"duplicates={content['duplicate_frames']} monotonic={content['monotonic']}"
            )
        if sync.get("audio") and (sync.get("max_abs_offset_ms") or 0) > 1000 / efa.FPS:
            problems.append(f"A/V offset up to {sync['max_abs_offset_ms']} ms")
        video = fields["durations"].get("video")
        if video is not None and abs(video - fields["expected_duration"]) > 1.5 / efa.FPS:
            problems.append(f"video duration {video}s vs {fields['expected_duration']}s")
        if expectation == "reject":
            problems.append("export completed although it must be refused")
        status = "FAIL" if problems else "PASS"
        summary = "; ".join(problems) or (
            f"frame-exact, {content['decoded_frames']} frames, max A/V offset "
            f"{sync.get('max_abs_offset_ms', 'n/a')} ms, {fields['seconds']} s"
        )
    elif outcome == "timeout":
        status = "FAIL" if expectation == "exact" else "TIMEOUT"
        summary = fields["error"]
    else:
        status = "FAIL" if expectation == "exact" else "REJECTED"
        summary = fields["error"][:300]
    if fields.get("leftovers"):
        summary += f" | leftover files: {len(fields['leftovers'])}"
    checks = {}
    if outcome == "completed":
        video = fields["durations"].get("video")
        checks = {
            "no_forbidden_frames": content["leaked_removed_frames"] == 0,
            "frame_exact": content["frame_exact"],
            "av_within_one_frame": (not sync.get("audio")) or (sync.get("max_abs_offset_ms") or 0) <= 1000 / efa.FPS,
            "video_duration_within_1_5_frames": video is not None
            and abs(video - fields["expected_duration"]) <= 1.5 / efa.FPS,
        }
    return {"id": case_id, "engine": engine, "removed": removed, "expectation": expectation,
            "outcome": outcome, "status": status, "summary": summary, "checks": checks, **fields}


def _leftovers(output_dir: Path, cache_dir: Path, exclude: Path | None = None) -> list[str]:
    found = []
    for root in (output_dir, cache_dir):
        if root.exists():
            found += [str(p) for p in root.rglob("*") if p.is_file() and p != exclude]
    return found


def _install_subprocess_timeout(seconds: float) -> None:
    original = subprocess.run

    @functools.wraps(original)
    def run_with_timeout(*args, **kwargs):
        kwargs.setdefault("timeout", seconds)
        return original(*args, **kwargs)

    subprocess.run = run_with_timeout


def _git(args: list[str]) -> str:
    return subprocess.run(["git", "-C", str(PROJECT_ROOT), *args], capture_output=True, text=True,
                          timeout=30, check=False).stdout.strip()


if __name__ == "__main__":
    sys.exit(main())
