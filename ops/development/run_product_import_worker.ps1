$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendRoot = Join-Path $RepoRoot "wa_backend"
Set-Location $BackendRoot

$Python = Join-Path $BackendRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Backend virtual environment not found: $Python"
}

Write-Host "Recovering stalled product-import jobs..."
& $Python -m workers.recover_cli product-import
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "Starting Wanasah product-import worker..."
Write-Host "App: product_import_queue.app"
Write-Host "Queue: product-import"

& $Python -m procrastinate --app=product_import_queue.app worker -q product-import
exit $LASTEXITCODE
