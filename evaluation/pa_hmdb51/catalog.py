"""Catalogue of PA-HMDB51 videos with semi-nudity (nudity level 2) across all actions (annotations only).

Level 2 means "semi-nudity with half-naked body" (TPAMI Table 1). It is NOT an NSFW reference label:
a bare male torso or swimwear is 'absent' under the project guide. The catalogue only describes where
those annotations are and checks that the videos exist in the HMDB51 archives; seconds are frames / 30
(HMDB51 clips are 30 fps) until the media are prepared and their real timelines measured.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from evaluation.pa_hmdb51 import annotations as pa
from evaluation.pa_hmdb51.prepare import UNRAR_DEFAULT, list_archive

NOMINAL_FPS = 30


def catalog(dataset_dir: Path, output: Path, unrar: Path = UNRAR_DEFAULT):
    dataset_dir, output = Path(dataset_dir), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows, per_action = [], {}
    for path in sorted((dataset_dir / "PrivacyAttributes").glob("*.json")):
        action = path.stem
        videos = pa.load_action(path)
        archive = dataset_dir / f"{action}.rar"
        members = list_archive(unrar, archive) if archive.exists() else {}
        level2 = {name: v for name, v in videos.items() if v.max_nudity() == 2}
        per_action[action] = {"pa_annotated": len(videos), "nudity2_videos": len(level2),
                              "archive_present": archive.exists(),
                              "nudity2_in_archive": sum(name in members for name in level2),
                              "max_nudity_counts": {str(k): sum(v.max_nudity() == k for v in videos.values())
                                                    for k in (0, 1, 2)}}
        for name, video in sorted(level2.items()):
            frames = video.nudity_frames()
            annotated = video.annotated_frames("nudity")
            first, last = video.extent()
            segments = [s for s in video.attribute("nudity") if 2 in s.values]
            tags = pa.parse_hmdb_name(name, action)
            rows.append({
                "action": action, "file_name": name, "in_archive": name in members,
                "hmdb_source": tags["source"], "hmdb_body": tags.get("body"), "hmdb_people": tags.get("people"),
                "annotated_frames": annotated, "extent_frames": last - first + 1,
                "nudity2_frames": frames[2], "nudity2_fraction_of_annotated": round(frames[2] / annotated, 4),
                "nudity2_seconds_nominal": round(frames[2] / NOMINAL_FPS, 3),
                "nudity2_segments": ";".join(f"{s.first_frame}-{s.last_frame}" for s in segments),
                "first_nudity2_seconds_nominal": round(segments[0].first_frame / NOMINAL_FPS, 3),
                "whole_video_nudity2": frames[2] == annotated and len(segments) == 1,
                "gender_values": "|".join(sorted({str(v) for s in video.attribute("gender") for v in s.values})),
                "relationship_identifiable": any(1 in s.values for s in video.attribute("relationship")),
                "pa_review_flag": video.review, "issues": "; ".join(video.issues)})
    with (output / "pa_nudity2_catalog.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    durations = sorted(r["extent_frames"] / NOMINAL_FPS for r in rows)
    summary = {
        "warning": "PA-HMDB51 level 2 = half-naked body; not an NSFW label (see annotations.RELATION).",
        "pa_annotated_videos": sum(a["pa_annotated"] for a in per_action.values()),
        "nudity2_videos": len(rows), "nudity2_in_archives": sum(r["in_archive"] for r in rows),
        "actions_with_nudity2": sum(a["nudity2_videos"] > 0 for a in per_action.values()),
        "by_action": dict(sorted(per_action.items(), key=lambda kv: -kv[1]["nudity2_videos"])),
        "whole_video_nudity2": sum(r["whole_video_nudity2"] for r in rows),
        "gender_values": dict(Counter(r["gender_values"] for r in rows)),
        "relationship_identifiable": sum(r["relationship_identifiable"] for r in rows),
        "extent_seconds_nominal": {"min": durations[0], "median": durations[len(durations) // 2],
                                   "max": durations[-1]},
        "shorter_than_7_5_seconds": sum(d < 7.5 for d in durations),
        "sources": len({(r["action"], r["hmdb_source"]) for r in rows})}
    (output / "pa_nudity2_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
