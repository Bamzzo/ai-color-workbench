# Start the app from any working directory.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$main = Join-Path $root "app\main.py"
$worker = Join-Path $root "build-arm64\Debug\render_worker.exe"

if (-not (Test-Path $python)) {
    Write-Error "Python venv not found: $python. See README install steps."
    exit 1
}
if (-not (Test-Path $worker)) {
    Write-Warning "render_worker.exe not found at $worker; preview/export will be disabled."
}

& $python $main @args
exit $LASTEXITCODE
