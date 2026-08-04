# NSFW Cutter - User Installer & Updater
#
# Run with (one command, no administrator rights required):
#   irm https://raw.githubusercontent.com/Mohamad04/nsfw-cutter/main/scripts/install.ps1 | iex

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$NoLaunch,
    [switch]$NoDesktop,
    [string]$ExpectedTag = '',
    [int]$WaitForProcessId = 0,
    [string]$ExpectedExecutable = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = 'Mohamad04/nsfw-cutter'
$AppName = 'NSFW Cutter'
$Publisher = 'MohamadElHajj'
$ExeName = 'VideoCutter.exe'
$InstallDir = Join-Path $env:LOCALAPPDATA 'NSFWCutter'
$NewInstallDir = "$InstallDir.new"
$BackupInstallDir = "$InstallDir.backup"
$FailedInstallDir = "$InstallDir.failed"
$TransactionStatePath = "$InstallDir.install-state"
$ExePath = Join-Path $InstallDir $ExeName
$UninstallScriptPath = Join-Path $InstallDir 'uninstall.ps1'
$VersionFile = Join-Path $InstallDir 'version.txt'
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"
$TempRoot = Join-Path $env:TEMP 'NSFWCutterInstaller'
$SessionDir = Join-Path $TempRoot ([guid]::NewGuid().ToString('N'))
$ExtractDir = Join-Path $SessionDir 'extracted'
$AppPathsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\$ExeName"
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NSFWCutter'
$Headers = @{ 'User-Agent' = 'NSFWCutter-Installer'; 'Accept' = 'application/vnd.github+json' }

function Write-Step([string]$Message) { Write-Host "`n>> $Message" -ForegroundColor Cyan }
function Write-OK([string]$Message) { Write-Host "   OK  $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "   !! $Message" -ForegroundColor Yellow }

function Remove-PathWithRetry([string]$Path, [int]$Attempts = 10) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq $Attempts) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Remove-LegacyTemporaryFiles {
    foreach ($file in Get-ChildItem -LiteralPath $env:TEMP -File -Filter 'NSFWCutter_*.zip' -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
    foreach ($directory in Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'NSFWCutter_extract_*' -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $directory.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $env:TEMP 'ffmpeg_nsfwcutter.zip') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $env:TEMP 'ffmpeg_nsfwcutter_extract') -Recurse -Force -ErrorAction SilentlyContinue
}

function Set-TransactionState([string]$State) {
    Set-Content -LiteralPath $TransactionStatePath -Value $State -Encoding ASCII
}

function Clear-TransactionState {
    Remove-Item -LiteralPath $TransactionStatePath -Force -ErrorAction SilentlyContinue
}

function Repair-InterruptedInstallation {
    if (-not (Test-Path -LiteralPath $TransactionStatePath -PathType Leaf)) {
        if (-not (Test-Path -LiteralPath $InstallDir) -and (Test-Path -LiteralPath $BackupInstallDir)) {
            Move-Item -LiteralPath $BackupInstallDir -Destination $InstallDir
        } elseif ((Test-Path -LiteralPath $InstallDir) -and (Test-Path -LiteralPath $BackupInstallDir)) {
            Remove-PathWithRetry $BackupInstallDir
        }
        return
    }

    $state = (Get-Content -LiteralPath $TransactionStatePath -Raw).Trim()
    if ($state -ceq 'verified') {
        if (-not (Test-Path -LiteralPath $InstallDir) -and (Test-Path -LiteralPath $BackupInstallDir)) {
            Move-Item -LiteralPath $BackupInstallDir -Destination $InstallDir
        } elseif (Test-Path -LiteralPath $BackupInstallDir) {
            Remove-PathWithRetry $BackupInstallDir
        }
        Clear-TransactionState
        return
    }

    Write-Warn "Recovering an interrupted installation ($state)"
    Remove-PathWithRetry $FailedInstallDir
    if (Test-Path -LiteralPath $BackupInstallDir) {
        if (Test-Path -LiteralPath $InstallDir) {
            Move-Item -LiteralPath $InstallDir -Destination $FailedInstallDir
        }
        Move-Item -LiteralPath $BackupInstallDir -Destination $InstallDir
        try { Remove-PathWithRetry $FailedInstallDir } catch { Write-Warn "Could not remove failed payload: $_" }
        Set-TransactionState 'verified'
    } elseif ($state -ceq 'new-active' -and (Test-Path -LiteralPath $InstallDir)) {
        Remove-PathWithRetry $InstallDir
    }
    Clear-TransactionState
}

