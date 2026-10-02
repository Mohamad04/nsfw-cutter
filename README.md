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

### Local movie analysis

AI Picks uses a local, coarse-to-fine movie pipeline. Coarse interval and scene-change
frames first pass through the pinned, approximately 23 MB
`Marqo/nsfw-image-detection-384` classifier. Only candidate windows are sampled densely
and sent to the pinned `Qwen/Qwen2.5-VL-3B-Instruct` VLM as timestamped contact sheets.
Text/subtitle evidence may request visual inspection, but it cannot create a suggestion
without visual evidence.

**Balanced** is the default mode; Fast samples less densely and Thorough increases
sampling inside candidates. On NVIDIA GPUs, automatic placement tries 4-bit NF4 Qwen
fully on the GPU, then falls back to FP16 GPU/CPU offload when required. Compact JSON is
grammar-constrained, receives one text-only repair attempt, and has a 75-second soft
per-batch deadline. Completed batches are checkpointed and resumed after cancellation or
failure.

Suggestions are review-only: analysis never cuts, exports, deletes, or uploads media
automatically. Model downloads are disabled by default and model weights are not bundled
in releases. Generic Local/OpenAI/Custom settings belong to the older AI settings flow;
this movie-analysis pipeline currently uses its pinned local models. See
[Local VLM Movie Analysis](docs/vlm_analysis_mvp.md) for exact source commands, modes,
cache/resume paths, privacy, monitoring, limitations, and the manual performance checklist.

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
# 1. Create a virtual environment
python -m venv .venv

# 2. Install dependencies
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Optional NVIDIA CUDA build used by local movie analysis
.\.venv\Scripts\python.exe -m pip install torch==2.13.0+cu130 torchvision==0.28.0+cu130 --index-url https://download.pytorch.org/whl/cu130

# Optional local movie-analysis stack (Python packages, no model weights)
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt

# 3. Prepare the FFmpeg copy used by development and production builds:
.\scripts\prepare_ffmpeg.ps1

# 4. Launch
.\.venv\Scripts\python.exe main.py
```

AI model downloads remain disabled until explicitly enabled for a first run:

```powershell
$env:NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD = "1"
.\.venv\Scripts\python.exe main.py
```

After the required models are cached, remove the opt-in and launch normally. See the
[full VLM guide](docs/vlm_analysis_mvp.md#install-and-run-from-source) for CUDA
verification and model-cache configuration.

### Reviewer demo path

For the current AI-assisted demo, source execution is the verified path. Use Windows
10/11, Python 3.12 or newer, the dependencies above, and resolvable `ffmpeg` and
`ffprobe`. The application checks the bundled `vendor\ffmpeg` directory, the user-level
NSFW Cutter FFmpeg installation, and `PATH`. Keep the pinned Marqo and Qwen model
snapshots in the configured cache when running with downloads disabled.

Launch from the repository root:

```powershell
.\.venv\Scripts\python.exe main.py
```

Demo flow:

1. Load a local video.
2. Select **AI Picks**, then **Analyze video**.
3. Inspect the timestamped suggestions; accept at least one and reject another.
4. Confirm only accepted suggestions appear in the cut list.
5. Select **Export Clean Video** and wait for the completion panel and output path.
6. Reopen the exported file and confirm video playback and audio.

The verified Smart Cutting demo input is a local MP4 or MKV with one H.264/yuv420p
video stream and conventional audio such as AAC. Smart Cutting currently supports only
removing selected intervals; use representative local media with readable duration and
keyframes. The production AI path is the pinned `Marqo/nsfw-image-detection-384`
prefilter followed by pinned `Qwen/Qwen2.5-VL-3B-Instruct` review.

Current demo limitations:

- Whisper first attempts CUDA and may fall back to slower CPU transcription.
- An occasional invalid VLM structured response can cause that individual candidate
  batch to be skipped; other valid batches still complete.
- AI review decisions and the cut list are session-local and are not restored after the
  application exits or a different video is loaded.
- Smart Cutting compatibility is intentionally narrow: MP4/MKV, one H.264/yuv420p
  video stream, available keyframes, and remove-intervals export.
- **Preview Cuts** is not implemented/enabled; validate the completed export by reopening
  it.

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

Production builds install the pinned AI runtime dependencies, while model weights remain
outside the package and are provisioned only after explicit user consent. The source launch
above remains the recommended reviewer path when inspecting or changing the AI pipeline.

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
VLM data : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\vlm-analysis
AI models: %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\Cache\models
Logs     : %LOCALAPPDATA%\MohamadElHajj\NSFW Cutter\logs
```

Set `NSFW_CUTTER_MODEL_CACHE` to override only the AI model location. Final analysis
records and resumable per-batch checkpoints stay under `vlm-analysis`; neither stores the
source path or full transcript. Checkpoints can contain bounded raw/repaired Qwen output,
which remains local but may describe sensitive content. Temporary sampled frames,
contact sheets, and audio live under `vlm-analysis\work` only while a run is active
(except work left by a process crash). Optional LangSmith tracing is disabled by default
and sends only allowlisted, redacted metadata when explicitly enabled—not media, paths,
prompts, transcripts, or raw model output.

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
