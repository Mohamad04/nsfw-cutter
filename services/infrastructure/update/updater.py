"""
Self-update logic against GitHub Releases.

The application is distributed as a PyInstaller *onedir* build zipped into a
GitHub release asset (``VideoCutter-windows.zip``). Because a onedir build is a
whole folder rather than a single exe, updating in place is delegated to the
same PowerShell installer used for the first install: it downloads the latest
release, mirrors it over the install directory and relaunches the app. This
module only decides *whether* an update exists and *launches* that installer.

All functions here are pure / non-UI so they can run in a background thread.
"""

import json
import logging
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
# Branch that hosts the installer script.
# TODO(revert-before-release): restore "master" once this is merged.
# INSTALL_BRANCH = "master"
INSTALL_BRANCH = "feat/deployement-and-versioning"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# The installer doubles as the updater — running it again performs an in-place update.
INSTALL_SCRIPT_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{INSTALL_BRANCH}/scripts/install.ps1"
)

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "NSFWCutter-App",
}


@dataclass
class ReleaseInfo:
    tag: str            # e.g. "v1.2.0"
    version_str: str    # e.g. "1.2.0"
    name: str           # human release title
    download_url: str   # direct URL to the .zip asset
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

        asset = next(
            (a for a in data.get("assets", []) if a["name"].lower().endswith(".zip")),
            None,
        )
        if not asset:
            return None, "No .zip asset found in the latest release."

        return ReleaseInfo(
            tag=data["tag_name"],
            version_str=data["tag_name"].lstrip("v"),
            name=data.get("name", data["tag_name"]),
            download_url=asset["browser_download_url"],
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


def launch_installer() -> Tuple[bool, Optional[str]]:
    """
    Launch the PowerShell installer in a new, visible window to perform the
    update, then return so the caller can quit the app (freeing the locked
    files). Returns (True, None) on successful launch or (False, error).

    The installer waits briefly for this process to exit, mirrors the latest
    release over the install directory and relaunches the app.
    """
    if not is_frozen():
        return (
            False,
            "Self-update is only available in the packaged app. Pull the latest "
            "source instead when running from a checkout.",
        )

    powershell = _resolve_powershell()
    # -NoExit is intentionally omitted: the window closes when the update ends.
    command = (
        "$ErrorActionPreference='Stop'; "
        f"irm {INSTALL_SCRIPT_URL} | iex"
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
        subprocess.Popen(
            args,
            creationflags=creationflags,
            close_fds=True,
            cwd=str(Path(tempfile.gettempdir())),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to launch updater")
        return False, str(exc)

    logger.info("Update installer launched; the app will now exit to unlock files.")
    return True, None


def _resolve_powershell() -> str:
    """Prefer Windows PowerShell, but fall back to PowerShell 7 (pwsh)."""
    import shutil

    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return "powershell"
