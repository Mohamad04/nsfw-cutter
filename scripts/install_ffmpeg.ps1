# NSFW Cutter - Optional FFmpeg Installer
#
# The packaged app already bundles FFmpeg, so most users never need this.
# It is useful when running from source, or if you want ffmpeg/ffprobe available
# on your PATH for other tools too.
#
# Run with (one command, no admin required):
#   irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/master/scripts/install_ffmpeg.ps1 | iex
#
# Installs to : %LOCALAPPDATA%\NSFWCutter\ffmpeg\bin  (ffmpeg.exe + ffprobe.exe)
# PATH        : adds that folder to the current user's PATH if missing
#
# Optional switches (when invoked via -File):
#   -Force   re-download even if already installed
#   -NoPath  do not modify the user PATH

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoPath,
    [string]$ReleaseApiUrl = 'https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

$BinDir     = Join-Path $env:LOCALAPPDATA 'NSFWCutter\ffmpeg\bin'
$FfmpegExe  = Join-Path $BinDir 'ffmpeg.exe'
$FfprobeExe = Join-Path $BinDir 'ffprobe.exe'

function Write-Step([string]$msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "   !! $msg" -ForegroundColor Yellow }

function Test-Installed {
    return (Test-Path -LiteralPath $FfmpegExe) -and (Test-Path -LiteralPath $FfprobeExe)
}

if ((Test-Installed) -and -not $Force) {
    Write-OK "FFmpeg already installed in $BinDir (use -Force to reinstall)."
} else {
    Write-Step "Resolving latest Windows FFmpeg build from BtbN/FFmpeg-Builds..."
    $release = Invoke-RestMethod -Uri $ReleaseApiUrl -Headers @{ 'User-Agent' = 'NSFWCutter-Installer' } -UseBasicParsing
    $asset = $release.assets |
        Where-Object { $_.name -match 'win64-gpl.*\.zip$' -and $_.name -notmatch 'shared' } |
        Sort-Object name |
        Select-Object -First 1
    if (-not $asset) {
        Write-Error "Could not find a static win64 GPL FFmpeg zip in the latest release."
        exit 1
    }
    Write-OK "Asset: $($asset.name)  ($([math]::Round($asset.size/1MB,1)) MB)"

    $TmpZip     = Join-Path $env:TEMP 'ffmpeg_nsfwcutter.zip'
    $TmpExtract = Join-Path $env:TEMP 'ffmpeg_nsfwcutter_extract'

    Write-Step "Downloading FFmpeg..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $TmpZip -Headers @{ 'User-Agent' = 'NSFWCutter-Installer' } -UseBasicParsing

    Write-Step "Extracting..."
    if (Test-Path $TmpExtract) { Remove-Item $TmpExtract -Recurse -Force }
    Expand-Archive -LiteralPath $TmpZip -DestinationPath $TmpExtract -Force

    $srcFfmpeg  = Get-ChildItem -LiteralPath $TmpExtract -Recurse -File -Filter 'ffmpeg.exe'  | Select-Object -First 1
    $srcFfprobe = Get-ChildItem -LiteralPath $TmpExtract -Recurse -File -Filter 'ffprobe.exe' | Select-Object -First 1
    if (-not $srcFfmpeg -or -not $srcFfprobe) {
        Write-Error "The archive did not contain both ffmpeg.exe and ffprobe.exe."
        exit 1
    }

    New-Item -Path $BinDir -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath $srcFfmpeg.FullName  -Destination $FfmpegExe  -Force
    Copy-Item -LiteralPath $srcFfprobe.FullName -Destination $FfprobeExe -Force

    Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue

    if (-not (Test-Installed)) {
        Write-Error "FFmpeg installation failed: expected binaries were not created."
        exit 1
    }
    Write-OK "Installed FFmpeg to $BinDir"
}

# -- Add to user PATH ----------------------------------------------------------
if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { $userPath = '' }
    $entries = $userPath.Split(';') | Where-Object { $_ -ne '' }
    if ($entries -notcontains $BinDir) {
        Write-Step "Adding FFmpeg to your user PATH..."
        $newPath = if ($userPath.TrimEnd(';') -eq '') { $BinDir } else { "$($userPath.TrimEnd(';'));$BinDir" }
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        # Make it available in the current session too.
        $env:Path = "$env:Path;$BinDir"
        Write-OK "Added to PATH. Open a new terminal for it to take effect everywhere."
    } else {
        Write-OK "FFmpeg folder is already on your user PATH."
    }
}

Write-Host ""
& $FfmpegExe -version | Select-Object -First 1
Write-Host ""
Write-Host "  OK  FFmpeg is ready for NSFW Cutter." -ForegroundColor Green
Write-Host ""
