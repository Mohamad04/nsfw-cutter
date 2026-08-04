# NSFW Cutter - User-scope uninstaller

[CmdletBinding()]
param(
    [switch]$RemoveUserData,
    [switch]$Quiet,
    [switch]$Cleanup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$AppName = 'NSFW Cutter'
$ExeName = 'VideoCutter.exe'
$InstallDir = Join-Path $env:LOCALAPPDATA 'NSFWCutter'
$AppDataDir = Join-Path $env:LOCALAPPDATA 'MohamadElHajj\NSFW Cutter'
$TempInstallerRoot = Join-Path $env:TEMP 'NSFWCutterInstaller'
$AppPathsKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\$ExeName"
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\NSFWCutter'

function Write-Step([string]$Message) {
    if (-not $Quiet) { Write-Host "`n>> $Message" -ForegroundColor Cyan }
}

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

if (-not $Cleanup) {
    $helperPath = Join-Path $env:TEMP "NSFWCutterUninstall_$([guid]::NewGuid().ToString('N')).ps1"
    Copy-Item -LiteralPath $PSCommandPath -Destination $helperPath -Force
    Set-Location -LiteralPath $env:TEMP
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$helperPath`" -Cleanup"
    if ($RemoveUserData) { $arguments += ' -RemoveUserData' }
    if ($Quiet) { $arguments += ' -Quiet' }
    if ($Quiet) {
        $helper = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    } else {
        $helper = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -PassThru -Wait
    }
    exit $helper.ExitCode
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\NSFWCutterInstaller')
$hasMutex = $false
try {
    try { $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(30)) }
    catch [System.Threading.AbandonedMutexException] { $hasMutex = $true }
    if (-not $hasMutex) { throw 'Another NSFW Cutter install or uninstall is running.' }

    if (-not $Quiet -and -not $RemoveUserData -and (Test-Path -LiteralPath $AppDataDir)) {
        $answer = Read-Host 'Also remove NSFW Cutter settings, database, cache, and logs? [y/N]'
        $RemoveUserData = $answer -match '^[Yy]'
    }

    Write-Step "Closing $AppName"
    $installedExe = Join-Path $InstallDir $ExeName
    $running = Get-Process -Name ([IO.Path]::GetFileNameWithoutExtension($ExeName)) -ErrorAction SilentlyContinue |
        Where-Object {
            try { [IO.Path]::GetFullPath($_.Path) -ieq [IO.Path]::GetFullPath($installedExe) }
            catch { $false }
        }
    foreach ($process in $running) {
        try { $process.CloseMainWindow() | Out-Null } catch {}
        try { $process.WaitForExit(10000) | Out-Null } catch {}
        if (-not $process.HasExited) {
            if ($Quiet) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            } else {
                throw "$AppName is still running. Close it without unsaved work, then uninstall again."
            }
        }
    }

    Write-Step 'Removing application files and update leftovers'
    Remove-PathWithRetry $InstallDir
    Remove-PathWithRetry "$InstallDir.new"
    Remove-PathWithRetry "$InstallDir.backup"
    Remove-PathWithRetry "$InstallDir.failed"
    Remove-Item -LiteralPath "$InstallDir.install-state" -Force -ErrorAction SilentlyContinue
    Remove-PathWithRetry $TempInstallerRoot
    foreach ($file in Get-ChildItem -LiteralPath $env:TEMP -File -Filter 'NSFWCutter_*.zip' -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $file.FullName -Force -ErrorAction SilentlyContinue
    }
    foreach ($directory in Get-ChildItem -LiteralPath $env:TEMP -Directory -Filter 'NSFWCutter_extract_*' -ErrorAction SilentlyContinue) {
        Remove-Item -LiteralPath $directory.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $env:TEMP 'ffmpeg_nsfwcutter.zip') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $env:TEMP 'ffmpeg_nsfwcutter_extract') -Recurse -Force -ErrorAction SilentlyContinue
    foreach ($helper in Get-ChildItem -LiteralPath $env:TEMP -File -Filter 'NSFWCutterUninstall_*.ps1' -ErrorAction SilentlyContinue) {
        if ($helper.FullName -ine $PSCommandPath) {
            Remove-Item -LiteralPath $helper.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    $legacyFfmpegBin = Join-Path $InstallDir 'ffmpeg\bin'
    try {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if ($userPath) {
            $normalizedLegacy = $legacyFfmpegBin.TrimEnd('\')
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
            }
        }
    } catch {}

    Write-Step 'Removing shortcuts and Windows registration'
    $startMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $desktopDir = [Environment]::GetFolderPath('Desktop')
    foreach ($shortcut in @(
        (Join-Path $startMenuDir "$AppName.lnk"),
        (Join-Path $startMenuDir 'NSFW Cutter\NSFW Cutter.lnk'),
        (Join-Path $startMenuDir 'NSFW Cutter\Uninstall NSFW Cutter.lnk'),
        (Join-Path $desktopDir "$AppName.lnk")
    )) {
        Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $startMenuDir 'NSFW Cutter') -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $AppPathsKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue

    if ($RemoveUserData) {
        Write-Step 'Removing settings, database, cache, and logs'
        Remove-PathWithRetry $AppDataDir
    }

    if (-not $Quiet) {
        Write-Host "`n$AppName was uninstalled successfully." -ForegroundColor Green
        if (-not $RemoveUserData -and (Test-Path -LiteralPath $AppDataDir)) {
            Write-Host "User data was preserved at $AppDataDir" -ForegroundColor Gray
        }
    }
} finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    try { Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue } catch {}
}
