[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$AppName = "VideoCutter"
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

$prepareScript = Join-Path $ProjectRoot "scripts\prepare_ffmpeg.ps1"
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$entryFile = Join-Path $ProjectRoot "main.py"
$buildDir = Join-Path $ProjectRoot "build"
$distDir = Join-Path $ProjectRoot "dist"
$appDistDir = Join-Path $distDir $AppName
$zipPath = Join-Path $distDir "$AppName-windows.zip"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    $pythonExe = "python"
}

if (-not (Test-Path -LiteralPath $entryFile -PathType Leaf)) {
    throw "Entry file not found: $entryFile"
}

Write-Host "Preparing bundled FFmpeg"
& powershell -NoProfile -ExecutionPolicy Bypass -File $prepareScript -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "FFmpeg preparation failed."
}

Write-Host "Checking PyInstaller"
& $pythonExe -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to install PyInstaller."
    }
}

foreach ($generatedPath in @($buildDir, $distDir)) {
    if (Test-Path -LiteralPath $generatedPath) {
        Write-Host "Removing $generatedPath"
        Remove-Item -LiteralPath $generatedPath -Recurse -Force
    }
}

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", $AppName
)

$iconPath = Join-Path $ProjectRoot "assets\icons\app.ico"
if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
    $pyinstallerArgs += @("--icon", $iconPath)
}

function Add-DataDirectoryIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRelativePath,
        [Parameter(Mandatory = $true)]
        [string]$DestinationRelativePath
    )

    $sourcePath = Join-Path $ProjectRoot $SourceRelativePath
    if (Test-Path -LiteralPath $sourcePath -PathType Container) {
        $script:pyinstallerArgs += @("--add-data", "$sourcePath;$DestinationRelativePath")
    }
}

Add-DataDirectoryIfExists -SourceRelativePath "vendor\ffmpeg" -DestinationRelativePath "vendor\ffmpeg"
Add-DataDirectoryIfExists -SourceRelativePath "vue\qml" -DestinationRelativePath "vue\qml"
Add-DataDirectoryIfExists -SourceRelativePath "assets" -DestinationRelativePath "assets"
Add-DataDirectoryIfExists -SourceRelativePath "resources" -DestinationRelativePath "resources"

$pyinstallerArgs += $entryFile

Push-Location $ProjectRoot
try {
    Write-Host "Running PyInstaller"
    & $pythonExe -m PyInstaller @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $appDistDir -PathType Container)) {
    throw "PyInstaller output folder was not created: $appDistDir"
}

$bundledFfmpegCandidates = @(
    (Join-Path $appDistDir "vendor\ffmpeg\bin\ffmpeg.exe"),
    (Join-Path $appDistDir "_internal\vendor\ffmpeg\bin\ffmpeg.exe")
)

$bundledFfprobeCandidates = @(
    (Join-Path $appDistDir "vendor\ffmpeg\bin\ffprobe.exe"),
    (Join-Path $appDistDir "_internal\vendor\ffmpeg\bin\ffprobe.exe")
)

$bundledFfmpeg = $bundledFfmpegCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
$bundledFfprobe = $bundledFfprobeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1

if ($null -eq $bundledFfmpeg -or $null -eq $bundledFfprobe) {
    throw "Bundled FFmpeg binaries were not found in the PyInstaller output."
}

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Creating $zipPath"
Compress-Archive -LiteralPath $appDistDir -DestinationPath $zipPath -CompressionLevel Optimal

if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw "Build zip was not created: $zipPath"
}

Write-Host "Windows build complete: $appDistDir"
Write-Host "Zip created: $zipPath"
