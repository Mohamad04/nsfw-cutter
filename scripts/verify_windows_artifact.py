"""Validate a packaged NSFW Cutter Windows artifact before publication."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


MIB = 1024 * 1024
REQUIRED_QML_MODULES = (
    "QtQuick/qmldir",
    "QtQuick/Controls/qmldir",
    "QtQuick/Layouts/qmldir",
    "QtQuick/Window/qmldir",
    "QtMultimedia/qmldir",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--zip-path", type=Path, required=True)
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--max-installed-mib", type=float, default=1150)
    parser.add_argument("--max-archive-mib", type=float, default=450)
    parser.add_argument("--forbidden-path", action="append", default=[])
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    return path


def require_directory(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise RuntimeError(f"Missing {label}: {path}")
    return path


def first_existing(candidates: list[Path], label: str) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    checked = "\n - ".join(str(path) for path in candidates)
    raise RuntimeError(f"Missing {label}. Checked:\n - {checked}")


def run_version_check(executable: Path) -> None:
    completed = subprocess.run(
        [str(executable), "-version"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Version check failed for {executable}: {details}")


def find_bytes(path: Path, patterns: list[bytes]) -> bytes | None:
    patterns = [pattern for pattern in patterns if pattern]
    if not patterns:
        return None
    overlap = max(len(pattern) for pattern in patterns) - 1
    carry = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = carry + chunk
            for pattern in patterns:
                if pattern in data:
                    return pattern
            carry = data[-overlap:] if overlap > 0 else b""
    return None


def forbidden_patterns(values: list[str]) -> list[bytes]:
    variants: set[str] = set()
    for value in values:
        if not value:
            continue
        normalized = str(Path(value).resolve())
        variants.add(normalized)
        variants.add(normalized.replace("\\", "/"))
        variants.add("file:///" + normalized.replace("\\", "/"))
        variants.add(normalized.lower())
        variants.add(normalized.replace("\\", "/").lower())
        variants.add(normalized.upper())
        variants.add(normalized.replace("\\", "/").upper())

    encoded: list[bytes] = []
    for value in sorted(variants):
        encoded.extend((value.encode("utf-8"), value.encode("utf-16-le")))
    return encoded


def verify_no_developer_paths(app_dir: Path, values: list[str]) -> None:
    patterns = forbidden_patterns(values)
    for file_path in app_dir.rglob("*"):
        if not file_path.is_file():
            continue
        match = find_bytes(file_path, patterns)
        if match is not None:
            raise RuntimeError(
                f"Developer path found in artifact file {file_path}: "
                f"{match.decode('utf-8', errors='ignore')!r}"
            )


def verify_zip(zip_path: Path, app_dir: Path) -> None:
    require_file(zip_path, "release ZIP")
    root_prefix = f"{app_dir.name}/"
    expected_entries = {
        root_prefix + path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*")
        if path.is_file()
    }
    with zipfile.ZipFile(zip_path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"Release ZIP contains a corrupt member: {bad_member}")

        file_names = [
            entry.filename.replace("\\", "/")
            for entry in archive.infolist()
            if not entry.is_dir()
        ]
        if not file_names:
            raise RuntimeError("Release ZIP is empty.")
        if len(file_names) != len(set(file_names)):
            raise RuntimeError("Release ZIP contains duplicate file entries.")
        actual_entries = set(file_names)
        invalid = [name for name in actual_entries if not name.startswith(root_prefix)]
        if invalid:
            raise RuntimeError(
                f"Release ZIP must contain only the {app_dir.name}/ root; found {invalid[0]!r}."
            )
        unsafe = [
            name
            for name in actual_entries
            if name.startswith("/") or ".." in Path(name).parts
        ]
        if unsafe:
            raise RuntimeError(f"Release ZIP contains an unsafe entry: {unsafe[0]!r}")
        missing = sorted(expected_entries - actual_entries)
        if missing:
            raise RuntimeError(f"Release ZIP is missing entries: {', '.join(missing)}")
        unexpected = sorted(actual_entries - expected_entries)
        if unexpected:
            raise RuntimeError(
                f"Release ZIP contains unexpected entries: {', '.join(unexpected[:10])}"
            )


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    app_dir = args.app_dir.resolve()
    zip_path = args.zip_path.resolve()

    require_directory(app_dir, "application directory")
    require_file(app_dir / "VideoCutter.exe", "application executable")
    require_file(app_dir / "uninstall.ps1", "bundled uninstaller")

    internal_dir = app_dir / "_internal"
    require_directory(internal_dir, "PyInstaller runtime directory")
    require_file(internal_dir / "vue" / "qml" / "Main.qml", "application Main.qml")

    source_qml_root = project_root / "vue" / "qml"
    packaged_qml_root = internal_dir / "vue" / "qml"
    missing_qml_runtime_files = [
        str(path.relative_to(source_qml_root))
        for path in source_qml_root.rglob("*")
        if path.is_file()
        if not (packaged_qml_root / path.relative_to(source_qml_root)).is_file()
    ]
    if missing_qml_runtime_files:
        raise RuntimeError(
            "Packaged QML runtime files are missing: "
            f"{', '.join(missing_qml_runtime_files[:10])}"
        )

    ffmpeg = require_file(
        internal_dir / "vendor" / "ffmpeg" / "bin" / "ffmpeg.exe",
        "bundled ffmpeg.exe",
    )
    ffprobe = require_file(
        internal_dir / "vendor" / "ffmpeg" / "bin" / "ffprobe.exe",
        "bundled ffprobe.exe",
    )
    run_version_check(ffmpeg)
    run_version_check(ffprobe)

    pyside_root = require_directory(internal_dir / "PySide6", "PySide6 runtime")
    plugins_root = first_existing(
        [pyside_root / "Qt" / "plugins", pyside_root / "plugins"],
        "Qt plugins directory",
    )
    require_file(plugins_root / "platforms" / "qwindows.dll", "Qt Windows plugin")
    multimedia_dir = require_directory(
        plugins_root / "multimedia", "Qt multimedia plugins"
    )
    if not any(multimedia_dir.glob("*.dll")):
        raise RuntimeError(f"No Qt multimedia plugin DLLs found in {multimedia_dir}")

    qml_root = first_existing(
        [pyside_root / "Qt" / "qml", pyside_root / "qml"], "Qt QML runtime"
    )
    for relative_path in REQUIRED_QML_MODULES:
        require_file(qml_root / Path(relative_path), f"Qt QML module {relative_path}")

    manifest_path = require_file(app_dir / "release-manifest.json", "release manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError("Unsupported or missing release manifest schema_version.")
    if manifest.get("entrypoint") != "VideoCutter.exe":
        raise RuntimeError("Release manifest has an invalid entrypoint.")
    if args.release_tag and manifest.get("tag") != args.release_tag:
        raise RuntimeError(
            f"Release manifest tag {manifest.get('tag')!r} does not match {args.release_tag!r}."
        )
    version_text = require_file(app_dir / "version.txt", "version file").read_text(
        encoding="ascii"
    ).strip()
    if version_text != manifest.get("tag"):
        raise RuntimeError("version.txt does not match the release manifest tag.")
    expected_version = version_text[1:] if version_text.startswith("v") else version_text
    if manifest.get("version") != expected_version:
        raise RuntimeError("Release manifest version does not match its tag.")

    environment_path_names = (
        "USERPROFILE",
        "TEMP",
        "TMP",
        "RUNNER_TEMP",
        "RUNNER_TOOL_CACHE",
        "VIRTUAL_ENV",
    )
    scan_values = [
        str(project_root),
        str(Path(sys.executable).resolve().parent),
        *(os.environ.get(name, "") for name in environment_path_names),
        *args.forbidden_path,
    ]
    verify_no_developer_paths(app_dir, scan_values)

    installed_bytes = sum(
        path.stat().st_size for path in app_dir.rglob("*") if path.is_file()
    )
    archive_bytes = zip_path.stat().st_size
    installed_mib = installed_bytes / MIB
    archive_mib = archive_bytes / MIB
    if installed_mib > args.max_installed_mib:
        raise RuntimeError(
            f"Installed size {installed_mib:.2f} MiB exceeds "
            f"{args.max_installed_mib:.2f} MiB."
        )
    if archive_mib > args.max_archive_mib:
        raise RuntimeError(
            f"Archive size {archive_mib:.2f} MiB exceeds "
            f"{args.max_archive_mib:.2f} MiB."
        )

    verify_zip(zip_path, app_dir)
    print(f"Artifact verified: {app_dir}")
    print(f"Installed size: {installed_mib:.2f} MiB")
    print(f"Archive size: {archive_mib:.2f} MiB")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - this is a CLI validation boundary
        print(f"Artifact verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
