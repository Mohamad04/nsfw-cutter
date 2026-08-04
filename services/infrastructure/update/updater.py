"""
Self-update logic against GitHub Releases.

The application is distributed as a PyInstaller *onedir* build zipped into a
versioned GitHub release asset (``NSFW-Cutter-vX.Y.Z-windows.zip``). Because a onedir build is a
whole folder rather than a single exe, updating in place is delegated to the
same PowerShell installer used for the first install: it downloads the latest
release, validates and transactionally swaps the payload, then relaunches the
app. This module only decides *whether* an update exists and *launches* that installer.

All functions here are pure / non-UI so they can run in a background thread.
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from version import __version__

logger = logging.getLogger(__name__)

# GitHub repository that hosts the releases and the installer script.
GITHUB_REPO = "Mohamad04/nsfw-cutter"
# Branch that hosts the stable installer script.
INSTALL_BRANCH = "main"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# The installer doubles as the updater — running it again performs an in-place update.
INSTALL_SCRIPT_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{INSTALL_BRANCH}/scripts/install.ps1"
)

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "NSFWCutter-App",
}
_RELEASE_TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


@dataclass
class ReleaseInfo:
    tag: str            # e.g. "v1.2.0"
    version_str: str    # e.g. "1.2.0"
    name: str           # human release title
    download_url: str   # direct URL to the .zip asset
    checksum_url: str   # direct URL to the .zip.sha256 asset
    asset_name: str     # exact version-derived release asset name
    release_notes: str


# ── Version comparison ────────────────────────────────────────────────────────

def _semver(v: str) -> tuple:
    """'v1.2.3-beta' -> (1, 2, 3). 'dev' / unparsable -> (0, 0, 0)."""
    base = v.strip().lstrip("v").split("-")[0]
    try:
        return tuple(int(x) for x in base.split("."))
    except ValueError:
        return (0, 0, 0)


def current_version() -> str:
    return __version__


def is_newer(release: ReleaseInfo) -> bool:
    """True when the release is strictly newer than the running version.

    A "dev" build (running from source) reports version (0, 0, 0), so any
    published release is considered newer — handy while testing.
    """
    return _semver(release.tag) > _semver(__version__)


# ── Network ───────────────────────────────────────────────────────────────────

def fetch_latest_release() -> Tuple[Optional[ReleaseInfo], Optional[str]]:
    """Returns (ReleaseInfo, None) on success or (None, error_message) on failure."""
    try:
        with urlopen(Request(RELEASES_API, headers=_HEADERS), timeout=10) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        if not _RELEASE_TAG_PATTERN.fullmatch(tag):
            return None, f"Unsupported release tag: {tag or '<missing>'}"

        asset_name = f"NSFW-Cutter-{tag}-windows.zip"
        checksum_name = f"{asset_name}.sha256"
        assets = data.get("assets", [])
        matching_assets = [asset for asset in assets if asset.get("name") == asset_name]
        matching_checksums = [
            asset for asset in assets if asset.get("name") == checksum_name
        ]
        if len(matching_assets) != 1 or len(matching_checksums) != 1:
            return (
                None,
                f"Release {tag} must contain exactly {asset_name} and {checksum_name}.",
            )

        asset = matching_assets[0]
        checksum_asset = matching_checksums[0]

        return ReleaseInfo(
            tag=tag,
            version_str=tag.lstrip("v"),
            name=data.get("name", tag),
            download_url=asset["browser_download_url"],
            checksum_url=checksum_asset["browser_download_url"],
            asset_name=asset_name,
            release_notes=(data.get("body") or "").strip(),
        ), None

    except URLError as exc:
        return None, f"Network error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        return None, str(exc)


# ── Applying the update ─────────────────────────────────────────────────────────

def is_frozen() -> bool:
    """True when running as the packaged .exe (as opposed to `python main.py`)."""
    return bool(getattr(sys, "frozen", False))


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def launch_installer(
    expected_tag: str = "",
) -> Tuple[Optional[subprocess.Popen], Optional[str]]:
    """
    Launch the PowerShell installer in a new, visible window to perform the
    update. Returns (process, None) on successful launch or (None, error).

    The installer downloads and validates the complete release while this
    process stays open, then closes this exact executable before swapping the
    payload and relaunching the app.
    """
    if not is_frozen():
        return (
            None,
            "Self-update is only available in the packaged app. Pull the latest "
            "source instead when running from a checkout.",
        )
    if expected_tag and not _RELEASE_TAG_PATTERN.fullmatch(expected_tag):
        return None, f"Invalid release tag: {expected_tag}"

    powershell = _resolve_powershell()
    installer_url = _powershell_literal(INSTALL_SCRIPT_URL)
    expected_tag_argument = (
        f" -ExpectedTag {_powershell_literal(expected_tag)}" if expected_tag else ""
    )
    executable_argument = _powershell_literal(str(Path(sys.executable).resolve()))
    # Download the same public installer used for a first install, but pass the
    # checked tag and current process identity to make the handoff deterministic.
    command = (
        "$ErrorActionPreference='Stop'; "
        f"$installer = irm -Uri {installer_url}; "
        "& ([ScriptBlock]::Create($installer))"
        f"{expected_tag_argument}"
        f" -WaitForProcessId {os.getpid()}"
        f" -ExpectedExecutable {executable_argument}"
    )
    args = [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]

    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        process = subprocess.Popen(
            args,
            creationflags=creationflags,
            close_fds=True,
            cwd=str(Path(tempfile.gettempdir())),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to launch updater")
        return None, str(exc)

    logger.info("Update installer launched; it will close the app after staging.")
    return process, None


def _resolve_powershell() -> str:
    """Prefer Windows PowerShell, but fall back to PowerShell 7 (pwsh)."""
    import shutil

    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return "powershell"
