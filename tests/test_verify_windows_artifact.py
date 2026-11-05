"""The artifact check ignores the GitHub runner home only inside compiled third-party extensions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify_windows_artifact", ROOT / "scripts" / "verify_windows_artifact.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

RUNNER_HOME = verify.RUNNER_DEFAULT_HOME


def _write(app_dir: Path, relative: str, content: bytes) -> None:
    target = app_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


@pytest.mark.parametrize(
    "relative",
    ["_internal/hf_xet/hf_xet.pyd", "_internal/ormsgpack/ormsgpack.cp312-win_amd64.pyd", "_internal/a/b/Ext.PYD"],
)
def test_runner_home_is_accepted_in_compiled_third_party_extensions(tmp_path, relative):
    _write(tmp_path, relative, b"\x00panic at " + RUNNER_HOME.encode() + b"\\.cargo\\registry\x00")
    verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME])


@pytest.mark.parametrize(
    "relative",
    ["_internal/pkg/module.py", "_internal/pkg/data.json", "_internal/pkg/lib.dll", "VideoCutter.exe", "extension.pyd"],
)
def test_runner_home_is_still_rejected_in_every_other_file(tmp_path, relative):
    _write(tmp_path, relative, RUNNER_HOME.encode())
    with pytest.raises(RuntimeError, match="Developer path"):
        verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME])


def test_every_offending_file_is_reported_in_one_error(tmp_path):
    for name in ("one.json", "two.json", "three.json"):
        _write(tmp_path, f"_internal/pkg/{name}", RUNNER_HOME.encode())
    _write(tmp_path, "_internal/pkg/clean.json", b"nothing to see")
    with pytest.raises(RuntimeError, match=r"3 artifact file\(s\)") as error:
        verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME])
    for name in ("one.json", "two.json", "three.json"):
        assert name in str(error.value)
    assert "clean.json" not in str(error.value)


def test_other_developer_paths_are_still_rejected_in_a_compiled_extension(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write(tmp_path, "_internal/hf_xet/hf_xet.pyd", RUNNER_HOME.encode() + b"|" + str(project_root).encode())
    with pytest.raises(RuntimeError, match="Developer path"):
        verify.verify_no_developer_paths(tmp_path, [RUNNER_HOME, str(project_root)])
