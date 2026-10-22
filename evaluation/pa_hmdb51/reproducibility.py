"""Run-to-run reproducibility of campaigns on the same manifest items (no model or media access).

Compares, item by item, the latest attempt of each campaign: status, errors, coarse frame timestamps,
Marqo probabilities, candidate windows, Qwen batch timestamps and final suggestions. Probabilities are
compared exactly and with a tolerance (GPU arithmetic is not guaranteed bitwise deterministic).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation.benchmark import runner

TOLERANCE = 1e-3


def _observations(directory: Path):
    found = {}
    for line in (directory / "observations.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("kind") in ("coarse_frames", "marqo_scores", "candidate_windows", "batch_plan"):
            found[entry["kind"]] = entry
    return found


def fingerprint(directory: Path):
    record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
    seen = _observations(directory)
    return {
        # FFmpeg messages embed a per-process memory address ("[out#0/image2 @ 000001971c832700]").
        "status": record["status"], "errors": [re.sub(r"@ [0-9a-fA-F]+\]", "@ <address>]", e) for e in record["errors"]],
        "coarse": [(f["timestamp_seconds"], f["origin"]) for f in seen.get("coarse_frames", {}).get("frames", [])],
        "marqo": [s["model_probability"] for s in seen.get("marqo_scores", {}).get("scores", [])],
        "windows": [(w["start_seconds"], w["end_seconds"]) for w in seen.get("candidate_windows", {}).get("windows", [])],
        "batches": [[f["timestamp_seconds"] for f in b["frames"]] for b in seen.get("batch_plan", {}).get("batches", [])],
        "suggestions": [(s["category"], s["start_seconds"], s["end_seconds"], s["final_confidence"], s["reason"])
                        for s in record["suggestions"]],
        "wall_seconds": json.loads((directory / "monitor_summary.json").read_text(encoding="utf-8"))["wall_seconds"]}


def compare(campaigns: list[Path], config: str = "A2"):
    runs = [{key[0]: dirs[-1] for key, dirs in runner._attempts(Path(c)).items() if key[1] == config}
            for c in campaigns]
    common = sorted(set.intersection(*(set(r) for r in runs)))
    items, summary = [], {"items_compared": len(common), "campaigns": [str(c) for c in campaigns]}
    checks = ("status", "errors", "coarse", "windows", "batches", "suggestions")
    for item in common:
        prints = [fingerprint(r[item]) for r in runs]
        row = {"item_id": item, **{f"same_{k}": all(p[k] == prints[0][k] for p in prints) for k in checks}}
        marqo = [p["marqo"] for p in prints]
        row["same_marqo_exact"] = all(m == marqo[0] for m in marqo)
        row["max_marqo_difference"] = max((abs(a - b) for m in marqo[1:] for a, b in zip(m, marqo[0])), default=0.0) \
            if all(len(m) == len(marqo[0]) for m in marqo) else None
        row["wall_seconds"] = [round(p["wall_seconds"], 2) for p in prints]
        items.append(row)
    for key in [f"same_{k}" for k in checks] + ["same_marqo_exact"]:
        summary[key] = sum(r[key] for r in items)
    differences = [r["max_marqo_difference"] for r in items if r["max_marqo_difference"] is not None]
    summary["max_marqo_difference"] = max(differences, default=None)
    summary["marqo_within_tolerance"] = sum(d <= TOLERANCE for d in differences)
    summary["tolerance"] = TOLERANCE
    return {"summary": summary, "items": items}
