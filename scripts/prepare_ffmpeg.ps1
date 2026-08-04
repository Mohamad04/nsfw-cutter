[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$FfmpegZipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-07-31-14-10/ffmpeg-n8.1.2-34-g9b6c8969e0-win64-gpl-8.1.zip",
    [string]$FfmpegZipSha256 = "cc4156d51387566ea8ba653fc3a04897bdf812fddf652428d9030bbf7ae24835",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptRoot = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $PSScriptRoot
    } else {
        Split-Path -Parent $PSCommandPath
    }

    $ProjectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

$vendorBinDir = Join-Path $ProjectRoot "vendor\ffmpeg\bin"
$ffmpegExe = Join-Path $vendorBinDir "ffmpeg.exe"
$ffprobeExe = Join-Path $vendorBinDir "ffprobe.exe"
$downloadRoot = Join-Path $ProjectRoot "vendor\ffmpeg\.download"
$zipPath = Join-Path $downloadRoot "ffmpeg-windows.zip"
$extractRoot = Join-Path $downloadRoot "extract"

function Test-PreparedFfmpeg {
    return (Test-Path -LiteralPath $ffmpegExe -PathType Leaf) -and (Test-Path -LiteralPath $ffprobeExe -PathType Leaf)
}

function Invoke-VersionCheck {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath
    )

    $output = & $ExecutablePath -version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Version check failed for $ExecutablePath.`n$($output -join [Environment]::NewLine)"
    }

    Write-Host ($output | Select-Object -First 1)
}

function Save-RemoteFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -ne $curl) {
        & $curl.Source -L --fail --output $OutputPath $Uri
        if ($LASTEXITCODE -eq 0) {
            return
        }

        Write-Warning "curl.exe failed with exit code $LASTEXITCODE. Falling back to Invoke-WebRequest."
    }

    Invoke-WebRequest -Uri $Uri -OutFile $OutputPath -UseBasicParsing
}

New-Item -ItemType Directory -Force -Path $vendorBinDir | Out-Null

if ((Test-PreparedFfmpeg) -and -not $Force) {
    Write-Host "FFmpeg binaries already exist in $vendorBinDir. Skipping download."
    Invoke-VersionCheck -ExecutablePath $ffmpegExe
    Invoke-VersionCheck -ExecutablePath $ffprobeExe
    exit 0
}

if ([string]::IsNullOrWhiteSpace($FfmpegZipUrl)) {
    throw "FfmpegZipUrl cannot be empty."
}
if ($FfmpegZipSha256 -notmatch '^[A-Fa-f0-9]{64}$') {
    throw "FfmpegZipSha256 must be a 64-character SHA-256 digest."
}

if (Test-Path -LiteralPath $downloadRoot) {
    Remove-Item -LiteralPath $downloadRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

Write-Host "Downloading pinned FFmpeg from $FfmpegZipUrl"
Save-RemoteFile -Uri $FfmpegZipUrl -OutputPath $zipPath

$actualArchiveHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
if ($actualArchiveHash -ine $FfmpegZipSha256) {
    throw "FFmpeg archive checksum mismatch. Expected $FfmpegZipSha256, received $actualArchiveHash."
}
Write-Host "FFmpeg archive checksum verified"

Write-Host "Extracting FFmpeg archive"
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force

$foundFfmpeg = Get-ChildItem -LiteralPath $extractRoot -Recurse -File -Filter "ffmpeg.exe" |
    Where-Object { $_.DirectoryName -match "\\bin$" } |
    Select-Object -First 1

$foundFfprobe = Get-ChildItem -LiteralPath $extractRoot -Recurse -File -Filter "ffprobe.exe" |
    Where-Object { $_.DirectoryName -match "\\bin$" } |
    Select-Object -First 1

if ($null -eq $foundFfmpeg -or $null -eq $foundFfprobe) {
    throw "FFmpeg archive did not contain both ffmpeg.exe and ffprobe.exe under a bin directory."
}

Copy-Item -LiteralPath $foundFfmpeg.FullName -Destination $ffmpegExe -Force
Copy-Item -LiteralPath $foundFfprobe.FullName -Destination $ffprobeExe -Force

if (-not (Test-PreparedFfmpeg)) {
    throw "FFmpeg preparation failed: expected binaries were not created in $vendorBinDir."
}

Remove-Item -LiteralPath $downloadRoot -Recurse -Force

Write-Host "FFmpeg prepared in $vendorBinDir"
Invoke-VersionCheck -ExecutablePath $ffmpegExe
Invoke-VersionCheck -ExecutablePath $ffprobeExe
