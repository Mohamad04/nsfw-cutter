<#
.SYNOPSIS
    Prepare the project-local FFmpeg (vendor\ffmpeg) from the pinned, verified stable build.

.DESCRIPTION
    The pinned build is described in scripts\ffmpeg-pin.json (version, SHA-256 of ffmpeg.exe and
    ffprobe.exe, license documents). Nothing is accepted unless both executables match those hashes
    and report the pinned version.

    Sources, in order:
      1. Existing vendor\ffmpeg\bin binaries: kept if they match; refused (left untouched) if they do not,
         unless -Replace is given.
      2. -SourceDir: a local folder of the pinned build (containing bin\ffmpeg.exe, or ffmpeg.exe directly).
      3. -ArchivePath: a local copy of the pinned zip archive.
      4. The pinned WinGet package folder, if already installed for this user (Gyan.FFmpeg 8.1.1).
      5. -AllowDownload only: the pinned archive URL. Never used implicitly.

    The script never changes PATH and never installs anything system-wide.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1 -Replace -SourceDir C:\tools\ffmpeg-8.1.1-full_build
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$SourceDir = "",
    [string]$ArchivePath = "",
    [switch]$Replace,
    [switch]$AllowDownload,
    [switch]$NoAutoDetect
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptRoot = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
    $ProjectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

$pinPath = Join-Path $PSScriptRoot "ffmpeg-pin.json"
if (-not (Test-Path -LiteralPath $pinPath -PathType Leaf)) {
    throw "FFmpeg pin file not found: $pinPath"
}
$pin = Get-Content -LiteralPath $pinPath -Raw | ConvertFrom-Json

$vendorDir = Join-Path $ProjectRoot "vendor\ffmpeg"
$vendorBinDir = Join-Path $vendorDir "bin"
$workDir = Join-Path $ProjectRoot "vendor\ffmpeg-prepare.tmp"
$binaryNames = @("ffmpeg.exe", "ffprobe.exe")

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-PinnedHash([string]$Name) {
    return [string]$pin.binaries.$Name
}

function Get-RecoveryText {
    return @"
Recovery:
  - Use an existing copy of the pinned build: -SourceDir <folder of $($pin.winget_package_folder)> or -ArchivePath <$($pin.archive_name)>
  - Or install it for the current user only: winget install --id $($pin.winget_package_id) --version 8.1.1 (then rerun this script)
  - Or allow the pinned download explicitly: -AllowDownload ($($pin.download_url))
Expected SHA-256: ffmpeg.exe $(Get-PinnedHash 'ffmpeg.exe'), ffprobe.exe $(Get-PinnedHash 'ffprobe.exe')
"@
}

function Test-BuildFolder([string]$BinDir) {
    # Returns a list of problems; empty when both executables are the pinned build.
    $problems = @()
    foreach ($name in $binaryNames) {
        $path = Join-Path $BinDir $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $problems += "$name is missing in $BinDir"
            continue
        }
        $actual = Get-Sha256 $path
        if ($actual -ne (Get-PinnedHash $name)) {
            $problems += "$name SHA-256 is $actual, expected $(Get-PinnedHash $name)"
            continue
        }
        $versionLine = (& $path -hide_banner -version 2>&1 | Select-Object -First 1) -as [string]
        if ($versionLine -notmatch [regex]::Escape($pin.version)) {
            $problems += "$name reports '$versionLine', expected version $($pin.version)"
        }
    }
    return ,$problems
}

function Find-BinDir([string]$Root) {
    foreach ($candidate in @((Join-Path $Root "bin"), $Root)) {
        if (Test-Path -LiteralPath (Join-Path $candidate "ffmpeg.exe") -PathType Leaf) {
            return $candidate
        }
    }
    $found = Get-ChildItem -LiteralPath $Root -Recurse -File -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $found) { return $found.DirectoryName }
    return $null
}

function Install-FromBinDir([string]$BinDir, [string]$Origin) {
    $problems = Test-BuildFolder $BinDir
    if ($problems.Count -gt 0) {
        throw "Refusing FFmpeg from ${Origin}:`n  - $($problems -join "`n  - ")`n$(Get-RecoveryText)"
    }
    $buildRoot = Split-Path -Parent $BinDir
    New-Item -ItemType Directory -Force -Path $vendorBinDir | Out-Null

    if ($Replace) {
        $existing = @($binaryNames | ForEach-Object { Join-Path $vendorBinDir $_ } | Where-Object { Test-Path -LiteralPath $_ })
        if ($existing.Count -gt 0) {
            $backupDir = Join-Path $ProjectRoot ("artifacts\ffmpeg-previous-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            $existing | ForEach-Object { Copy-Item -LiteralPath $_ -Destination $backupDir -Force }
            Write-Host "Previous binaries kept in $backupDir (Git-ignored)"
        }
    }

    foreach ($name in $binaryNames) {
        $staged = Join-Path $vendorBinDir "$name.new"
        Copy-Item -LiteralPath (Join-Path $BinDir $name) -Destination $staged -Force
        if ((Get-Sha256 $staged) -ne (Get-PinnedHash $name)) {
            Remove-Item -LiteralPath $staged -Force
            throw "Copy of $name was corrupted; vendor\ffmpeg was not changed."
        }
    }
    foreach ($name in $binaryNames) {
        Move-Item -LiteralPath (Join-Path $vendorBinDir "$name.new") -Destination (Join-Path $vendorBinDir $name) -Force
    }
    Install-Documents $buildRoot
    Write-Host "FFmpeg $($pin.version) installed in $vendorBinDir from $Origin"
}

function Install-Documents([string]$BuildRoot) {
    foreach ($property in $pin.documents.PSObject.Properties) {
        $sourceName = $property.Name
        $target = Join-Path $vendorDir $property.Value.target
        $source = Join-Path $BuildRoot $sourceName
        if ((Test-Path -LiteralPath $source -PathType Leaf) -and (Get-Sha256 $source) -eq $property.Value.sha256) {
            Copy-Item -LiteralPath $source -Destination $target -Force
        }
    }
    Copy-Item -LiteralPath $pinPath -Destination (Join-Path $vendorDir "BUILD-PIN.json") -Force
}

function Assert-Documents {
    foreach ($property in $pin.documents.PSObject.Properties) {
        $target = Join-Path $vendorDir $property.Value.target
        if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or (Get-Sha256 $target) -ne $property.Value.sha256) {
            throw "Required FFmpeg document $($property.Value.target) is missing or modified in $vendorDir (GPL redistribution needs it).`n$(Get-RecoveryText)"
        }
    }
}

