"""Corpus preparation: inspect HMDB51 archives, extract selected AVIs, convert, verify, write manifests.

NSFW Cutter accepts only MP4 and MKV (services/media/validation_service.py), so each AVI is converted
once. A stream copy is not usable: the DivX "packed B-frame" AVIs carry no packet timestamps, a plain
copy is refused by the Matroska muxer, and a copy with generated timestamps (-fflags +genpts) keeps
identical packets but gives two frames the same timestamp, so ordinary timestamp handling drops a
frame (observed on 2026-10-22). Each AVI is therefore encoded with mathematically lossless H.264
(libx264 -qp 0, yuv420p like the source) with timestamps set to frame_index / fps. Every conversion is
verified and recorded:
  - extraction: CRC32 and size of each extracted AVI equal to those stored in the RAR archive;
  - decoded frames: same count and identical per-frame MD5 (FFmpeg framemd5, every decoded frame) for
    the AVI and the MKV, and no frame lost when the MKV is decoded with default timestamp handling;
  - timeline: the presentation time of every MKV frame (kept in the record) is frame_index / fps within
    the 1 ms Matroska resolution; annotation frame indices are converted to seconds with these times.
A video that fails a check is reported and excluded from the manifests.

Original archives and annotations are only read. Media are written under --media-root (keep it
outside Git); the deliverable directory receives tables and manifests only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import zlib
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from evaluation.benchmark.atomic import write_atomic
from evaluation.benchmark.manifest import BenchmarkManifest, manifest_digest
from evaluation.pa_hmdb51 import annotations as pa
from evaluation.pilot.manifest import file_digest

ROOT = Path(__file__).resolve().parents[2]
FFMPEG_BIN = ROOT / "vendor" / "ffmpeg" / "bin"
UNRAR_DEFAULT = Path(r"C:\Program Files\WinRAR\UnRAR.exe")
ACTIONS_DEFAULT = ("kiss", "dive")
TRANSFORMATION = ("ffmpeg -nostdin -i <original.avi> -map 0:v:0 -fps_mode passthrough -vf setpts=N/(<fps>*TB) "
                  "-c:v libx264 -qp 0 -preset veryfast -pix_fmt yuv420p <evaluated.mkv>")
TIMELINE_TOLERANCE_SECONDS = 0.0011
PA_LICENSE_URL = "https://github.com/VITA-Group/PA-HMDB51/blob/master/LICENSE"
HMDB_URL = "https://serre-lab.clps.brown.edu/resource/hmdb-a-large-human-motion-database/"


def _run(command, timeout=600):
    return subprocess.run([str(c) for c in command], check=True, capture_output=True, text=True, timeout=timeout)


def safe_id(text: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_.-" else "-" for c in text)
    return cleaned.lstrip("_.-") or "x"


def item_id_for(action: str, file_name: str) -> str:
    stem = safe_id(Path(file_name).stem)
    digest = hashlib.sha256(file_name.encode()).hexdigest()[:6]
    return f"{stem[:110]}-{digest}"


# --------------------------------------------------------------------------- archives

def list_archive(unrar: Path, archive: Path) -> dict[str, dict]:
    """{bare .avi member name: {"size", "crc32"}} (the HMDB51 RARs hold one <action>/ folder)."""
    members, current = {}, None
    for line in _run([unrar, "lt", archive]).stdout.splitlines():
        key, _, value = line.strip().partition(": ")
        if key == "Name":
            name = value.replace("\\", "/").split("/")[-1]
            current = name if name.lower().endswith(".avi") else None
            if current:
                members[current] = {}
        elif current and key == "Size":
            members[current]["size"] = int(value)
        elif current and key == "CRC32":
            members[current]["crc32"] = value.lower()
    return dict(sorted(members.items()))


def crc32(path: Path) -> str:
    value = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value = zlib.crc32(block, value)
    return f"{value:08x}"


def extract(unrar: Path, archive: Path, action: str, members: list[str], destination: Path):
    """Extracts only the listed members, never overwriting an existing file (-o-)."""
    destination.mkdir(parents=True, exist_ok=True)
    pending = [m for m in members if not (destination / m).exists()]
    for start in range(0, len(pending), 40):  # bounded command lines
        chunk = [f"{action}\\{m}" for m in pending[start:start + 40]]
        _run([unrar, "e", "-o-", "-y", "-idq", archive, *chunk, str(destination) + "\\"])
    missing = [m for m in members if not (destination / m).is_file()]
    if missing:
        raise RuntimeError(f"{archive.name}: not extracted: {missing[:5]}")


# --------------------------------------------------------------------------- media checks

def probe(path: Path) -> dict:
    return json.loads(_run([FFMPEG_BIN / "ffprobe.exe", "-v", "error", "-show_format", "-show_streams",
                            "-of", "json", path]).stdout)


def decoded_frames(path: Path, fps_mode: str = "passthrough"):
    """[(presentation_seconds, md5)] of the first video stream. "passthrough" lists every decoded frame;
    "auto" is FFmpeg's default timestamp handling, which may drop or duplicate frames."""
    out = _run([FFMPEG_BIN / "ffmpeg.exe", "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0",
                "-fps_mode", fps_mode, "-f", "framemd5", "-"]).stdout
    time_base, frames = None, []
    for line in out.splitlines():
        if line.startswith("#tb 0:"):
            time_base = Fraction(line.split(":", 1)[1].strip())
        elif line and not line.startswith("#"):
            fields = [f.strip() for f in line.split(",")]
            frames.append((int(fields[2]), fields[5]))
    if time_base is None:
        raise ValueError(f"{path.name}: no time base in framemd5 output")
    return [(float(pts * time_base), md5) for pts, md5 in frames]


