"""Track 1 (technical / false-alert) manifest builder for Charades, from its annotation CSVs only.

Charades annotates household actions, not nudity: every selected video is labelled "missing"
(presumed negative, unverified) until a project reviewer verifies it. The subject (crowd actor)
is the independence group. Selection is deterministic: sha256(seed|video id) order inside each
stratum, with a per-subject cap so a few prolific actors cannot dominate the sample.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path

LICENSE_URL = "https://ai2-public-datasets.s3-us-west-2.amazonaws.com/charades/Charades.zip"
LICENSE_STATEMENT = ("license.txt (Charades.zip): License for Non-Commercial Use; academic, non-profit or "
                     "government-sponsored researchers, may also be used for evaluation purposes; no public "
                     "release or third-party distribution of the data.")
# Actions that put clothing, beds, bathrooms or mirrors in frame: realistic hard negatives.
HARD_ACTION = re.compile(r"cloth|dress|undress|towel|shoe|blanket|pillow|bed|mirror|lying|snuggl", re.I)
HARD_SCENES = {"Bedroom", "Bathroom"}


def read_annotations(zip_path: Path):
    with zipfile.ZipFile(zip_path) as archive:
        classes = dict(line.split(" ", 1) for line in archive.read("Charades/Charades_v1_classes.txt")
                       .decode("utf-8").splitlines() if line.strip())
        rows = []
        for split in ("train", "test"):
            text = archive.read(f"Charades/Charades_v1_{split}.csv").decode("utf-8")
            rows += [{**row, "charades_split": split} for row in csv.DictReader(io.StringIO(text))]
    return classes, rows


def is_hard(row, classes) -> bool:
    codes = [action.split()[0] for action in row["actions"].split(";") if action.strip()]
    return row["scene"] in HARD_SCENES or any(HARD_ACTION.search(classes.get(code, "")) for code in codes)


def select(rows, classes, *, total: int, hard_fraction: float, per_subject_cap: int, seed: str):
    if not 0 <= hard_fraction <= 1 or total <= 0 or per_subject_cap <= 0:
        raise ValueError("invalid selection parameters")
    rank = lambda row: hashlib.sha256(f"{seed}|{row['id']}".encode()).hexdigest()  # noqa: E731
    strata = {"hard": [], "ordinary": []}
    for row in sorted(rows, key=rank):
        strata["hard" if is_hard(row, classes) else "ordinary"].append(row)
    targets = {"hard": round(total * hard_fraction)}
    targets["ordinary"] = total - targets["hard"]
    per_subject, chosen = {}, []
    for name in ("hard", "ordinary"):
        taken = 0
        for row in strata[name]:
            if taken == targets[name]:
                break
            if per_subject.get(row["subject"], 0) >= per_subject_cap:
                continue
            per_subject[row["subject"]] = per_subject.get(row["subject"], 0) + 1
            chosen.append({**row, "stratum": name})
            taken += 1
        if taken < targets[name]:
            raise ValueError(f"only {taken} {name} videos available under the per-subject cap")
    return chosen


def build_manifest(zip_path: Path, *, total: int, hard_fraction: float = 0.5, per_subject_cap: int = 5,
                   seed: str = "nsfw-cutter/charades/track1/v1", retrieved: str = "2026-10-19"):
    classes, rows = read_annotations(zip_path)
    chosen = select(rows, classes, total=total, hard_fraction=hard_fraction,
                    per_subject_cap=per_subject_cap, seed=seed)
    unknown = {"nudity": "unknown", "sexual_activity": "unknown", "sexual_context": "unknown"}
    return {
        "schema_version": 1, "benchmark_id": f"charades_track1_{total}", "track": "technical",
        "dataset": {"dataset_id": "charades_v1", "name": "Charades (Hollywood in Homes)",
                    "publisher": "Allen Institute for AI", "homepage": "https://arxiv.org/abs/1604.01753",
                    "version": "v1 (480p release)", "license_id": "Charades Non-Commercial Use License",
                    "license_evidence": [{"url": LICENSE_URL, "retrieved": retrieved, "statement": LICENSE_STATEMENT}],
                    "access": "ungated", "permitted_use": "non-commercial academic research and evaluation",
                    "redistribution_allowed": False, "content": "real"},
        "annotation": {"version": "0-unverified", "source": "dataset_human",
                       "guideline": "Charades action annotations only; NSFW negatives require project review",
                       "notes": f"seed={seed}; per_subject_cap={per_subject_cap}; hard_fraction={hard_fraction}"},
        "items": [{"item_id": f"charades_{row['id']}", "group_id": f"subject_{row['subject']}", "split": "test",
                   "file_name": f"{row['id']}.mp4", "video_label": "missing", "category_labels": unknown,
                   "provenance": {"charades_id": row["id"], "charades_split": row["charades_split"],
                                  "scene": row["scene"], "stratum": row["stratum"],
                                  "annotated_length_seconds": row["length"]}}
                  for row in chosen],
    }
