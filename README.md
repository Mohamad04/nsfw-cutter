# NSFW Cutter

> Detect and cut unwanted (NSFW) segments out of your videos — a fast, keyboard-friendly
> desktop editor with AI-assisted scene picks. No command line required.

[![Latest Release](https://img.shields.io/github/v/release/Mohamad04/nsfw-cutter?label=download&style=flat-square)](https://github.com/Mohamad04/nsfw-cutter/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue?style=flat-square)](https://github.com/Mohamad04/nsfw-cutter)

---

## Install — one command, no admin required

Open **PowerShell** (Win + R → type `powershell` → Enter) and run:

```powershell
irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/master/scripts/install.ps1 | iex
```

The installer will:

1. Fetch the latest release `.zip` from GitHub Releases.
2. Install it to `%LOCALAPPDATA%\NSFWCutter\VideoCutter.exe`.
3. Register it in the user App Paths registry key (no admin needed).
4. Create a **Start Menu** shortcut (and offer a **Desktop** shortcut).
5. Launch the app.

**Run the exact same command again at any time to update to the latest version.**

> **Tip:** If you see a script-execution error, run this once first, then retry:
> ```powershell
> Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### FFmpeg (usually not needed)

The installed app **bundles FFmpeg**, so it works out of the box. You only need the
optional FFmpeg installer if you run from source, or want `ffmpeg`/`ffprobe` on your
PATH for other tools. It installs to `%LOCALAPPDATA%\NSFWCutter\ffmpeg\bin` and adds
that folder to your user PATH:

```powershell
irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/master/scripts/install_ffmpeg.ps1 | iex
```

If the app cannot find FFmpeg (bundled, on PATH, or in the folder above) it will show a
message telling you to run the command above, and will not start until FFmpeg is
available.

### Uninstall

```powershell
Remove-Item "$env:LOCALAPPDATA\NSFWCutter" -Recurse -Force
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\NSFW Cutter.lnk" -ErrorAction SilentlyContinue
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\NSFW Cutter.lnk" -ErrorAction SilentlyContinue
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\VideoCutter.exe" -ErrorAction SilentlyContinue
```

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
- When a newer version exists, click **Update now** — the app closes, the installer runs
  in place (download → replace → relaunch), and the app reopens on the new version.
- You can always update manually by re-running the one-line install command above.

---

## Requirements

- Windows 10 or 11.
- FFmpeg — **bundled with the installed app**; only needed separately when running from
  source (see the FFmpeg installer above).
- Python 3.12+ — *only required to run from source or build the executable.*

---

## Running from source

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Provide FFmpeg for the app (either of these):
#    a) Bundle it into the project (used by the build):
.\scripts\prepare_ffmpeg.ps1
#    b) or install it to your user profile + PATH:
.\scripts\install_ffmpeg.ps1

# 4. Launch
python main.py
```

---

## Building a standalone executable

```powershell
# Builds dist\VideoCutter\ and dist\VideoCutter-windows.zip
.\scripts\build_windows.ps1
```

`build_windows.ps1` prepares bundled FFmpeg, compiles translations, and runs PyInstaller
(onedir). The output `.zip` is exactly what the release workflow publishes and what the
installer consumes. A portable `VideoCutter.spec` is also provided for manual
`pyinstaller VideoCutter.spec` builds.

---

## PowerShell scripts reference

| Script                        | Audience   | What it does                                                                 |
|-------------------------------|------------|------------------------------------------------------------------------------|
| `scripts/install.ps1`         | Users      | Install / update the app to `%LOCALAPPDATA%\NSFWCutter` + shortcuts. No admin. |
| `scripts/install_ffmpeg.ps1`  | Users      | *Optional.* Install FFmpeg to the user profile and add it to PATH.           |
| `scripts/prepare_ffmpeg.ps1`  | Developers | Download FFmpeg into `vendor\ffmpeg` so the build can bundle it.             |
| `scripts/build_windows.ps1`   | Developers | Build the Windows onedir app and release zip.                               |

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
├── scripts/                    # install.ps1, install_ffmpeg.ps1, prepare_ffmpeg.ps1, build_windows.ps1
├── vendor/ffmpeg/              # Bundled FFmpeg (populated by prepare_ffmpeg.ps1)
└── .github/workflows/          # CI (test), Build Windows, Release
```
