# NSFW Cutter - User Installer & Updater
#
# Run with (one command, no admin required):
#   TODO(revert-before-release): restore the master URL once merged.
#   irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/master/scripts/install.ps1 | iex
#   irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/feat/deployement-and-versioning/scripts/install.ps1 | iex
#
# Installs to : %LOCALAPPDATA%\NSFWCutter\VideoCutter.exe
# Shortcuts   : Start Menu (always) + Desktop (asked, default yes)
# Re-running  : updates to the latest release in place. This same script is
#               used by the in-app "Update now" button.
#
# Optional switches (when invoked via -File instead of the one-liner above):
#   -Force      reinstall even if already up to date
#   -NoLaunch   do not launch the app after installing
#   -NoDesktop  do not create a Desktop shortcut (and do not prompt)

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoLaunch,
    [switch]$NoDesktop
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo         = 'Mohamad04/nsfw-cutter'
$AppName      = 'NSFW Cutter'
$ExeName      = 'VideoCutter.exe'
$InstallDir   = Join-Path $env:LOCALAPPDATA 'NSFWCutter'
$ExePath      = Join-Path $InstallDir $ExeName
$VersionFile  = Join-Path $InstallDir 'version.txt'
$ApiUrl       = "https://api.github.com/repos/$Repo/releases/latest"

function Write-Step([string]$msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "   !! $msg" -ForegroundColor Yellow }

# -- Resolve latest release ----------------------------------------------------
Write-Step "Fetching latest release from GitHub..."
try {
    $headers = @{ 'User-Agent' = 'NSFWCutter-Installer'; 'Accept' = 'application/vnd.github+json' }
    $release = Invoke-RestMethod -Uri $ApiUrl -Headers $headers -UseBasicParsing
} catch {
    Write-Error "Could not reach GitHub API: $_"
    exit 1
}

$tag   = $release.tag_name
$asset = $release.assets | Where-Object { $_.name -match '\.zip$' } | Select-Object -First 1
if (-not $asset) {
    Write-Error "No .zip asset found in release $tag."
    exit 1
}
$DownloadUrl = $asset.browser_download_url
Write-OK "Latest release : $tag"
Write-OK "Asset          : $($asset.name)  ($([math]::Round($asset.size/1MB,1)) MB)"

# -- Up-to-date check ----------------------------------------------------------
if ((Test-Path $VersionFile) -and -not $Force) {
    $installed = (Get-Content $VersionFile -Raw -ErrorAction SilentlyContinue).Trim()
    if ($installed -eq $tag -and (Test-Path $ExePath)) {
        Write-Host "`n  Already up to date ($tag). Nothing to do." -ForegroundColor Green
        Write-Host "  (Use -Force to reinstall.)" -ForegroundColor Gray
        exit 0
    }
    if ($installed) { Write-Warn "Installed: $installed  ->  Updating to: $tag" }
}

# -- Close a running instance --------------------------------------------------
$running = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue
if ($running) {
    Write-Step "Closing running $AppName..."
    $running | ForEach-Object { try { $_.CloseMainWindow() | Out-Null } catch {} }
    Start-Sleep -Seconds 2
    $running = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue
    if ($running) {
        try { $running | Stop-Process -Force -ErrorAction Stop } catch {}
        Start-Sleep -Seconds 1
    }
}

# -- Download ------------------------------------------------------------------
Write-Step "Downloading $($asset.name)..."
$TmpZip     = Join-Path $env:TEMP "NSFWCutter_$tag.zip"
$TmpExtract = Join-Path $env:TEMP "NSFWCutter_extract_$tag"
try {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TmpZip -Headers @{ 'User-Agent' = 'NSFWCutter-Installer' } -UseBasicParsing
} catch {
    Write-Error "Download failed: $_"
    exit 1
}
Write-OK "Downloaded to $TmpZip"

