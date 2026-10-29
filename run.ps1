$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'The project Python environment is missing. Install the project requirements into .venv first.'
}
Push-Location $PSScriptRoot
try {
    & $projectPython (Join-Path $PSScriptRoot 'main.py') @args
    $projectExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $projectExitCode
