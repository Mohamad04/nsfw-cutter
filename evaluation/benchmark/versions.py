"""Registry of frozen pipeline versions that campaigns may run (evaluation-only).

A campaign verifies before any inference that the analysis code (services/analysis, models, core) is
byte-identical to its version's commit, and records the version in campaign.json. A derived version names
its parent and the only analysis files allowed to differ from it, so a comparison between the two can be
attributed to that change alone. The effective configuration (evaluation/technical/frozen_config.json,
digest CONFIG_DIGEST) is shared: no version changes a model, threshold or sampling parameter.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIRS = ("services/analysis", "models", "core")
# Campaigns started before this registry (2026-10-22) do not record a version: they all ran this one. A campaign
# records its version whenever it is another one, so changing the default never changes a recorded identity.
UNRECORDED_PIPELINE_VERSION = "baseline-2399e95"
# Reference freeze used by new campaigns unless another registered version is requested explicitly.
DEFAULT_PIPELINE_VERSION = "reference-20261023-50b04b6"

PIPELINE_VERSIONS = {
    "baseline-2399e95": {
        "commit": "2399e950aeb33dd7925690c78d3f5f25d50d07cb",
        "parent": None,
        "changed_files": [],
        "description": "experimental freeze of 2026-10-19 (pilot, Charades and first PA-HMDB51 campaigns)",
    },
    "short-media-coverage-bfe55cc": {
        "commit": "bfe55cc0c7772a695269b97d1646f364e818c87e",
        "parent": "baseline-2399e95",
        "changed_files": ["services/analysis/visual_sampling.py"],
        "description": "baseline plus at least one sampled frame for media shorter than half a coarse period and "
                       "for end-of-stream candidate windows shorter than half a dense period",
    },
    "reference-20261023-50b04b6": {
        "commit": "50b04b63a5e73d69711b75777cf420e2343c9307",
        "parent": "short-media-coverage-bfe55cc",
        "changed_files": ["services/analysis/visual_sampling.py"],
        "description": "reference freeze of 2026-10-23, merged into feature/vlm-analysis-mvp: short-media coverage "
                       "after code review (final windows that start after the last frame keep the displayed frame; "
                       "cancellation is checked before any fallback)",
    },
}


def version(name: str) -> dict:
    if name not in PIPELINE_VERSIONS:
        raise ValueError(f"unknown pipeline version {name!r}; known: {', '.join(PIPELINE_VERSIONS)}")
    return {"name": name, **PIPELINE_VERSIONS[name]}


def verify_lineage(name: str, git=("git",)) -> dict:
    """A derived version may differ from its parent only in its declared analysis files."""
    entry = version(name)
    if entry["parent"] is None:
        return {"parent": None, "changed_files": []}
    parent = version(entry["parent"])
    changed = subprocess.run([*git, "diff", "--name-only", parent["commit"], entry["commit"], "--", *ANALYSIS_DIRS],
                             cwd=ROOT, check=True, capture_output=True, text=True).stdout.split()
    if sorted(changed) != sorted(entry["changed_files"]):
        raise ValueError(f"{name}: analysis changes {changed} differ from the declared {entry['changed_files']}")
    return {"parent": entry["parent"], "parent_commit": parent["commit"], "changed_files": changed}
