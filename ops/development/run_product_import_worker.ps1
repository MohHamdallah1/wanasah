param(
    [ValidateSet("execution", "control", "maintenance")]
    [string]$Role = "execution"
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
& (Join-Path $RepoRoot "wa_backend\scripts\run_product_import_worker.ps1") -Role $Role
exit $LASTEXITCODE