def convert_lossless(source: Path, target: Path, fps: Fraction):
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _run([FFMPEG_BIN / "ffmpeg.exe", "-nostdin", "-v", "error", "-n", "-i", source, "-map", "0:v:0",
          "-fps_mode", "passthrough", "-vf", f"setpts=N/({fps.numerator}/{fps.denominator}*TB)",
          "-c:v", "libx264", "-qp", "0", "-preset", "veryfast", "-pix_fmt", "yuv420p", target])


def app_validation(path: Path) -> str:
    """Result of the application's own loading check (services/media/media_validation.py)."""
    from services.media.media_validation import MediaValidationError, validate_media_file
    try:
        validate_media_file(path, ffprobe_path=FFMPEG_BIN / "ffprobe.exe")
        return "accepted"
    except MediaValidationError as exc:
        return f"rejected:{exc.category}:{exc.message_code}"


def _stream_info(payload: dict) -> dict:
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"container": payload.get("format", {}).get("format_name"),
            "duration_seconds": float(payload.get("format", {}).get("duration") or 0) or None,
            "video_codec": video.get("codec_name"), "codec_profile": video.get("profile"),
            "codec_tag": video.get("codec_tag_string"), "pix_fmt": video.get("pix_fmt"),
            "width": video.get("width"), "height": video.get("height"),
            "r_frame_rate": video.get("r_frame_rate"), "avg_frame_rate": video.get("avg_frame_rate"),
            "nb_frames_header": video.get("nb_frames"), "divx_packed": video.get("divx_packed"),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams),
            "stream_types": [s.get("codec_type") for s in streams]}


