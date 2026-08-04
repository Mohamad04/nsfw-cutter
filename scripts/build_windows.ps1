[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$AppName = "VideoCutter",
    [string]$ReleaseTag = "",
    [int]$MaxInstalledSizeMiB = 1150,
    [int]$MaxArchiveSizeMiB = 450,
    [switch]$Console
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
$uninstallScript = Join-Path $ProjectRoot "scripts\uninstall.ps1"
$verificationScript = Join-Path $ProjectRoot "scripts\verify_windows_artifact.py"
$buildDir = Join-Path $ProjectRoot "build"
$distDir = Join-Path $ProjectRoot "dist"
$appDistDir = Join-Path $distDir $AppName

if ($ReleaseTag) {
    if ($ReleaseTag -notmatch '^v\d+\.\d+\.\d+$') {
        throw "ReleaseTag must use the format vMAJOR.MINOR.PATCH; received: $ReleaseTag"
    }
    $zipName = "NSFW-Cutter-$ReleaseTag-windows.zip"
} else {
    $zipName = "NSFW-Cutter-windows.zip"
}
$zipPath = Join-Path $distDir $zipName

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    $pythonExe = "python"
}

if (-not (Test-Path -LiteralPath $entryFile -PathType Leaf)) {
    throw "Entry file not found: $entryFile"
}
if (-not (Test-Path -LiteralPath $uninstallScript -PathType Leaf)) {
    throw "Uninstall script not found: $uninstallScript"
}
if (-not (Test-Path -LiteralPath $verificationScript -PathType Leaf)) {
    throw "Artifact verification script not found: $verificationScript"
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

$translationDir = Join-Path $ProjectRoot "resources\i18n"
if (Test-Path -LiteralPath $translationDir -PathType Container) {
    $translationFiles = Get-ChildItem -LiteralPath $translationDir -Filter "*.ts" -File
    if ($translationFiles) {
        $translationCompiler = $null
        if (Test-Path -LiteralPath $pythonExe -PathType Leaf) {
            $localCompiler = Join-Path (Split-Path -Parent $pythonExe) "pyside6-lrelease.exe"
            if (Test-Path -LiteralPath $localCompiler -PathType Leaf) {
                $translationCompiler = $localCompiler
            }
        }

        if ($null -eq $translationCompiler) {
            $pathCompiler = Get-Command "pyside6-lrelease" -ErrorAction SilentlyContinue
            if ($null -ne $pathCompiler) {
                $translationCompiler = $pathCompiler.Source
            }
        }

        if ($null -eq $translationCompiler) {
            throw "pyside6-lrelease was not found. Install PySide6 or run this script from the project virtualenv."
        }

        Write-Host "Compiling translations"
        foreach ($translationFile in $translationFiles) {
            $qmPath = Join-Path $translationDir "$($translationFile.BaseName).qm"
            & $translationCompiler $translationFile.FullName -qm $qmPath
            if ($LASTEXITCODE -ne 0) {
                throw "Translation compilation failed: $($translationFile.FullName)"
            }
        }
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
    $(if ($Console) { "--console" } else { "--windowed" }),
    "--name", $AppName
)

$pySide6RuntimeModules = @(
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2"
)

foreach ($moduleName in $pySide6RuntimeModules) {
    $pyinstallerArgs += @("--hidden-import", $moduleName)
}

$pyinstallerArgs += @(
    "--collect-data", "PySide6",
    "--collect-binaries", "PySide6"
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

Push-Location $ProjectRoot
try {
    $builtVersion = (& $pythonExe -c "from version import __version__; print(__version__)" | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($builtVersion)) {
        throw "Unable to read the packaged application version."
    }
}
finally {
    Pop-Location
}

$manifestTag = if ($ReleaseTag) { $ReleaseTag } elseif ($builtVersion -eq 'dev') { 'dev' } else { "v$builtVersion" }
if ($ReleaseTag -and $builtVersion -ne $ReleaseTag.Substring(1)) {
    throw "version.py reports $builtVersion but ReleaseTag is $ReleaseTag."
}

Copy-Item -LiteralPath $uninstallScript -Destination (Join-Path $appDistDir "uninstall.ps1") -Force
Set-Content -LiteralPath (Join-Path $appDistDir "version.txt") -Value $manifestTag -Encoding ASCII
$releaseManifest = [ordered]@{
    schema_version = 1
    tag = $manifestTag
    version = $builtVersion
    entrypoint = "$AppName.exe"
}
$releaseManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appDistDir "release-manifest.json") -Encoding UTF8

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

function Find-FirstExistingRuntimePath {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$CandidatePaths
    )

    foreach ($candidatePath in $CandidatePaths) {
        if (Test-Path -LiteralPath $candidatePath -PathType Container) {
            return $candidatePath
        }
    }

    return $null
}

function Assert-RuntimeDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string[]]$CandidatePaths
    )

    $existingPath = Find-FirstExistingRuntimePath -CandidatePaths $CandidatePaths
    if ($null -eq $existingPath) {
        $candidateList = $CandidatePaths -join "`n - "
        throw "$Name was not found in the PyInstaller output. Checked:`n - $candidateList"
    }

    Write-Host "$Name found: $existingPath"
    return $existingPath
}

