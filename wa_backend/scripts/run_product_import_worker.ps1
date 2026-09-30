param(
    [ValidateSet("execution", "control", "maintenance")]
    [string]$Role = "execution"
)

$ErrorActionPreference = "Stop"

$BackendRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $BackendRoot

$Python = Join-Path $BackendRoot "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Product Import worker venv Python was not found: $Python"
}

# Each role is a separate supervised foreground process. The Python entrypoint
# owns slot validation, startup recovery and code-version reporting on all OSes.
& $Python -m domains.simple_products.imports.infrastructure.worker_cli --role $Role

exit $LASTEXITCODE