def prepare_video(original: Path, evaluated: Path, archive_entry: dict) -> dict:
    """Converts (if not already done) and verifies one video; returns its preparation record."""
    problems = []
    extracted_crc = crc32(original)
    if extracted_crc != archive_entry.get("crc32") or original.stat().st_size != archive_entry.get("size"):
        problems.append("extraction_crc_or_size_mismatch")
    source_info = _stream_info(probe(original))
    fps = Fraction(source_info["r_frame_rate"] or "0/1")
    if not fps or source_info["avg_frame_rate"] != source_info["r_frame_rate"]:
        problems.append("source_frame_rate_not_constant")
    source_frames = decoded_frames(original)
    if not evaluated.exists() and fps:
        convert_lossless(original, evaluated, fps)
    target_info = _stream_info(probe(evaluated))
    target_frames = decoded_frames(evaluated)
    default_decode = decoded_frames(evaluated, "auto")
    frames_identical = bool(source_frames) and [m for _, m in source_frames] == [m for _, m in target_frames]
    default_identical = [m for _, m in default_decode] == [m for _, m in target_frames]
    times = [t for t, _ in target_frames]
    deviation = max((abs(t - float(i / fps)) for i, t in enumerate(times)), default=None) if fps else None
    if not frames_identical:
        problems.append("decoded_frames_differ")
    if not default_identical:
        problems.append("default_decode_drops_or_duplicates_frames")
    if deviation is None or deviation > TIMELINE_TOLERANCE_SECONDS:
        problems.append("timeline_not_frame_index_over_fps")
    return {"archive_entry": {**archive_entry, "extracted_crc32": extracted_crc},
            "original": {"sha256": file_digest(original), "bytes": original.stat().st_size, **source_info,
                         "decoded_frames": len(source_frames)},
            "evaluated": {"sha256": file_digest(evaluated), "bytes": evaluated.stat().st_size, **target_info,
                          "decoded_frames": len(target_frames), "app_validation": app_validation(evaluated)},
            "transformation": {"operation": "lossless_h264_avi_to_mkv", "command": TRANSFORMATION,
                               "fps": str(fps), "re_encoded": True, "lossless": True,
                               "decoded_frames_identical": frames_identical,
                               "default_decode_identical": default_identical,
                               "max_timeline_deviation_seconds": deviation,
                               "decoded_md5_sequence_sha256": hashlib.sha256(
                                   "".join(m for _, m in target_frames).encode()).hexdigest(),
                               "rejected_alternative": "stream copy with -fflags +genpts: duplicate frame timestamps"},
            "frame_times_seconds": times, "problems": problems}


# --------------------------------------------------------------------------- annotations in seconds

def segment_seconds(segment: pa.Segment, frame_times: list[float], frame_duration: float):
    """[start, end) seconds of an inclusive frame range, from decoded presentation times."""
    if segment.last_frame >= len(frame_times):
        return None, None
    return frame_times[segment.first_frame], frame_times[segment.last_frame] + frame_duration


def mapping_rows(item_id: str, action: str, annotation: pa.VideoAnnotation, frame_times, frame_duration):
    rows = []
    for segment in annotation.segments:
        start, end = segment_seconds(segment, frame_times, frame_duration)
        for value in segment.values:
            usability, note = pa.relation(segment.attribute, value)
            rows.append({"item_id": item_id, "action": action, "original_file_name": annotation.file_name,
                         "attribute": segment.attribute, "first_frame": segment.first_frame,
                         "last_frame": segment.last_frame, "frames": segment.frames,
                         "start_seconds": None if start is None else round(start, 4),
                         "end_seconds": None if end is None else round(end, 4),
                         "value": value, "coexisting_values": "|".join(map(str, segment.values)),
                         "official_meaning": pa.MEANING.get(segment.attribute, {}).get(value, "undefined"),
                         "nsfw_usability": usability, "relation_to_nsfw_categories": note,
                         "pa_review_flag": annotation.review,
                         "within_decoded_frames": start is not None})
    return rows


# --------------------------------------------------------------------------- manifests

