$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendRoot = Join-Path $RepoRoot "wa_backend"
Set-Location $BackendRoot

$Python = Join-Path $BackendRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Backend virtual environment not found: $Python"
}

Write-Host "Starting Wanasah operational worker..."
Write-Host "App: workers.app.app"
Write-Host "Queues: maintenance,notifications"
Write-Host "This terminal must remain open during a full development runtime."

& $Python -m procrastinate --app=workers.app.app worker -q maintenance,notifications
exit $LASTEXITCODE
