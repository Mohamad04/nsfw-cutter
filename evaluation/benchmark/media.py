"""Evaluation-only input preparation and runtime parity helpers.

- A1 input: the original video stream copied without audio or subtitle streams. Refused unless the
  video packets (count, payload hash, PTS) are identical to the source; never re-encoded.
- Whisper parity: source runs load CTranslate2 from the virtual environment, which lacks CUDA 12
  cuBLAS. The packaged application bundles the pinned cuBLAS 12.8.4.1 beside ctranslate2.dll, whose
  package preloads it by full path. This helper verifies the same vendor files and preloads them by
  full path in the evaluation process only; CTranslate2's later load by name reuses those modules.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PTS_TOLERANCE_SECONDS = 0.002


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_packets(path: Path, ffprobe: Path):
    raw = json.loads(subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-show_packets", "-show_data_hash", "sha256",
         "-of", "json", str(path)], check=True, capture_output=True, text=True, timeout=600).stdout)
    streams = raw.get("streams", [])
    video = [s["index"] for s in streams if s.get("codec_type") == "video"]
    return {"stream_types": [s.get("codec_type") for s in streams],
            "video_codecs": [s.get("codec_name") for s in streams if s.get("codec_type") == "video"],
            "video_packets": [[(p.get("pts_time"), p.get("data_hash")) for p in raw.get("packets", [])
                               if p.get("stream_index") == index] for index in video]}


def verify_video_only_copy(source_probe, target_probe):
    if set(target_probe["stream_types"]) != {"video"}:
        raise ValueError("A1 input still contains non-video streams")
    if source_probe["video_codecs"] != target_probe["video_codecs"]:
        raise ValueError("A1 input changed the video codec")
    for before, after in zip(source_probe["video_packets"], target_probe["video_packets"], strict=True):
        if not before or len(before) != len(after):
            raise ValueError("A1 input changed the number of video packets")
        for (pts_a, hash_a), (pts_b, hash_b) in zip(before, after):
            if not hash_a or hash_a != hash_b:
                raise ValueError("A1 input changed a video packet payload")
            if pts_a is None or pts_b is None or abs(float(pts_a) - float(pts_b)) > PTS_TOLERANCE_SECONDS:
                raise ValueError("A1 input changed the video timeline")


def prepare_video_only_copy(source: Path, target: Path, *, ffmpeg: Path, ffprobe: Path):
    """Creates target (must not exist) and returns its identity record for VideoResult.input."""
    if target.exists():
        raise FileExistsError(target)
    subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-n", "-copyts", "-i", str(source),
                    "-map", "0:v", "-c", "copy", str(target)], check=True, capture_output=True, timeout=600)
    verify_video_only_copy(probe_packets(source, ffprobe), probe_packets(target, ffprobe))
    return {"sha256": _sha256(target), "derived_from_sha256": _sha256(source),
            "video_packets_verified_identical": True}


def enable_whisper_cuda12_cublas(project_root: Path = ROOT, *, loader=None):
    """Verify the pinned vendor cuBLAS 12 and preload it, by full path, in this process only.

    Must be called before CTranslate2 first needs cuBLAS. Returns the loaded module handles, which
    the caller keeps alive; the loaded paths should then be recorded in the run's environment.
    """
    pin = json.loads((project_root / "scripts" / "cuda12-cublas-pin.json").read_text(encoding="utf-8"))
    vendor = project_root / "vendor" / "cuda12-cublas"
    for name, binary in pin["binaries"].items():
        path = vendor / name
        if not path.is_file() or path.stat().st_size != binary["size"] or _sha256(path) != binary["sha256"]:
            raise ValueError(f"{name} is missing or is not the pinned cuBLAS {pin['version']}")
    if loader is None:
        if os.name != "nt":
            raise OSError("the pinned cuBLAS 12 DLLs are Windows binaries")
        import ctypes
        loader = ctypes.WinDLL
    # cublas64_12 imports cublasLt64_12 by name, so the dependency is loaded first.
    order = sorted(pin["binaries"], key=lambda name: name.lower() != "cublaslt64_12.dll")
    return [loader(str(vendor / name)) for name in order]
