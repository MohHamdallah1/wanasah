$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendRoot = Join-Path $RepoRoot "wa_backend"
Set-Location $BackendRoot

$Python = Join-Path $BackendRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Backend virtual environment not found: $Python"
}

Write-Host "Recovering stalled report jobs..."
& $Python -m workers.recover_cli reports
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Starting Wanasah reports worker..."
Write-Host "App: workers.app.app"
Write-Host "Queue: reports"

& $Python -m procrastinate --app=workers.app.app worker -q reports
exit $LASTEXITCODE