def dataset_info(retrieved: str) -> dict:
    return {"dataset_id": "pa_hmdb51", "name": "PA-HMDB51 privacy attributes on HMDB51 videos",
            "publisher": "VITA Group (annotations); Serre Lab, Brown University (HMDB51 videos)",
            "homepage": "https://github.com/VITA-Group/PA-HMDB51",
            "version": "PrivacyAttributes JSON (local copy) on hmdb51_org RAR archives (2011-08-25)",
            "license_id": "PA-HMDB51 non-commercial research notice; HMDB51 licence not verified",
            "license_evidence": [
                {"url": PA_LICENSE_URL, "retrieved": retrieved,
                 "statement": "Made available to the scientific community for non-commercial research purposes; "
                              "no commercial use; cite Wu et al. (arXiv:1906.05675); derivatives must be marked."},
                {"url": HMDB_URL, "retrieved": retrieved,
                 "statement": "Official page is script-rendered; its licence text could not be read on the "
                              "retrieval date. Treat HMDB51 clips (excerpts of films and web videos) as "
                              "third-party material: local research use only, no redistribution."}],
            "access": "ungated", "permitted_use": "non-commercial academic research and evaluation",
            "redistribution_allowed": False, "content": "real"}


def manifest(benchmark_id: str, items: list[dict], retrieved: str, note: str) -> dict:
    unknown = {c: "unknown" for c in ("nudity", "sexual_activity", "sexual_context")}
    data = {"schema_version": 1, "benchmark_id": benchmark_id, "track": "accuracy",
            "dataset": dataset_info(retrieved),
            "annotation": {"version": "0-unreviewed", "source": "dataset_human",
                           "guideline": "No NSFW reference labels. PA-HMDB51 privacy attributes are kept in "
                                        "provenance only; NSFW labels require project review "
                                        "(docs/nsfw_annotation_guide.md).",
                           "notes": note},
            "items": [{"item_id": row["item_id"], "group_id": row["group_id"], "split": "test",
                       "file_name": row["evaluated_file"], "sha256": row["evaluated_sha256"],
                       "duration_seconds": row["evaluated_duration_seconds"], "has_audio": row["has_audio"],
                       "video_label": "missing", "category_labels": unknown,
                       "provenance": {k: row[k] for k in (
                           "action", "original_file_name", "original_sha256", "subset", "pa_annotated",
                           "pa_max_nudity", "pa_nudity_frames_2", "pa_review_flag", "hmdb_source")}}
                      for row in items]}
    validated = BenchmarkManifest.model_validate(data)
    return {**validated.model_dump(mode="json")}, manifest_digest(validated)


MANIFEST_COLUMNS = (
    "item_id", "action", "subset", "original_file_name", "archive", "group_id", "hmdb_source", "hmdb_body",
    "hmdb_camera", "hmdb_people", "hmdb_viewpoint", "hmdb_quality", "hmdb_clip",
    "pa_annotated", "pa_review_flag", "pa_note", "pa_annotation_issues", "pa_annotated_frames_range",
    "pa_max_nudity", "pa_nudity_frames_0", "pa_nudity_frames_1", "pa_nudity_frames_2",
    "pa_relationship_identifiable_frames", "pa_gender_values", "pa_face_max",
    "original_sha256", "original_bytes", "original_container", "video_codec", "codec_tag", "divx_packed",
    "width", "height", "r_frame_rate", "avg_frame_rate", "original_duration_seconds", "decoded_frames",
    "has_audio", "transformation", "re_encoded", "lossless", "extraction_crc32_ok", "decoded_frames_identical",
    "default_decode_identical", "max_timeline_deviation_seconds", "evaluated_codec", "evaluated_file", "evaluated_sha256", "evaluated_duration_seconds", "first_frame_seconds",
    "last_frame_seconds", "app_validation", "app_validation_results", "annotation_beyond_decoded_frames", "problems",
    "excluded")


REVALIDATIONS = 3