function Get-ExactAsset($Release, [string]$Name) {
    $matches = @($Release.assets | Where-Object { $_.name -ceq $Name })
    if ($matches.Count -ne 1) {
        throw "Release $($Release.tag_name) must contain exactly one asset named $Name."
    }
    return $matches[0]
}

function Save-ReleaseAsset($Asset, [string]$Destination) {
    $previousProgressPreference = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest `
            -Uri $Asset.browser_download_url `
            -OutFile $Destination `
            -Headers @{ 'User-Agent' = 'NSFWCutter-Installer' } `
            -UseBasicParsing
    } finally {
        $ProgressPreference = $previousProgressPreference
    }
    $downloadedLength = (Get-Item -LiteralPath $Destination).Length
    if ($Asset.size -and $downloadedLength -ne [long]$Asset.size) {
        throw "Downloaded size for $($Asset.name) is $downloadedLength bytes; expected $($Asset.size)."
    }
}

function Assert-SafeArchive([string]$ZipPath) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        if ($archive.Entries.Count -eq 0) { throw 'The release ZIP is empty.' }
        $entryNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        [long]$uncompressedBytes = 0
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if ($name.StartsWith('/') -or $name -notmatch '^VideoCutter/' -or $name -match '(^|/)\.\.(/|$)') {
                throw "Unsafe or unexpected ZIP entry: $($entry.FullName)"
            }
            if (-not $entryNames.Add($name)) { throw "Duplicate ZIP entry: $name" }
            $uncompressedBytes += $entry.Length
            if ($uncompressedBytes -gt 1150MB) {
                throw 'The release ZIP exceeds the maximum supported extracted size.'
            }
        }
        return $uncompressedBytes
    } finally {
        $archive.Dispose()
    }
}

function Assert-Payload([string]$PayloadDir, [string]$Tag) {
    $requiredFiles = @(
        (Join-Path $PayloadDir $ExeName),
        (Join-Path $PayloadDir 'uninstall.ps1'),
        (Join-Path $PayloadDir 'version.txt'),
        (Join-Path $PayloadDir 'release-manifest.json'),
        (Join-Path $PayloadDir '_internal\vue\qml\Main.qml'),
        (Join-Path $PayloadDir '_internal\vendor\ffmpeg\bin\ffmpeg.exe'),
        (Join-Path $PayloadDir '_internal\vendor\ffmpeg\bin\ffprobe.exe')
    )
    foreach ($requiredFile in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Release payload is missing required file: $requiredFile"
        }
    }

    $manifest = Get-Content -LiteralPath (Join-Path $PayloadDir 'release-manifest.json') -Raw |
        ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or $manifest.tag -cne $Tag -or $manifest.entrypoint -cne $ExeName) {
        throw 'Release manifest does not match the selected GitHub release.'
    }
    if ($manifest.version -cne $Tag.Substring(1)) {
        throw 'Release manifest version does not match the selected GitHub release.'
    }
    $payloadVersion = (Get-Content -LiteralPath (Join-Path $PayloadDir 'version.txt') -Raw).Trim()
    if ($payloadVersion -cne $Tag) { throw 'Payload version.txt does not match the selected release.' }

    $pysideRoot = Join-Path $PayloadDir '_internal\PySide6'
    $pluginCandidates = @(
        (Join-Path $pysideRoot 'Qt\plugins'),
        (Join-Path $pysideRoot 'plugins')
    )
    $pluginsRoot = $pluginCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
        Select-Object -First 1
    if (-not $pluginsRoot) { throw 'Release payload is missing the Qt plugins directory.' }
    if (-not (Test-Path -LiteralPath (Join-Path $pluginsRoot 'platforms\qwindows.dll') -PathType Leaf)) {
        throw 'Release payload is missing the Qt Windows platform plugin.'
    }
    $multimediaPlugins = Get-ChildItem -LiteralPath (Join-Path $pluginsRoot 'multimedia') -File -Filter '*.dll' -ErrorAction SilentlyContinue
    if (-not $multimediaPlugins) { throw 'Release payload is missing Qt multimedia plugins.' }

    $qmlCandidates = @((Join-Path $pysideRoot 'Qt\qml'), (Join-Path $pysideRoot 'qml'))
    $qtQmlRoot = $qmlCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
        Select-Object -First 1
    if (-not $qtQmlRoot) { throw 'Release payload is missing the Qt QML runtime.' }
    foreach ($module in @('QtQuick\qmldir', 'QtQuick\Controls\qmldir', 'QtQuick\Layouts\qmldir', 'QtQuick\Window\qmldir', 'QtMultimedia\qmldir')) {
        if (-not (Test-Path -LiteralPath (Join-Path $qtQmlRoot $module) -PathType Leaf)) {
            throw "Release payload is missing Qt QML module: $module"
        }
    }

    foreach ($tool in @('ffmpeg.exe', 'ffprobe.exe')) {
        $toolPath = Join-Path $PayloadDir "_internal\vendor\ffmpeg\bin\$tool"
        $output = & $toolPath -version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "$tool validation failed: $($output -join ' ')" }
    }
}

