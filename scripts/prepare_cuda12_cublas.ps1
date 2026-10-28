<#
.SYNOPSIS
    Prepare the project-local CUDA 12 cuBLAS runtime (vendor\cuda12-cublas) used by CTranslate2 (faster-whisper).

.DESCRIPTION
    The pinned NVIDIA redistributable is described in scripts\cuda12-cublas-pin.json (version, archive URL,
    archive SHA-256 and size, SHA-256 and size of cublas64_12.dll and cublasLt64_12.dll, license text).
    Nothing is accepted unless every file matches those values.

    Sources, in order:
      1. Existing vendor\cuda12-cublas files: kept if they match; refused (left untouched) if they do not,
         unless -Replace is given.
      2. -ArchivePath: a local copy of the pinned NVIDIA archive.
      3. -AllowDownload only: the pinned archive URL. Never used implicitly.

    Only the two DLLs and the license are extracted. The script never changes PATH, never installs
    anything system-wide and never touches the CUDA 13 libraries shipped with PyTorch.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_cuda12_cublas.ps1 -ArchivePath C:\downloads\libcublas-windows-x86_64-12.8.4.1-archive.zip
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$ArchivePath = "",
    [switch]$Replace,
    [switch]$AllowDownload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptRoot = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
    $ProjectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

$pinPath = Join-Path $PSScriptRoot "cuda12-cublas-pin.json"
if (-not (Test-Path -LiteralPath $pinPath -PathType Leaf)) {
    throw "cuBLAS pin file not found: $pinPath"
}
$pin = Get-Content -LiteralPath $pinPath -Raw | ConvertFrom-Json

$vendorDir = Join-Path $ProjectRoot "vendor\cuda12-cublas"
$workDir = Join-Path $ProjectRoot "vendor\cuda12-cublas-prepare.tmp"
$binaryNames = @($pin.binaries.PSObject.Properties | ForEach-Object { $_.Name })

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-RecoveryText {
    return @"
Recovery:
  - Use a local copy of the pinned archive: -ArchivePath <$($pin.archive_name)>
  - Or allow the pinned download explicitly: -AllowDownload ($($pin.download_url))
Expected archive SHA-256 $($pin.archive_sha256), size $($pin.archive_size) bytes (manifest $($pin.manifest_url))
"@
}

function Test-VendorFolder {
    # Returns a list of problems; empty when both DLLs and the license are the pinned files.
    $problems = @()
    foreach ($name in $binaryNames) {
        $expected = $pin.binaries.$name
        $path = Join-Path $vendorDir $name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $problems += "$name is missing in $vendorDir"
            continue
        }
        $actual = Get-Sha256 $path
        if ($actual -ne $expected.sha256 -or (Get-Item -LiteralPath $path).Length -ne $expected.size) {
            $problems += "$name SHA-256 is $actual, expected $($expected.sha256)"
        }
    }
    foreach ($property in $pin.documents.PSObject.Properties) {
        $target = Join-Path $vendorDir $property.Value.target
        if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or (Get-Sha256 $target) -ne $property.Value.sha256) {
            $problems += "Document $($property.Value.target) is missing or modified in $vendorDir"
        }
    }
    return ,$problems
}

function Assert-Archive([string]$ZipPath) {
    $length = (Get-Item -LiteralPath $ZipPath).Length
    if ($length -ne [int64]$pin.archive_size) {
        throw "Archive $ZipPath is $length bytes, expected $($pin.archive_size).`n$(Get-RecoveryText)"
    }
    $actual = Get-Sha256 $ZipPath
    if ($actual -ne $pin.archive_sha256) {
        throw "Archive $ZipPath SHA-256 is $actual, expected $($pin.archive_sha256).`n$(Get-RecoveryText)"
    }
}