$multimediaPluginDir = Assert-RuntimeDirectory -Name "Qt multimedia plugins" -CandidatePaths @(
    (Join-Path $appDistDir "_internal\PySide6\Qt\plugins\multimedia"),
    (Join-Path $appDistDir "_internal\PySide6\plugins\multimedia"),
    (Join-Path $appDistDir "PySide6\Qt\plugins\multimedia"),
    (Join-Path $appDistDir "PySide6\plugins\multimedia")
)

$platformPluginDir = Assert-RuntimeDirectory -Name "Qt platform plugins" -CandidatePaths @(
    (Join-Path $appDistDir "_internal\PySide6\Qt\plugins\platforms"),
    (Join-Path $appDistDir "_internal\PySide6\plugins\platforms"),
    (Join-Path $appDistDir "PySide6\Qt\plugins\platforms"),
    (Join-Path $appDistDir "PySide6\plugins\platforms")
)

$qmlRuntimeDir = Assert-RuntimeDirectory -Name "PySide6 QML runtime" -CandidatePaths @(
    (Join-Path $appDistDir "_internal\PySide6\Qt\qml"),
    (Join-Path $appDistDir "_internal\PySide6\qml"),
    (Join-Path $appDistDir "PySide6\Qt\qml"),
    (Join-Path $appDistDir "PySide6\qml")
)

$multimediaPluginFiles = Get-ChildItem -LiteralPath $multimediaPluginDir -File -ErrorAction Stop
if (-not $multimediaPluginFiles) {
    throw "Qt multimedia plugin directory exists but contains no plugin files: $multimediaPluginDir"
}

Write-Host "Qt multimedia plugin files:"
$multimediaPluginFiles | ForEach-Object { Write-Host " - $($_.Name)" }
Write-Host "Playback smoke check: bundled ffmpeg.exe/ffprobe.exe are for processing only; Qt video playback requires the PySide6 Qt Multimedia plugins verified above."

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

Write-Host "Creating $zipPath"
Compress-Archive -LiteralPath $appDistDir -DestinationPath $zipPath -CompressionLevel Optimal

if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw "Build zip was not created: $zipPath"
}

Write-Host "Verifying packaged Windows artifact"
& $pythonExe $verificationScript `
    --project-root $ProjectRoot `
    --app-dir $appDistDir `
    --zip-path $zipPath `
    --release-tag $manifestTag `
    --max-installed-mib $MaxInstalledSizeMiB `
    --max-archive-mib $MaxArchiveSizeMiB
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Windows artifact verification failed."
}

Write-Host "Windows build complete: $appDistDir"
Write-Host "Zip created: $zipPath"
