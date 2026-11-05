"""The artifact check ignores the GitHub runner home only inside the known third-party binary."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_windows_artifact", ROOT / "scripts" / "verify_windows_artifact.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

RUNNER_HOME = verify.RUNNER_DEFAULT_HOME
ALLOWED = "_internal/hf_xet/hf_xet.pyd"


def _write(app_dir: Path, relative: str, content: bytes) -> None:
    target = app_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def test_runner_home_is_accepted_in_the_listed_third_party_binary(tmp_path):
    _write(tmp_path, ALLOWED, b"\x00panic at " + RUNNER_HOME.encode() + b"\\.cargo\\registry\x00")
    verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME])


def test_runner_home_is_still_rejected_in_any_other_file(tmp_path):
    _write(tmp_path, "_internal/other/module.pyd", RUNNER_HOME.encode())
    with pytest.raises(RuntimeError, match="Developer path"):
        verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME])


def test_other_developer_paths_are_still_rejected_in_the_listed_binary(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write(tmp_path, ALLOWED, RUNNER_HOME.encode() + b"|" + str(project_root).encode())
    with pytest.raises(RuntimeError, match="Developer path"):
        verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME, str(project_root)])