function Get-WinGetBuildRoots {
    $packages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (-not (Test-Path -LiteralPath $packages)) { return @() }
    return @(Get-ChildItem -LiteralPath $packages -Directory -Filter "$($pin.winget_package_id)_*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName $pin.winget_package_folder } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Container })
}

function Expand-PinnedArchive([string]$ZipPath) {
    if (Test-Path -LiteralPath $workDir) { Remove-Item -LiteralPath $workDir -Recurse -Force }
    $extractDir = Join-Path $workDir "extract"
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Expand-Archive -LiteralPath $ZipPath -DestinationPath $extractDir -Force
    $binDir = Find-BinDir $extractDir
    if ($null -eq $binDir) { throw "The archive $ZipPath does not contain ffmpeg.exe." }
    return $binDir
}

try {
    # 1. Existing project-local binaries.
    $existingProblems = Test-BuildFolder $vendorBinDir
    $hasExisting = @($binaryNames | Where-Object { Test-Path -LiteralPath (Join-Path $vendorBinDir $_) }).Count -gt 0
    if ($existingProblems.Count -eq 0) {
        $sameAsPin = (Test-Path -LiteralPath (Join-Path $vendorDir "BUILD-PIN.json")) -and
            ((Get-Sha256 (Join-Path $vendorDir "BUILD-PIN.json")) -eq (Get-Sha256 $pinPath))
        if (-not $sameAsPin) { Copy-Item -LiteralPath $pinPath -Destination (Join-Path $vendorDir "BUILD-PIN.json") -Force }
        $documentRoots = @()
        if (-not [string]::IsNullOrWhiteSpace($SourceDir)) { $documentRoots += (Resolve-Path -LiteralPath $SourceDir).Path }
        if (-not $NoAutoDetect) { $documentRoots += Get-WinGetBuildRoots }
        foreach ($root in $documentRoots) { Install-Documents $root }
        Assert-Documents
        Write-Host "FFmpeg $($pin.version) already prepared and verified in $vendorBinDir"
        exit 0
    }
    if ($hasExisting -and -not $Replace) {
        throw "vendor\ffmpeg\bin does not hold the pinned FFmpeg build and was left unchanged:`n  - $($existingProblems -join "`n  - ")`nRerun with -Replace to install the pinned build (the current binaries are kept under artifacts\).`n$(Get-RecoveryText)"
    }

    # 2-5. Pinned sources, never an unpinned 'latest'.
    if (-not [string]::IsNullOrWhiteSpace($SourceDir)) {
        $binDir = Find-BinDir (Resolve-Path -LiteralPath $SourceDir).Path
        if ($null -eq $binDir) { throw "No ffmpeg.exe found under -SourceDir $SourceDir" }
        Install-FromBinDir $binDir "-SourceDir $SourceDir"
    } elseif (-not [string]::IsNullOrWhiteSpace($ArchivePath)) {
        Install-FromBinDir (Expand-PinnedArchive (Resolve-Path -LiteralPath $ArchivePath).Path) "-ArchivePath $ArchivePath"
    } else {
        $installed = $false
        if (-not $NoAutoDetect) {
            foreach ($root in Get-WinGetBuildRoots) {
                $binDir = Find-BinDir $root
                if ($null -eq $binDir) { continue }
                $candidateProblems = Test-BuildFolder $binDir
                if ($candidateProblems.Count -eq 0) {
                    Install-FromBinDir $binDir "WinGet package $root"
                    $installed = $true
                    break
                }
            }
        }
        if (-not $installed) {
            if (-not $AllowDownload) {
                throw "The pinned FFmpeg build $($pin.version) was not found locally and downloading is not allowed.`n$(Get-RecoveryText)"
            }
            New-Item -ItemType Directory -Force -Path $workDir | Out-Null
            $zip = Join-Path $workDir $pin.archive_name
            Write-Host "Downloading pinned archive $($pin.download_url)"
            Invoke-WebRequest -Uri $pin.download_url -OutFile $zip -UseBasicParsing
            Install-FromBinDir (Expand-PinnedArchive $zip) "pinned download $($pin.download_url)"
        }
    }

    $finalProblems = Test-BuildFolder $vendorBinDir
    if ($finalProblems.Count -gt 0) { throw "Verification after installation failed:`n  - $($finalProblems -join "`n  - ")" }
    Assert-Documents
    Write-Host "Verified: ffmpeg.exe and ffprobe.exe are $($pin.version) (SHA-256 pinned in $pinPath)"
    exit 0
}
catch {
    [Console]::Error.WriteLine("FFmpeg preparation failed: " + $_.Exception.Message)
    exit 1
}
finally {
    if (Test-Path -LiteralPath $workDir) { Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue }
    Get-ChildItem -LiteralPath $vendorBinDir -Filter "*.new" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}
