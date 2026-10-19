[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$AppName = "VideoCutter",
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
$prepareCublasScript = Join-Path $ProjectRoot "scripts\prepare_cuda12_cublas.ps1"
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

Write-Host "Preparing bundled CUDA 12 cuBLAS for CTranslate2"
& powershell -NoProfile -ExecutionPolicy Bypass -File $prepareCublasScript -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "CUDA 12 cuBLAS preparation failed."
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
    "--collect-binaries", "PySide6",
    "--collect-data", "faster_whisper",
    "--hidden-import", "transformers.models.qwen2_vl.video_processing_qwen2_vl"
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

# CTranslate2 adds its own package folder to the DLL search path, so its CUDA 12 cuBLAS goes there,
# apart from PyTorch's CUDA 13 libraries. Only the license and pin go under vendor\.
$cublasPin = Get-Content -LiteralPath (Join-Path $ProjectRoot "scripts\cuda12-cublas-pin.json") -Raw | ConvertFrom-Json
$cublasVendorDir = Join-Path $ProjectRoot "vendor\cuda12-cublas"
foreach ($cublasName in $cublasPin.binaries.PSObject.Properties.Name) {
    $pyinstallerArgs += @("--add-binary", "$(Join-Path $cublasVendorDir $cublasName);$($cublasPin.bundle_destination)")
}
foreach ($cublasDocument in @($cublasPin.documents.LICENSE.target, "BUILD-PIN.json")) {
    $pyinstallerArgs += @("--add-data", "$(Join-Path $cublasVendorDir $cublasDocument);vendor\cuda12-cublas")
}

$pyinstallerArgs += $entryFile

# PyInstaller resolves DLL dependencies it cannot find next to the binaries through PATH, and its PySide6
# hook bundles whatever OpenSSL Qt finds there (Git Bash puts Git for Windows' libssl-3-x64.dll on PATH;
# ImageMagick ships its own VC++ runtime). Run it with a fixed PATH so the bundle does not depend on the
# invoking shell or on tools installed on the build machine.
$pythonPrefixes = @(& $pythonExe -c "import sys; print(sys.prefix); print(sys.base_prefix)")
if ($LASTEXITCODE -ne 0 -or $pythonPrefixes.Count -ne 2) {
    throw "Unable to query the Python prefixes of $pythonExe."
}
$pythonPrefix = $pythonPrefixes[0].Trim()
$pythonBasePrefix = $pythonPrefixes[1].Trim()
$pythonExe = (Get-Command $pythonExe -ErrorAction Stop).Source
$controlledBuildPath = @(
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot,
    (Join-Path $env:SystemRoot "System32\Wbem")
) -join ";"

Push-Location $ProjectRoot
$originalPath = $env:PATH
try {
    $env:PATH = $controlledBuildPath
    Write-Host "Running PyInstaller with PATH=$controlledBuildPath"
    & $pythonExe -m PyInstaller @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }
}
finally {
    $env:PATH = $originalPath
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

$ffmpegPin = Get-Content -LiteralPath (Join-Path $ProjectRoot "scripts\ffmpeg-pin.json") -Raw | ConvertFrom-Json
foreach ($bundledBinary in @($bundledFfmpeg, $bundledFfprobe)) {
    $binaryName = Split-Path -Leaf $bundledBinary
    $actualHash = (Get-FileHash -LiteralPath $bundledBinary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ffmpegPin.binaries.$binaryName) {
        throw "Bundled $binaryName is not the pinned FFmpeg $($ffmpegPin.version) (SHA-256 $actualHash)."
    }
}
$bundledLicense = Join-Path (Split-Path -Parent (Split-Path -Parent $bundledFfmpeg)) $ffmpegPin.documents.LICENSE.target
if (-not (Test-Path -LiteralPath $bundledLicense -PathType Leaf) -or
    (Get-FileHash -LiteralPath $bundledLicense -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ffmpegPin.documents.LICENSE.sha256) {
    throw "The FFmpeg GPL license text is missing from the PyInstaller output: $bundledLicense"
}
Write-Host "Bundled FFmpeg verified: $($ffmpegPin.version), SHA-256 pinned, license included"

$internalDir = Join-Path $appDistDir "_internal"
foreach ($cublasName in $cublasPin.binaries.PSObject.Properties.Name) {
    # Dependency analysis (cublas64_12 -> cublasLt64_12, and the unused CUDA 12 bitsandbytes variants)
    # also copies the pinned DLL into the top-level _internal folder, which is on the DLL search path
    # of the whole process. Only the copy beside ctranslate2.dll is wanted.
    $topLevelCopy = Join-Path $internalDir $cublasName
    if ((Test-Path -LiteralPath $topLevelCopy -PathType Leaf) -and
        (Get-FileHash -LiteralPath $topLevelCopy -Algorithm SHA256).Hash.ToLowerInvariant() -eq $cublasPin.binaries.$cublasName.sha256) {
        Remove-Item -LiteralPath $topLevelCopy -Force
        Write-Host "Removed the top-level duplicate of $cublasName added by dependency analysis"
    }
    $bundledCublas = Join-Path $internalDir (Join-Path $cublasPin.bundle_destination $cublasName)
    if (-not (Test-Path -LiteralPath $bundledCublas -PathType Leaf) -or
        (Get-FileHash -LiteralPath $bundledCublas -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cublasPin.binaries.$cublasName.sha256) {
        throw "Bundled $cublasName is missing or is not the pinned cuBLAS $($cublasPin.version): $bundledCublas"
    }
    $copies = @(Get-ChildItem -LiteralPath $internalDir -Recurse -File -Filter $cublasName | Where-Object { $_.FullName -ne $bundledCublas })
    if ($copies.Count -gt 0) {
        throw "Unexpected extra copies of ${cublasName}: $($copies.FullName -join ', ')"
    }
}
$bundledCublasLicense = Join-Path $internalDir "vendor\cuda12-cublas\$($cublasPin.documents.LICENSE.target)"
if (-not (Test-Path -LiteralPath $bundledCublasLicense -PathType Leaf) -or
    (Get-FileHash -LiteralPath $bundledCublasLicense -Algorithm SHA256).Hash.ToLowerInvariant() -ne $cublasPin.documents.LICENSE.sha256) {
    throw "The NVIDIA cuBLAS license text is missing from the PyInstaller output: $bundledCublasLicense"
}
Write-Host "Bundled CUDA 12 cuBLAS verified: $($cublasPin.version) in _internal\$($cublasPin.bundle_destination), SHA-256 pinned, license included"

# Python's own OpenSSL (ssl and hashlib, used for example by the update check) must be bundled unchanged.
# Qt's optional OpenSSL TLS backend libraries must not be: without them Qt uses its Schannel backend.
$pythonOpenSsl = @(Get-ChildItem -LiteralPath (Join-Path $pythonBasePrefix "DLLs") -File |
    Where-Object { $_.Name -match '^lib(ssl|crypto)-\d+\.dll$' })
if ($pythonOpenSsl.Count -ne 2) {
    throw "Expected Python's libssl and libcrypto DLLs in $(Join-Path $pythonBasePrefix 'DLLs')."
}
foreach ($pythonDll in $pythonOpenSsl) {
    $bundledDll = Join-Path $internalDir $pythonDll.Name
    if (-not (Test-Path -LiteralPath $bundledDll -PathType Leaf) -or
        (Get-FileHash -LiteralPath $bundledDll -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $pythonDll.FullName -Algorithm SHA256).Hash) {
        throw "Python's $($pythonDll.Name) is missing from the PyInstaller output or differs from $($pythonDll.FullName)."
    }
}
foreach ($sslModule in @("_ssl.pyd", "_hashlib.pyd")) {
    if (-not (Test-Path -LiteralPath (Join-Path $internalDir $sslModule) -PathType Leaf)) {
        throw "Python's $sslModule is missing from the PyInstaller output."
    }
}
$expectedOpenSsl = @($pythonOpenSsl | ForEach-Object { Join-Path $internalDir $_.Name })
$unexpectedOpenSsl = @(Get-ChildItem -LiteralPath $internalDir -Recurse -File |
    Where-Object { $_.Name -match '^(lib(ssl|crypto)|libeay32|ssleay32)' -and $expectedOpenSsl -notcontains $_.FullName })
if ($unexpectedOpenSsl.Count -gt 0) {
    throw "Unexpected OpenSSL libraries in the PyInstaller output: $($unexpectedOpenSsl.FullName -join ', ')"
}
Write-Host "OpenSSL verified: only Python's $($pythonOpenSsl.Name -join ', ') are bundled"

# Every collected file must come from the project (including .venv and vendor\), the Python installation or Windows.
$collectToc = Join-Path $buildDir "$AppName\COLLECT-00.toc"
$tocSourceCheck = @'
import ast, os, sys
toc_path, *roots = sys.argv[1:]
roots = tuple(os.path.normcase(os.path.abspath(root)).rstrip(os.sep) + os.sep for root in roots)
with open(toc_path, encoding='utf-8') as handle:
    toc = ast.literal_eval(handle.read())
entries = next(part for part in toc if isinstance(part, list) and part and isinstance(part[0], tuple))
outside = sorted({src for _dest, src, _kind in entries if src and not os.path.normcase(os.path.abspath(src)).startswith(roots)})
print(len(entries))
print('\n'.join(outside))
'@
$tocResult = @(& $pythonExe -c $tocSourceCheck $collectToc $ProjectRoot $pythonPrefix $pythonBasePrefix $env:SystemRoot)
if ($LASTEXITCODE -ne 0 -or $tocResult.Count -lt 1) {
    throw "Unable to check the sources recorded in $collectToc."
}
$outsideSources = @($tocResult | Select-Object -Skip 1 | Where-Object { $_ })
if ($outsideSources.Count -gt 0) {
    throw "Files collected from outside the project, Python and Windows:`n - $($outsideSources -join "`n - ")"
}
Write-Host "Collected file sources verified: $($tocResult[0]) entries from the project, Python and Windows only"
foreach ($vcRuntimeName in @("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
    $vcRuntime = Join-Path $internalDir $vcRuntimeName
    if (Test-Path -LiteralPath $vcRuntime -PathType Leaf) {
        Write-Host "Bundled $vcRuntimeName $((Get-Item -LiteralPath $vcRuntime).VersionInfo.FileVersion)"
    }
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

Write-Host "Windows build complete: $appDistDir"
Write-Host "Zip created: $zipPath"