# -- Extract -------------------------------------------------------------------
Write-Step "Extracting..."
if (Test-Path $TmpExtract) { Remove-Item $TmpExtract -Recurse -Force }
Expand-Archive -LiteralPath $TmpZip -DestinationPath $TmpExtract -Force

# The release archive contains a top-level folder holding VideoCutter.exe.
$exeInArchive = Get-ChildItem -LiteralPath $TmpExtract -Recurse -File -Filter $ExeName |
    Select-Object -First 1
if (-not $exeInArchive) {
    Write-Error "The downloaded archive did not contain $ExeName."
    exit 1
}
$payloadDir = $exeInArchive.Directory.FullName
Write-OK "Payload: $payloadDir"

# -- Install (mirror payload into InstallDir) ----------------------------------
Write-Step "Installing to $InstallDir ..."
if (-not (Test-Path $InstallDir)) {
    New-Item -Path $InstallDir -ItemType Directory -Force | Out-Null
}

# robocopy /MIR makes InstallDir an exact mirror of the payload, removing stale
# files from previous versions. We exclude the optional user-installed ffmpeg
# folder so an app update never wipes it. Exit codes 0-7 indicate success.
$ffmpegDir = Join-Path $InstallDir 'ffmpeg'
$roboArgs = @($payloadDir, $InstallDir, '/MIR', '/XD', $ffmpegDir, '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:5', '/W:1')
$null = & robocopy @roboArgs
$roboExit = $LASTEXITCODE
if ($roboExit -ge 8) {
    Write-Error "File copy failed (robocopy exit code $roboExit). Is $AppName still running?"
    exit 1
}
if (-not (Test-Path $ExePath)) {
    Write-Error "Installation failed: $ExePath was not created."
    exit 1
}
Set-Content -Path $VersionFile -Value $tag -Encoding ASCII
Write-OK "Installed $ExePath"

# -- Cleanup temp --------------------------------------------------------------
Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue

# -- Register app path (user scope, no admin) ----------------------------------
try {
    $appPathsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\$ExeName"
    if (-not (Test-Path $appPathsKey)) { New-Item -Path $appPathsKey -Force | Out-Null }
    Set-ItemProperty -Path $appPathsKey -Name '(default)' -Value $ExePath
    Set-ItemProperty -Path $appPathsKey -Name 'Path'      -Value $InstallDir
    Write-OK "Registered app path (user scope)"
} catch {
    Write-Warn "Could not register app path (non-fatal): $_"
}

# -- Shortcuts -----------------------------------------------------------------
function New-Shortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk   = $shell.CreateShortcut($Path)
    $lnk.TargetPath       = $ExePath
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description      = $AppName
    $lnk.Save()
}

Write-Step "Creating Start Menu shortcut..."
$startMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$startLnk     = Join-Path $startMenuDir "$AppName.lnk"
try { New-Shortcut $startLnk; Write-OK "Start Menu: $startLnk" }
catch { Write-Warn "Could not create Start Menu shortcut: $_" }

$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"
$createDesktop = -not $NoDesktop
if ($createDesktop -and $Host.UI.RawUI -and -not [Environment]::GetEnvironmentVariable('CI')) {
    try {
        $answer = Read-Host "`nCreate a Desktop shortcut? [Y/n]"
        $createDesktop = ($answer -eq '' -or $answer -match '^[Yy]')
    } catch { $createDesktop = $true }
}
if ($createDesktop) {
    try { New-Shortcut $desktopLnk; Write-OK "Desktop:    $desktopLnk" }
    catch { Write-Warn "Could not create Desktop shortcut: $_" }
}

# -- Done ----------------------------------------------------------------------
Write-Host ""
Write-Host "  OK  $AppName $tag installed successfully!" -ForegroundColor Green
Write-Host "      Launch from the Start Menu or run:  $ExePath" -ForegroundColor Gray
Write-Host ""

if (-not $NoLaunch) {
    try { Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir } catch {}
}
