[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$SkipPackage
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptRoot = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $PSScriptRoot
    } else {
        Split-Path -Parent $PSCommandPath
    }
    $ProjectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$qmlLintExe = Join-Path $ProjectRoot ".venv\Scripts\pyside6-qmllint.exe"
$prepareFfmpegScript = Join-Path $ProjectRoot "scripts\prepare_ffmpeg.ps1"
$buildScript = Join-Path $ProjectRoot "scripts\build_windows.ps1"
$releaseTestRoot = Join-Path $ProjectRoot "build\release-tests-$PID"
$unitTestRoot = Join-Path $releaseTestRoot "unit"
$e2eTestRoot = Join-Path $releaseTestRoot "e2e"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    $pythonExe = "python"
}
if (-not (Test-Path -LiteralPath $qmlLintExe -PathType Leaf)) {
    $qmlLintCommand = Get-Command "pyside6-qmllint" -ErrorAction SilentlyContinue
    if ($null -eq $qmlLintCommand) {
        throw "pyside6-qmllint was not found. Install requirements.txt in the active environment."
    }
    $qmlLintExe = $qmlLintCommand.Source
}

function Invoke-CheckedStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host "`n==> $Name" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE."
    }
}

$releaseChecksPassed = $false
New-Item -ItemType Directory -Force -Path $releaseTestRoot | Out-Null
Push-Location $ProjectRoot
try {
    Invoke-CheckedStep "Prepare pinned FFmpeg" {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $prepareFfmpegScript -ProjectRoot $ProjectRoot
    }
    Invoke-CheckedStep "Lint Python" {
        & $pythonExe -m ruff check --isolated --select E4,E7,E9,F .
    }
    Invoke-CheckedStep "Lint QML" {
        & $qmlLintExe "vue\qml\Main.qml"
    }
    Invoke-CheckedStep "Run unit and integration tests" {
        & $pythonExe -m pytest -q -p no:cacheprovider --basetemp $unitTestRoot -m "not e2e"
    }
    Invoke-CheckedStep "Run real-media end-to-end tests" {
        & $pythonExe -m pytest -q -p no:cacheprovider --basetemp $e2eTestRoot -m e2e
    }

    if (-not $SkipPackage) {
        Invoke-CheckedStep "Build and verify the Windows package" {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $buildScript -ProjectRoot $ProjectRoot
        }
    }

    Write-Host "`nRelease-candidate checks passed." -ForegroundColor Green
    if ($SkipPackage) {
        Write-Host "Package build was skipped by request." -ForegroundColor Yellow
    }
    $releaseChecksPassed = $true
} finally {
    Pop-Location
    if ($releaseChecksPassed -and (Test-Path -LiteralPath $releaseTestRoot)) {
        Remove-Item -LiteralPath $releaseTestRoot -Recurse -Force
    }
}