def validation_outcome(record_path: Path, evaluated: Path, first: str):
    """The application validator was once observed to reject a verified file and then accept it 10 times out
    of 10 (2026-10-22, cause unknown). A rejection is therefore re-checked REVALIDATIONS times; all results
    are kept (append-only) and only a consistent rejection excludes the video."""
    results = [first]
    if first != "accepted":
        path = record_path.with_name(record_path.stem + ".revalidation.json")
        if not path.exists():
            write_atomic(path, {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                "results": [app_validation(evaluated) for _ in range(REVALIDATIONS)]})
        results += json.loads(path.read_text(encoding="utf-8"))["results"]
    accepted = [r == "accepted" for r in results]
    return ("accepted" if all(accepted) else "intermittent" if any(accepted) else "rejected"), results


def _verified_record(record_path: Path, original: Path, evaluated: Path):
    """A stored verification is reused only while both media files still have its SHA-256."""
    if not (record_path.exists() and original.exists() and evaluated.exists()):
        return None
    stored = json.loads(record_path.read_text(encoding="utf-8"))
    if file_digest(original) != stored["original"]["sha256"] or file_digest(evaluated) != stored["evaluated"]["sha256"]:
        raise ValueError(f"{record_path.stem}: media changed since its verification; use a new media root")
    return stored


