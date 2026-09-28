$ErrorActionPreference = "Stop"

$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $BackendRoot

$Python = Join-Path $BackendRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Product Import worker venv Python was not found: $Python"
}

$Concurrency = 1
if ($env:PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS) {
    $Concurrency = [int]$env:PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS
}
if ($Concurrency -lt 1) {
    throw "PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS must be >= 1."
}

& $Python -m procrastinate `
    --app=domains.simple_products.imports.infrastructure.queue.app `
    worker `
    -q product-import `
    -c $Concurrency

exit $LASTEXITCODE
