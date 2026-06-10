[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$FfmpegZipUrl = "",
    [string]$ReleaseApiUrl = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
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

function Resolve-FfmpegZipUrl {
    if (-not [string]::IsNullOrWhiteSpace($FfmpegZipUrl)) {
        return $FfmpegZipUrl
    }

    Write-Host "Resolving latest Windows FFmpeg release from $ReleaseApiUrl"
    $release = Invoke-RestMethod -Uri $ReleaseApiUrl -Headers @{ "User-Agent" = "VideoCutter-build" }
    $asset = $release.assets |
        Where-Object {
            $_.name -match "win64-gpl.*\.zip$" -and
            $_.name -notmatch "shared" -and
            $_.browser_download_url
        } |
        Sort-Object name |
        Select-Object -First 1

    if ($null -eq $asset) {
        throw "Unable to find a static Windows win64 GPL FFmpeg zip in the latest release metadata."
    }

    return $asset.browser_download_url
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

if (Test-PreparedFfmpeg) {
    Write-Host "FFmpeg binaries already exist in $vendorBinDir. Skipping download."
    Invoke-VersionCheck -ExecutablePath $ffmpegExe
    Invoke-VersionCheck -ExecutablePath $ffprobeExe
    exit 0
}

if (Test-Path -LiteralPath $downloadRoot) {
    Remove-Item -LiteralPath $downloadRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

$resolvedZipUrl = Resolve-FfmpegZipUrl
Write-Host "Downloading FFmpeg from $resolvedZipUrl"
Save-RemoteFile -Uri $resolvedZipUrl -OutputPath $zipPath

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
