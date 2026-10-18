# NSFW Cutter - Optional FFmpeg Installer
#
# The packaged app already bundles FFmpeg, so most users never need this.
# It is useful when running from source, or if you want ffmpeg/ffprobe available
# on your PATH for other tools too.
#
# Run with (one command, no admin required):
#   irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/master/scripts/install_ffmpeg.ps1 | iex
#
# Installs the pinned, verified FFmpeg 8.1.1 build (www.gyan.dev, GPL v3) - never a moving "latest"
# nightly. Both executables must match the SHA-256 values below (kept identical to
# scripts/ffmpeg-pin.json by tests/test_ffmpeg_pin.py).
#
# Installs to : %LOCALAPPDATA%\NSFWCutter\ffmpeg\bin  (ffmpeg.exe + ffprobe.exe + LICENSE.txt)
# PATH        : adds that folder to the current user's PATH if missing
#
# Optional switches (when invoked via -File):
#   -Force       reinstall even if the pinned build is already installed
#   -NoPath      do not modify the user PATH
#   -SourceDir   use a local copy of the pinned build instead of downloading

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoPath,
    [string]$SourceDir = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

$PinnedVersion = '8.1.1-full_build-www.gyan.dev'
$PinnedArchiveUrl = 'https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-full_build.zip'
$PinnedHashes = @{
    'ffmpeg.exe'  = '09948d4cdd0650da6ff5a87577469f2a218dc2615ae379f8f734d24c49de0f73'
    'ffprobe.exe' = 'a6618e99bb58869ded3c6f37b53aa1a8d701c3591dbb7b5b317d47369c112be2'
}

$BinDir     = Join-Path $env:LOCALAPPDATA 'NSFWCutter\ffmpeg\bin'
$FfmpegExe  = Join-Path $BinDir 'ffmpeg.exe'
$FfprobeExe = Join-Path $BinDir 'ffprobe.exe'

function Write-Step([string]$msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }

function Test-PinnedFolder([string]$Folder) {
    foreach ($name in $PinnedHashes.Keys) {
        $path = Join-Path $Folder $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $PinnedHashes[$name]) { return $false }
    }
    return $true
}

function Find-PinnedBinDir([string]$Root) {
    $candidates = @(Get-ChildItem -LiteralPath $Root -Recurse -File -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.DirectoryName } | Select-Object -Unique)
    foreach ($candidate in $candidates) {
        if (Test-PinnedFolder $candidate) { return $candidate }
    }
    return $null
}

if ((Test-PinnedFolder $BinDir) -and -not $Force) {
    Write-OK "Pinned FFmpeg $PinnedVersion already installed in $BinDir (use -Force to reinstall)."
} else {
    $TmpExtract = Join-Path $env:TEMP 'ffmpeg_nsfwcutter_extract'
    $sourceBin = $null
    if ($SourceDir) {
        $sourceBin = Find-PinnedBinDir $SourceDir
    } else {
        $winget = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path -LiteralPath $winget) {
            foreach ($package in Get-ChildItem -LiteralPath $winget -Directory -Filter 'Gyan.FFmpeg_*') {
                $sourceBin = Find-PinnedBinDir $package.FullName
                if ($sourceBin) { break }
            }
        }
        if (-not $sourceBin) {
            $TmpZip = Join-Path $env:TEMP 'ffmpeg_nsfwcutter_8.1.1.zip'
            Write-Step "Downloading pinned FFmpeg $PinnedVersion..."
            Invoke-WebRequest -Uri $PinnedArchiveUrl -OutFile $TmpZip -Headers @{ 'User-Agent' = 'NSFWCutter-Installer' } -UseBasicParsing
            if (Test-Path $TmpExtract) { Remove-Item $TmpExtract -Recurse -Force }
            Expand-Archive -LiteralPath $TmpZip -DestinationPath $TmpExtract -Force
            Remove-Item $TmpZip -Force -ErrorAction SilentlyContinue
            $sourceBin = Find-PinnedBinDir $TmpExtract
        }
    }
    if (-not $sourceBin) {
        Write-Error ("No copy of the pinned FFmpeg $PinnedVersion was found (expected SHA-256 ffmpeg.exe " +
            "$($PinnedHashes['ffmpeg.exe'])). Nothing was installed. Install it with " +
            "'winget install --id Gyan.FFmpeg --version 8.1.1' or pass -SourceDir.")
        exit 1
    }

    New-Item -Path $BinDir -ItemType Directory -Force | Out-Null
    foreach ($name in $PinnedHashes.Keys) {
        Copy-Item -LiteralPath (Join-Path $sourceBin $name) -Destination (Join-Path $BinDir $name) -Force
    }
    $license = Join-Path (Split-Path -Parent $sourceBin) 'LICENSE'
    if (Test-Path -LiteralPath $license) { Copy-Item -LiteralPath $license -Destination (Join-Path $BinDir 'LICENSE.txt') -Force }
    if (Test-Path $TmpExtract) { Remove-Item $TmpExtract -Recurse -Force -ErrorAction SilentlyContinue }

    if (-not (Test-PinnedFolder $BinDir)) {
        Write-Error "FFmpeg installation failed: the installed binaries do not match the pinned SHA-256."
        exit 1
    }
    Write-OK "Installed pinned FFmpeg $PinnedVersion to $BinDir"
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
