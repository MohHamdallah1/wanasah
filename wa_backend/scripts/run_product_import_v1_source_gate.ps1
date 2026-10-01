# Phase 19 source-only regression gate; Windows PowerShell 5.1+.
# No real DB/HTTP/Worker, no benchmark and no 50k acceptance assertion.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$backend = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $backend
$dashboard = Join-Path $root 'dashboard'
$python = Join-Path $backend 'venv\Scripts\python.exe'
$vitest = Join-Path $dashboard 'node_modules\.bin\vitest.cmd'
$tsc = Join-Path $dashboard 'node_modules\.bin\tsc.cmd'
$eslint = Join-Path $dashboard 'node_modules\.bin\eslint.cmd'
$vite = Join-Path $dashboard 'node_modules\.bin\vite.cmd'

foreach ($binary in @($python, $vitest, $tsc, $eslint, $vite)) {
    if (-not (Test-Path -LiteralPath $binary)) {
        throw ('P19_SOURCE_GATE_MISSING_DEPENDENCY: ' + $binary)
    }
}

function Assert-Success([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw ('P19_SOURCE_GATE_FAIL: ' + $step + ' exit=' + $LASTEXITCODE)
    }
}

# Explicitly EXCLUDES real PostgreSQL integration and Worker-creating gates.
$environmentNames = @('SECRET_KEY', 'DATABASE_URL', 'DATABASE_URL_MIGRATION', 'REDIS_URL', 'PYTHONDONTWRITEBYTECODE')
$before = @{}
foreach ($name in $environmentNames) {
    $before[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    [Environment]::SetEnvironmentVariable('SECRET_KEY', 'P19SyntheticIsolationOnlyAbCd1234567890XyZ987654321', 'Process')
    [Environment]::SetEnvironmentVariable('DATABASE_URL', 'postgresql+asyncpg://unittest:unittest@127.0.0.1:59999/unit_test_only', 'Process')
    [Environment]::SetEnvironmentVariable('DATABASE_URL_MIGRATION', 'postgresql://unittest:unittest@127.0.0.1:59999/unit_test_only', 'Process')
    [Environment]::SetEnvironmentVariable('REDIS_URL', 'redis://127.0.0.1:59998/15', 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')

    Push-Location $backend
    try {
        Write-Output 'P19_SOURCE_BACKEND_START'
        & $python -m pytest -q -p no:cacheprovider tests/test_product_import_inline_correction.py tests/test_product_import_phase11_source_semantics.py tests/test_product_import_phase19_fixture_generator.py tests/test_product_import_phase19_staging_integrity.py tests/test_product_import_phase8_idempotency_correction.py::Phase8CorrectionContractTests tests/test_product_import_phase8_idempotency_correction.py::Phase8ExecutionIdempotencyTests
        Assert-Success 'BACKEND'
    } finally {
        Pop-Location
    }

    Push-Location $dashboard
    try {
        Write-Output 'P19_SOURCE_FRONTEND_START'
        & $vitest run src/test/product-import-inline-editor-p19.test.tsx src/test/product-import-browser-regressions-p19.test.tsx src/test/product-import-correction-file-p19.test.tsx src/test/product-import-rejected-rows-p19.test.tsx src/test/product-import-cancel-command-j.test.tsx src/test/product-import-inflight-file-guard-j.test.tsx src/test/product-import-realtime-lifecycle-j.test.tsx src/test/product-import-receipt.test.tsx src/test/products-import-file-preflight-p9.test.ts src/test/products-import-localization-p6.test.ts src/test/products-tracking-import.test.ts --maxWorkers=1
        Assert-Success 'FRONTEND'
        Write-Output 'P19_SOURCE_TYPESCRIPT_START'
        & $tsc --noEmit -p tsconfig.app.json
        Assert-Success 'TYPESCRIPT'
        Write-Output 'P19_SOURCE_ESLINT_START'
        & $eslint src/hooks/useDialogFocusTrap.ts src/pages/products/header/ProductsAddMenu.tsx src/pages/products/import/useImportProductPolling.ts src/pages/products/import/useImportProductWorkflow.ts src/pages/products/shared/ProductPackagingHelp.tsx src/test/product-import-browser-regressions-p19.test.tsx src/pages/products/import/useImportInlineCorrection.ts src/pages/products/import/ImportInlineCorrectionPanel.tsx src/pages/products/import/ImportInlineCorrectionRow.tsx src/pages/products/import/useImportCorrection.ts src/pages/products/import/correctionRouteGate.ts src/pages/products/import/loadInlineCorrectionRows.ts src/test/product-import-inline-editor-p19.test.tsx src/test/product-import-correction-file-p19.test.tsx src/i18n/resources.ts --max-warnings=0
        Assert-Success 'ESLINT'
        Write-Output 'P19_SOURCE_VITE_START'
        & $vite build
        Assert-Success 'VITE'
    } finally {
        Pop-Location
    }
    Write-Output 'P19_SOURCE_GATE=PASS'
    Write-Output 'P19_SOURCE_GATE_DOES_NOT_PERFORM_HTTP_DB_WORKER_OR_BROWSER=TRUE'
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $before[$name], 'Process')
    }
}