def _write_once(path: Path, value, *, compare):
    """Preparation is re-runnable: an existing record is kept only if it describes the same media."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, value)
    elif not compare(json.loads(path.read_text(encoding="utf-8"))):
        raise ValueError(f"{path.name} already exists with different content; use a new output directory")


def _write_csv(path: Path, rows: list[dict], columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


SCOPES = ("annotated", "all", "pa_nudity2")


def select_members(scope: str, members, annotated: dict) -> list[str]:
    """'all': every video of the action; 'annotated': PA-HMDB51 videos; 'pa_nudity2': PA-HMDB51 videos whose
    nudity reaches level 2 (a selection on a privacy attribute, never on an NSFW label or a prediction)."""
    if scope == "all":
        return list(members)
    chosen = set(members) & set(annotated)
    if scope == "pa_nudity2":
        chosen = {name for name in chosen if annotated[name].max_nudity() == 2}
    return sorted(chosen)


def prepare(dataset_dir: Path, media_root: Path, output: Path, *, actions=ACTIONS_DEFAULT, scope: str = "all",
            unrar: Path = UNRAR_DEFAULT, retrieved: str | None = None, action_scopes: dict | None = None,
            batch: str | None = None):
    """scope applies to every action unless action_scopes overrides it (values in SCOPES).

    Without batch, items are split into a 'pilot' (PA-HMDB51-annotated) and an 'extension' manifest (first
    kiss/dive campaign). With batch, one manifest pa_hmdb51_<batch> holds every prepared item and the subset
    column says whether the video is PA-HMDB51-annotated.
    """
    action_scopes = dict(action_scopes or {})
    if {scope, *action_scopes.values()} - set(SCOPES) or set(action_scopes) - set(actions):
        raise ValueError(f"scopes must be in {SCOPES} and overrides must name selected actions")
    retrieved = retrieved or datetime.now(UTC).strftime("%Y-%m-%d")
    dataset_dir, media_root, output = Path(dataset_dir), Path(media_root).resolve(), Path(output)
    if ROOT in media_root.parents and not media_root.is_relative_to(ROOT / "artifacts"):
        raise ValueError("media must stay outside versioned directories (use artifacts/ or another drive)")
    output.mkdir(parents=True, exist_ok=True)
    attributes_dir = dataset_dir / "PrivacyAttributes"
    archive_rows, manifest_rows, mapping, correspondences = [], [], [], []
    for action in actions:
        archive = dataset_dir / f"{action}.rar"
        members = list_archive(unrar, archive)
        annotated = pa.load_action(attributes_dir / f"{action}.json")
        archive_rows.append({"action": action, "archive": archive.name, "archive_sha256": file_digest(archive),
                             "archive_bytes": archive.stat().st_size, "avi_members": len(members),
                             "pa_annotated": len(annotated),
                             "pa_annotated_in_archive": len(set(annotated) & set(members)),
                             "annotation_json_sha256": file_digest(attributes_dir / f"{action}.json")})
        for name in sorted(set(annotated) - set(members)):
            correspondences.append({"action": action, "file_name": name, "issue": "annotated_but_not_in_archive"})
        for name in sorted(set(members) - set(annotated)):
            correspondences.append({"action": action, "file_name": name, "issue": "in_archive_without_pa_annotation"})
        selected = select_members(action_scopes.get(action, scope), members, annotated)
        originals = media_root / "originals" / action
        extract(unrar, archive, action, selected, originals)
        # Annotated videos first: they form the pilot.
        for name in sorted(selected, key=lambda n: (n not in annotated, n)):
            item_id = item_id_for(action, name)
            tags = pa.parse_hmdb_name(name, action)
            evaluated_rel = f"evaluated/{action}/{item_id}.mkv"
            record_path = media_root / "records" / f"{item_id}.json"
            if not record_path.exists() and (media_root / evaluated_rel).exists():
                # Converted output of an interrupted run, never verified (possibly truncated): redo it.
                (media_root / evaluated_rel).unlink()
            record = _verified_record(record_path, originals / name, media_root / evaluated_rel) or \
                prepare_video(originals / name, media_root / evaluated_rel, members[name])
            record.update(item_id=item_id, action=action, original_file_name=name, evaluated_file=evaluated_rel)
            fps = Fraction(record["evaluated"]["r_frame_rate"] or "0/1")
            frame_duration = float(1 / fps) if fps else 0.0
            note = annotated.get(name)
            beyond = []
            if note is not None:
                rows = mapping_rows(item_id, action, note, record["frame_times_seconds"], frame_duration)
                mapping += rows
                beyond = sorted({r["attribute"] for r in rows if not r["within_decoded_frames"]})
                record["pa_annotation"] = {"segments": [s.__dict__ | {"values": list(s.values)} for s in note.segments],
                                           "review": note.review, "note": note.note, "issues": note.issues}
            _write_once(record_path, record, compare=lambda old: old["evaluated"]["sha256"] == record["evaluated"]["sha256"]
                        and old["original"]["sha256"] == record["original"]["sha256"])
            validation, validation_results = validation_outcome(record_path, media_root / evaluated_rel,
                                                                record["evaluated"]["app_validation"])
            nudity = note.nudity_frames() if note else {}
            relationship = sum(s.frames for s in note.attribute("relationship") if 1 in s.values) if note else None
            problems = record["problems"] + [f"annotation_beyond_decoded_frames:{a}" for a in beyond]
            times = record["frame_times_seconds"]
            manifest_rows.append({
                "item_id": item_id, "action": action,
                "subset": ("pa_annotated" if note else "not_pa_annotated") if batch else
                ("pilot" if note else "extension"),
                "original_file_name": name, "archive": archive.name,
                "group_id": "hmdb51-src-" + safe_id(tags["source"] or Path(name).stem)[:100],
                "hmdb_source": tags["source"], "hmdb_body": tags.get("body"), "hmdb_camera": tags.get("camera"),
                "hmdb_people": tags.get("people"), "hmdb_viewpoint": tags.get("viewpoint"),
                "hmdb_quality": tags.get("quality"), "hmdb_clip": tags.get("clip"),
                "pa_annotated": note is not None, "pa_review_flag": note.review if note else None,
                "pa_note": note.note if note else None,
                "pa_annotation_issues": "; ".join(note.issues) if note else None,
                "pa_annotated_frames_range": "%d-%d" % note.extent() if note else None,
                "pa_max_nudity": note.max_nudity() if note else None,
                "pa_nudity_frames_0": nudity.get(0), "pa_nudity_frames_1": nudity.get(1),
                "pa_nudity_frames_2": nudity.get(2), "pa_relationship_identifiable_frames": relationship,
                "pa_gender_values": "|".join(sorted({str(v) for s in note.attribute("gender") for v in s.values}))
                if note else None,
                "pa_face_max": max((v for s in note.attribute("face") for v in s.values), default=None) if note else None,
                "original_sha256": record["original"]["sha256"], "original_bytes": record["original"]["bytes"],
                "original_container": record["original"]["container"], "video_codec": record["original"]["video_codec"],
                "codec_tag": record["original"]["codec_tag"], "divx_packed": record["original"]["divx_packed"],
                "width": record["original"]["width"], "height": record["original"]["height"],
                "r_frame_rate": record["original"]["r_frame_rate"], "avg_frame_rate": record["original"]["avg_frame_rate"],
                "original_duration_seconds": record["original"]["duration_seconds"],
                "decoded_frames": record["original"]["decoded_frames"], "has_audio": record["original"]["has_audio"],
                "transformation": record["transformation"]["operation"], "re_encoded": True, "lossless": True,
                "extraction_crc32_ok": "extraction_crc_or_size_mismatch" not in record["problems"],
                "decoded_frames_identical": record["transformation"]["decoded_frames_identical"],
                "default_decode_identical": record["transformation"]["default_decode_identical"],
                "max_timeline_deviation_seconds": record["transformation"]["max_timeline_deviation_seconds"],
                "evaluated_codec": "%s (%s)" % (record["evaluated"]["video_codec"], record["evaluated"]["codec_profile"]),
                "evaluated_file": evaluated_rel, "evaluated_sha256": record["evaluated"]["sha256"],
                "evaluated_duration_seconds": record["evaluated"]["duration_seconds"],
                "first_frame_seconds": round(times[0], 4) if times else None,
                "last_frame_seconds": round(times[-1], 4) if times else None,
                "app_validation": validation, "app_validation_results": "|".join(validation_results),
                "annotation_beyond_decoded_frames": "|".join(beyond), "problems": "; ".join(problems),
                "excluded": bool(problems) or validation == "rejected"})
    _write_csv(output / "dataset_manifest.csv", manifest_rows, MANIFEST_COLUMNS)
    _write_csv(output / "annotation_mapping.csv", mapping, list(mapping[0]) if mapping else ["item_id"])
    _write_csv(output / "correspondence_issues.csv", correspondences, ("action", "file_name", "issue"))
    manifests = {}
    selection = f"scope={scope}; overrides={action_scopes}; actions={','.join(actions)}"
    groups = {batch: [r for r in manifest_rows if not r["excluded"]]} if batch else {
        subset: [r for r in manifest_rows if r["subset"] == subset and not r["excluded"]]
        for subset in ("pilot", "extension")}
    for subset, rows in groups.items():
        if rows:
            name = f"pa_hmdb51_{batch}" if batch else f"pa_hmdb51_{'_'.join(actions)}_{subset}"
            data, digest = manifest(name, rows, retrieved,
                                    f"subset={subset}; {selection}; conversion={TRANSFORMATION}")
            _write_once(output / f"{name}.manifest.json", data,
                        compare=lambda old: manifest_digest(BenchmarkManifest.model_validate(old)) == digest)
            manifests[subset] = {"path": str(output / f"{name}.manifest.json"), "digest": digest, "items": len(rows)}
    summary = {"prepared_at": datetime.now(UTC).isoformat(timespec="seconds"), "scope": scope,
               "action_scopes": action_scopes, "batch": batch,
               "actions": list(actions), "archives": archive_rows, "media_root": str(media_root),
               "videos_prepared": len(manifest_rows),
               "videos_excluded": sum(r["excluded"] for r in manifest_rows),
               "pa_inventory_all_actions": pa.inventory(attributes_dir), "manifests": manifests,
               "transformation": TRANSFORMATION}
    (output / "preparation_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    return summary
