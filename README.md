# NSFW Cutter

> Detect and cut unwanted (NSFW) segments out of your videos — a fast, keyboard-friendly
> desktop editor with AI-assisted scene picks. No command line required.

[![Latest Release](https://img.shields.io/github/v/release/Mohamad04/nsfw-cutter?label=download&style=flat-square)](https://github.com/Mohamad04/nsfw-cutter/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat-square)](https://github.com/Mohamad04/nsfw-cutter)

---

## Install — one command, no admin required

Open **PowerShell** (Win + R → type `powershell` → Enter) and run:

```powershell
irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/main/scripts/install.ps1 | iex
```

The installer will:

1. Fetch the exact versioned ZIP and SHA-256 file from the latest GitHub Release.
2. Verify and stage the complete application before changing the current installation.
3. Install it to `%LOCALAPPDATA%\NSFWCutter\VideoCutter.exe` with rollback protection.
4. Register it in App Paths and Windows **Installed apps** for the current user.
5. Create Start Menu shortcuts (and offer a Desktop shortcut), then launch the app.

**Run the exact same command again at any time to update to the latest version.**

> **Tip:** If you see a script-execution error, run this once first, then retry:
> ```powershell
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### FFmpeg

The installed app **bundles FFmpeg**, so it works out of the box and does not install
a second FFmpeg copy on the user's machine. If the bundled files are missing, reinstall
or update NSFW Cutter. Developers running from source can populate `vendor\ffmpeg` with
`scripts\prepare_ffmpeg.ps1`.

### Uninstall

Open **Windows Settings → Apps → Installed apps**, find **NSFW Cutter**, and choose
**Uninstall**. You can also use the Start Menu uninstall shortcut. The uninstaller
removes the application, bundled FFmpeg, old update payloads, shortcuts, and Windows
registration. Settings, database, cache, and logs are preserved by default; removing
them requires explicit confirmation. User videos and exports are never removed.

---

## What it does

NSFW Cutter is a desktop video editor focused on quickly finding and removing segments
you don't want to keep:

- **Load a video** and scrub it with a frame-accurate timeline (with 1-second and
  5-second jump controls).
- **Mark cut intervals** by hand, or let the **AI picks** panel suggest NSFW segments
  for you to accept or reject.
- **Choose how to export**:
  - *Remove intervals* — drop the marked ranges and keep the rest.
  - *Export clips separately* — save each kept range as its own file.
  - *Export merged clips* — stitch the kept ranges into one file.
- **Keeps audio and subtitles in sync** through the cuts.
- **Multi-language UI** and light / dark / system themes.

### AI providers

The AI picks feature can run against a **Local** model, **OpenAI**, or a **Custom**
provider, with a configurable model name, batch size, confidence threshold, and optional
GPU acceleration. Configure this in **Settings → AI Settings**.

---

## Versioning & auto-update

- The app knows its own version (shown in **Settings → About & Updates**). Releases are
  tagged `vMAJOR.MINOR.PATCH`; the version is stamped into the build automatically by CI.
- Click **Check for updates** in Settings to query GitHub for the latest release.
- When a newer version exists, click **Update now** — the installer downloads and validates
  the release first, then closes the app only for the payload swap and relaunches it.
- You can always update manually by re-running the one-line install command above.

---

## Requirements

- Windows 10 or 11.
- FFmpeg — **bundled with the installed app** and prepared into `vendor\ffmpeg` for
  source development/builds.
- Python 3.12+ — *only required to run from source or build the executable.*

---

## Running from source

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Prepare the FFmpeg copy used by development and production builds:
.\scripts\prepare_ffmpeg.ps1

# 4. Launch
python main.py
```

---

## Building a standalone executable

```powershell
# Builds dist\VideoCutter\ and dist\NSFW-Cutter-windows.zip
.\scripts\build_windows.ps1
```

`build_windows.ps1` prepares bundled FFmpeg, compiles translations, and runs PyInstaller
(onedir). Tagged CI builds produce `NSFW-Cutter-vMAJOR.MINOR.PATCH-windows.zip`, verify
the package, generate its `.sha256` file, and publish both through GitHub Releases.
The FFmpeg input is pinned to an immutable retained release and verified before extraction.

To publish a production build, push a strict semantic-version tag such as `v1.3.0`.
The release workflow stamps that version, runs Python/QML/PowerShell checks, verifies the
extracted package and its size budgets, smoke-launches it, then creates the GitHub Release
with generated release notes.

Before tagging, run the complete release-candidate gate:

```powershell
.\scripts\test_release_candidate.ps1
```

It includes real FFmpeg end-to-end coverage for embedded/external subtitles, Quick Cutting,
and Smart Cutting before building and verifying the Windows package. See the
[release checklist](docs/RELEASE_CHECKLIST.md) for the remaining manual product checks.

---

## PowerShell scripts reference

| Script                        | Audience   | What it does                                                                 |
|-------------------------------|------------|------------------------------------------------------------------------------|
| `scripts/install.ps1`         | Users      | Install / update the app to `%LOCALAPPDATA%\NSFWCutter` + shortcuts. No admin. |
| `scripts/uninstall.ps1`       | Users      | Registered uninstaller; preserves app data unless explicitly removed.        |
| `scripts/prepare_ffmpeg.ps1`  | Developers | Download and checksum the pinned FFmpeg build into `vendor\ffmpeg`.          |
| `scripts/build_windows.ps1`   | Developers | Build the Windows onedir app and release zip.                               |
| `scripts/test_release_candidate.ps1` | Developers | Run the complete pre-tag quality gate.                         |
| `scripts/verify_windows_artifact.py` | CI/build | Verify runtime files, paths, and size budgets.                         |

`install.ps1` accepts `-Force` (reinstall), `-NoLaunch`, and `-NoDesktop` when invoked
via `-File`.

---

## Where your data lives

The app uses standard per-user locations (via `platformdirs`), so nothing is tied to a
specific machine:

```
Settings : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\settings\settings.json
Database : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\data\nsfw_app.db
Cache    : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache
Logs     : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\logs
```

---

## Project structure

```
nsfw-cutter/
├── main.py                     # Entry point (Qt/QML app bootstrap + FFmpeg preflight)
├── version.py                  # Single source of truth for the app version
├── controllers/                # QML-facing controllers (app, settings, video cut, update)
├── core/                       # Paths, config, logging, time helpers
├── services/
│   ├── infrastructure/
│   │   ├── ffmpeg/             # FFmpeg/ffprobe discovery + invocation
│   │   └── update/            # GitHub-release version check + installer launcher
│   ├── editing/ · export/ · media/ · subtitles/ · i18n/
├── vue/qml/                    # QML UI
├── scripts/                    # install, uninstall, build, verification, and FFmpeg preparation
├── tests/e2e/                  # Generated-media Quick/Smart/subtitle release checks
├── vendor/ffmpeg/              # Bundled FFmpeg (populated by prepare_ffmpeg.ps1)
└── .github/workflows/          # CI (test), Build Windows, Release
```