function Stop-InstalledApplication {
    if ($WaitForProcessId -gt 0) {
        $process = Get-Process -Id $WaitForProcessId -ErrorAction SilentlyContinue
        if ($process) {
            if ($ExpectedExecutable) {
                try { $actualPath = [IO.Path]::GetFullPath($process.Path) } catch { throw 'Unable to verify the updating process path.' }
                if ($actualPath -ine [IO.Path]::GetFullPath($ExpectedExecutable)) {
                    throw 'The updating process does not match the expected installed executable.'
                }
            }
            Write-Step "Closing $AppName now that the update is ready"
            try { $process.CloseMainWindow() | Out-Null } catch {}
            if (-not $process.WaitForExit(30000)) {
                throw "$AppName did not close. Close it and run the installer again."
            }
        }
    }

    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { return }
    $running = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue |
        Where-Object {
            try { [IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($ExePath) }
            catch { $false }
        }
    foreach ($process in $running) {
        Write-Step "Closing $AppName"
        try { $process.CloseMainWindow() | Out-Null } catch {}
        if (-not $process.WaitForExit(15000)) {
            throw "$AppName is still running. Close it and run the installer again."
        }
    }
}

function Invoke-SmokeTest([string]$ApplicationPath) {
    $previousPlatform = $env:QT_QPA_PLATFORM
    $previousUserDataRoot = $env:NSFW_CUTTER_USER_DATA_ROOT
    try {
        $env:QT_QPA_PLATFORM = 'offscreen'
        $env:NSFW_CUTTER_USER_DATA_ROOT = Join-Path $SessionDir 'smoke-data'
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $ApplicationPath
        $startInfo.Arguments = '--smoke-test'
        $startInfo.WorkingDirectory = Split-Path -Parent $ApplicationPath
        $startInfo.UseShellExecute = $false
        $process = [System.Diagnostics.Process]::Start($startInfo)
        if (-not $process) { throw 'Unable to start the installed application smoke test.' }
        if (-not $process.WaitForExit(30000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw 'The installed application smoke test timed out.'
        }
        $process.Refresh()
        if ($process.ExitCode -ne 0) { throw "The installed application smoke test failed with exit code $($process.ExitCode)." }
    } finally {
        $env:QT_QPA_PLATFORM = $previousPlatform
        $env:NSFW_CUTTER_USER_DATA_ROOT = $previousUserDataRoot
    }
}

function New-AppShortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $ExePath
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = $AppName
    $shortcut.IconLocation = $ExePath
    $shortcut.Save()
}

function New-UninstallShortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$UninstallScriptPath`""
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = "Uninstall $AppName"
    $shortcut.Save()
}

function Register-Installation([string]$Tag, [bool]$CreateDesktopShortcut) {
    if (-not (Test-Path -LiteralPath $AppPathsKey)) { New-Item -Path $AppPathsKey -Force | Out-Null }
    Set-ItemProperty -Path $AppPathsKey -Name '(default)' -Value $ExePath
    Set-ItemProperty -Path $AppPathsKey -Name 'Path' -Value $InstallDir

    if (-not (Test-Path -LiteralPath $UninstallKey)) { New-Item -Path $UninstallKey -Force | Out-Null }
    $installedBytes = (Get-ChildItem -LiteralPath $InstallDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $estimatedSizeKiB = [int][Math]::Ceiling($installedBytes / 1KB)
    $uninstallCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallScriptPath`""
    $quietUninstallCommand = "$uninstallCommand -Quiet"
    $stringProperties = @{
        DisplayName = $AppName
        DisplayVersion = $Tag.Substring(1)
        Publisher = $Publisher
        InstallLocation = $InstallDir
        DisplayIcon = $ExePath
        InstallDate = (Get-Date -Format 'yyyyMMdd')
        URLInfoAbout = "https://github.com/$Repo"
        URLUpdateInfo = "https://github.com/$Repo/releases"
        UninstallString = $uninstallCommand
        QuietUninstallString = $quietUninstallCommand
    }
    $dwordProperties = @{
        EstimatedSize = $estimatedSizeKiB
        NoModify = 1
        NoRepair = 1
    }
    foreach ($entry in $stringProperties.GetEnumerator()) {
        New-ItemProperty -Path $UninstallKey -Name $entry.Key -Value $entry.Value -PropertyType String -Force | Out-Null
    }
    foreach ($entry in $dwordProperties.GetEnumerator()) {
        New-ItemProperty -Path $UninstallKey -Name $entry.Key -Value $entry.Value -PropertyType DWord -Force | Out-Null
    }

    $startMenuRoot = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $startMenuDir = Join-Path $startMenuRoot 'NSFW Cutter'
    New-Item -Path $startMenuDir -ItemType Directory -Force | Out-Null
    New-AppShortcut (Join-Path $startMenuDir 'NSFW Cutter.lnk')
    New-UninstallShortcut (Join-Path $startMenuDir 'Uninstall NSFW Cutter.lnk')
    Remove-Item -LiteralPath (Join-Path $startMenuRoot 'NSFW Cutter.lnk') -Force -ErrorAction SilentlyContinue

    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NSFW Cutter.lnk'
    if ($CreateDesktopShortcut) {
        New-AppShortcut $desktopShortcut
    } elseif ($NoDesktop) {
        Remove-Item -LiteralPath $desktopShortcut -Force -ErrorAction SilentlyContinue
    }
}