function Install-FromArchive([string]$ZipPath, [string]$Origin) {
    Assert-Archive $ZipPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $entries = @{}
    foreach ($name in $binaryNames) { $entries[$name] = @{ path = $pin.binaries.$name.archive_path; sha256 = $pin.binaries.$name.sha256 } }
    foreach ($property in $pin.documents.PSObject.Properties) {
        $entries[$property.Value.target] = @{ path = $property.Value.archive_path; sha256 = $property.Value.sha256 }
    }

    New-Item -ItemType Directory -Force -Path $vendorDir | Out-Null
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($target in $entries.Keys) {
            $entryName = "$($pin.archive_root)/$($entries[$target].path)"
            $entry = $zip.GetEntry($entryName)
            if ($null -eq $entry) { throw "The archive does not contain $entryName." }
            $staged = Join-Path $vendorDir "$target.new"
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $staged, $true)
            if ((Get-Sha256 $staged) -ne $entries[$target].sha256) {
                throw "Extracted $target does not match its pinned SHA-256; vendor\cuda12-cublas was not changed."
            }
        }
    }
    finally {
        $zip.Dispose()
    }

    if ($Replace) {
        $existing = @($entries.Keys | ForEach-Object { Join-Path $vendorDir $_ } | Where-Object { Test-Path -LiteralPath $_ })
        if ($existing.Count -gt 0) {
            $backupDir = Join-Path $ProjectRoot ("artifacts\cuda12-cublas-previous-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
            New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
            $existing | ForEach-Object { Copy-Item -LiteralPath $_ -Destination $backupDir -Force }
            Write-Host "Previous files kept in $backupDir (Git-ignored)"
        }
    }
    foreach ($target in $entries.Keys) {
        Move-Item -LiteralPath (Join-Path $vendorDir "$target.new") -Destination (Join-Path $vendorDir $target) -Force
    }
    Copy-Item -LiteralPath $pinPath -Destination (Join-Path $vendorDir "BUILD-PIN.json") -Force
    Write-Host "cuBLAS $($pin.version) installed in $vendorDir from $Origin"
}

try {
    # 1. Existing project-local files.
    $existingProblems = Test-VendorFolder
    $hasExisting = @($binaryNames | Where-Object { Test-Path -LiteralPath (Join-Path $vendorDir $_) }).Count -gt 0
    if ($existingProblems.Count -eq 0) {
        Copy-Item -LiteralPath $pinPath -Destination (Join-Path $vendorDir "BUILD-PIN.json") -Force
        Write-Host "cuBLAS $($pin.version) already prepared and verified in $vendorDir"
        exit 0
    }
    if ($hasExisting -and -not $Replace) {
        throw "vendor\cuda12-cublas does not hold the pinned cuBLAS files and was left unchanged:`n  - $($existingProblems -join "`n  - ")`nRerun with -Replace to install the pinned files (the current ones are kept under artifacts\).`n$(Get-RecoveryText)"
    }

    # 2-3. Pinned sources only.
    if (-not [string]::IsNullOrWhiteSpace($ArchivePath)) {
        Install-FromArchive (Resolve-Path -LiteralPath $ArchivePath).Path "-ArchivePath $ArchivePath"
    } elseif ($AllowDownload) {
        New-Item -ItemType Directory -Force -Path $workDir | Out-Null
        $zipPath = Join-Path $workDir $pin.archive_name
        Write-Host "Downloading pinned archive $($pin.download_url)"
        Invoke-WebRequest -Uri $pin.download_url -OutFile $zipPath -UseBasicParsing
        Install-FromArchive $zipPath "pinned download $($pin.download_url)"
    } else {
        throw "The pinned cuBLAS $($pin.version) files were not found in $vendorDir and downloading is not allowed.`n$(Get-RecoveryText)"
    }

    $finalProblems = Test-VendorFolder
    if ($finalProblems.Count -gt 0) { throw "Verification after installation failed:`n  - $($finalProblems -join "`n  - ")" }
    Write-Host "Verified: $($binaryNames -join ', ') are cuBLAS $($pin.version) (SHA-256 pinned in $pinPath)"
    exit 0
}
catch {
    [Console]::Error.WriteLine("cuBLAS preparation failed: " + $_.Exception.Message)
    exit 1
}
finally {
    if (Test-Path -LiteralPath $workDir) { Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue }
    Get-ChildItem -LiteralPath $vendorDir -Filter "*.new" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}