function Remove-LegacyFfmpegPath {
    $legacyBin = Join-Path $InstallDir 'ffmpeg\bin'
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { return }
    $normalizedLegacy = $legacyBin.TrimEnd('\')
    $removed = $false
    $entries = foreach ($entry in $userPath.Split(';')) {
        if ($entry.Trim().TrimEnd('\') -ieq $normalizedLegacy) {
            $removed = $true
        } else {
            $entry
        }
    }
    if ($removed) {
        [Environment]::SetEnvironmentVariable('Path', ($entries -join ';'), 'User')
        Write-OK 'Removed legacy duplicate FFmpeg folder from user PATH'
    }
}

function Remove-LegacyFfmpegInstallation {
    Remove-LegacyFfmpegPath
    $legacyRoot = Join-Path $InstallDir 'ffmpeg'
    if (Test-Path -LiteralPath $legacyRoot) {
        Remove-PathWithRetry $legacyRoot
        Write-OK 'Removed the legacy duplicate FFmpeg installation'
    }
}

function Test-InstalledApplicationRunning {
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { return $false }
    $process = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue |
        Where-Object {
            try { [IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($ExePath) }
            catch { $false }
        } |
        Select-Object -First 1
    return $null -ne $process
}

function Start-InstalledApplicationAfterFailure {
    if (
        -not $NoLaunch -and
        (Test-Path -LiteralPath $ExePath -PathType Leaf) -and
        -not (Test-InstalledApplicationRunning)
    ) {
        Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir -ErrorAction SilentlyContinue
    }
}

function Invoke-Installer {
    Write-Step 'Fetching the latest GitHub release'
    $release = Invoke-RestMethod -Uri $ApiUrl -Headers $Headers -UseBasicParsing
    $tag = [string]$release.tag_name
    if ($tag -notmatch '^v\d+\.\d+\.\d+$') { throw "Unsupported release tag: $tag" }
    if ($ExpectedTag -and $ExpectedTag -cne $tag) {
        throw "The available release changed from $ExpectedTag to $tag. Check for updates again."
    }

    $zipName = "NSFW-Cutter-$tag-windows.zip"
    $checksumName = "$zipName.sha256"
    $zipAsset = Get-ExactAsset $release $zipName
    $checksumAsset = Get-ExactAsset $release $checksumName
    Write-OK "Latest release: $tag"
    Write-OK "Asset: $zipName ($([Math]::Round($zipAsset.size / 1MB, 1)) MiB)"

    $wasInstalled = Test-Path -LiteralPath $ExePath -PathType Leaf
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'NSFW Cutter.lnk'
    $hadDesktopShortcut = Test-Path -LiteralPath $desktopShortcut -PathType Leaf

    if ($wasInstalled -and -not $Force -and (Test-Path -LiteralPath $VersionFile -PathType Leaf)) {
        $installedTag = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
        if ($installedTag -ceq $tag) {
            try {
                Assert-Payload $InstallDir $tag
                $createDesktop = $hadDesktopShortcut -and -not $NoDesktop
                Register-Installation $tag $createDesktop
                Remove-LegacyFfmpegInstallation
                Write-Host "`n$AppName is already up to date ($tag)." -ForegroundColor Green
                if (-not $NoLaunch -and -not $WaitForProcessId -and -not (Test-InstalledApplicationRunning)) {
                    Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir
                }
                return
            } catch {
                Write-Warn 'The existing installation is incomplete; reinstalling it.'
            }
        }
    }

    New-Item -Path $ExtractDir -ItemType Directory -Force | Out-Null
    $zipPath = Join-Path $SessionDir $zipName
    $checksumPath = Join-Path $SessionDir $checksumName

    Write-Step "Downloading $zipName"
    Save-ReleaseAsset $zipAsset $zipPath
    Save-ReleaseAsset $checksumAsset $checksumPath

    Write-Step 'Verifying SHA-256 checksum'
    $checksumText = (Get-Content -LiteralPath $checksumPath -Raw).Trim()
    $checksumPattern = '^(?<hash>[A-Fa-f0-9]{64})\s+\*?' + [regex]::Escape($zipName) + '$'
    if ($checksumText -notmatch $checksumPattern) { throw "Invalid checksum file format for $zipName." }
    $actualHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    if ($actualHash -ine $Matches.hash) { throw 'The downloaded release failed SHA-256 verification.' }
    Write-OK 'Checksum verified'

    $archiveUncompressedBytes = Assert-SafeArchive $zipPath
    $temporaryDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($SessionDir))
    if ($temporaryDrive.AvailableFreeSpace -lt ($archiveUncompressedBytes + 100MB)) {
        throw 'There is not enough free disk space to extract the update safely.'
    }
    Write-Step 'Extracting and validating the release'
    Expand-Archive -LiteralPath $zipPath -DestinationPath $ExtractDir -Force
    $payloadDir = Join-Path $ExtractDir 'VideoCutter'
    Assert-Payload $payloadDir $tag
    Write-OK 'Staged release payload is complete and valid'

    $payloadBytes = (Get-ChildItem -LiteralPath $payloadDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($InstallDir))
    if ($drive.AvailableFreeSpace -lt ($payloadBytes + 100MB)) {
        throw 'There is not enough free disk space to stage the update safely.'
    }

    Remove-PathWithRetry $NewInstallDir
    New-Item -Path $NewInstallDir -ItemType Directory -Force | Out-Null
    $null = & robocopy $payloadDir $NewInstallDir /MIR /NFL /NDL /NJH /NJS /NP /R:5 /W:1
    if ($LASTEXITCODE -ge 8) { throw "Unable to stage the installation (robocopy exit code $LASTEXITCODE)." }
    Assert-Payload $NewInstallDir $tag

    Stop-InstalledApplication
    Remove-PathWithRetry $BackupInstallDir
    Remove-PathWithRetry $FailedInstallDir
    $oldInstallMoved = $false
    $newInstallActivated = $false
    Set-TransactionState 'prepared'
    try {
        if (Test-Path -LiteralPath $InstallDir) {
            Move-Item -LiteralPath $InstallDir -Destination $BackupInstallDir
            $oldInstallMoved = $true
            Set-TransactionState 'backup-created'
        }
        Set-TransactionState 'new-active'
        Move-Item -LiteralPath $NewInstallDir -Destination $InstallDir
        $newInstallActivated = $true
        Assert-Payload $InstallDir $tag
        Invoke-SmokeTest $ExePath
        Set-TransactionState 'verified'
    } catch {
        $installError = $_
        if ($newInstallActivated -and (Test-Path -LiteralPath $InstallDir)) {
            try {
                Move-Item -LiteralPath $InstallDir -Destination $FailedInstallDir
            } catch {
                try { Remove-PathWithRetry $InstallDir } catch {}
            }
        }
        if ($oldInstallMoved -and (Test-Path -LiteralPath $BackupInstallDir)) {
            if (-not (Test-Path -LiteralPath $InstallDir)) {
                Move-Item -LiteralPath $BackupInstallDir -Destination $InstallDir
                try { Remove-PathWithRetry $FailedInstallDir } catch {}
                Set-TransactionState 'verified'
                Clear-TransactionState
                Start-InstalledApplicationAfterFailure
                throw "Installation failed and the previous version was restored: $installError"
            }
            throw "Installation failed. The previous version is preserved at $BackupInstallDir and will be recovered on the next run: $installError"
        }
        try { Remove-PathWithRetry $FailedInstallDir } catch {}
        Clear-TransactionState
        Start-InstalledApplicationAfterFailure
        throw "Installation failed before activation; the existing installation was not changed: $installError"
    }

    try { Remove-LegacyFfmpegInstallation }
    catch { Write-Warn "Could not clean the legacy FFmpeg installation: $_" }
    $createDesktop = $false
    if (-not $NoDesktop) {
        if ($hadDesktopShortcut) {
            $createDesktop = $true
        } elseif (-not $wasInstalled) {
            $createDesktop = $true
            if ($Host.UI.RawUI -and -not [Environment]::GetEnvironmentVariable('CI')) {
                try {
                    $answer = Read-Host 'Create a Desktop shortcut? [Y/n]'
                    $createDesktop = ($answer -eq '' -or $answer -match '^[Yy]')
                } catch { $createDesktop = $true }
            }
        }
    }
    if (Test-Path -LiteralPath $BackupInstallDir) {
        try { Remove-PathWithRetry $BackupInstallDir }
        catch { Write-Warn "Could not remove the previous-version backup yet: $_" }
    }
    if (-not (Test-Path -LiteralPath $BackupInstallDir)) { Clear-TransactionState }

    try {
        Register-Installation $tag $createDesktop
    } catch {
        Start-InstalledApplicationAfterFailure
        throw "The application payload was installed, but Windows registration or shortcuts failed: $_"
    }

    Write-Host "`n$AppName $tag installed successfully." -ForegroundColor Green
    Write-Host "Installed at $InstallDir" -ForegroundColor Gray
    if (-not $NoLaunch) {
        Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir
    }
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\NSFWCutterInstaller')
$hasMutex = $false
try {
    try { $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(30)) }
    catch [System.Threading.AbandonedMutexException] { $hasMutex = $true }
    if (-not $hasMutex) { throw 'Another NSFW Cutter install or uninstall is already running.' }

    Repair-InterruptedInstallation
    Remove-PathWithRetry $NewInstallDir
    if (-not (Test-Path -LiteralPath $TransactionStatePath)) {
        Remove-PathWithRetry $FailedInstallDir
    }
    Remove-PathWithRetry $TempRoot
    Remove-LegacyTemporaryFiles
    New-Item -Path $SessionDir -ItemType Directory -Force | Out-Null

    Invoke-Installer
} finally {
    try { Remove-PathWithRetry $SessionDir }
    catch { Write-Warn "Could not remove temporary installer files: $_" }
    if (Test-Path -LiteralPath $TempRoot) {
        $remaining = Get-ChildItem -LiteralPath $TempRoot -Force -ErrorAction SilentlyContinue
        if (-not $remaining) { Remove-Item -LiteralPath $TempRoot -Force -ErrorAction SilentlyContinue }
    }
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
