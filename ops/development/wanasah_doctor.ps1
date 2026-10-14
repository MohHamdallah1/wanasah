<#
.SYNOPSIS
    Read-only Windows development environment diagnostic doctor for Wanasah.

.DESCRIPTION
    Inspects repository integrity, Python/backend virtualenv and dependencies,
    backend .env and connection budgets, PostgreSQL binaries/service/connectivity,
    Alembic head vs database revision, Product Import worker configuration and
    Windows localhost vs 127.0.0.1 loopback safety, Dashboard Node/Vite setup,
    Flutter SDK/package/asset setup, runtime TCP ports (5432, 8000, 8080), and
    live Backend /health and /ready endpoints when running.

    READ-ONLY GUARANTEE:
    Never installs packages, starts/stops services or workers, modifies .env or
    registry state, runs cluster creation/migrations/seeds, deletes files, or mutates Git.

    EXIT CODE:
    0 = no blocking environment failures (FAIL == 0)
    1 = at least one blocking environment failure (FAIL > 0, or WARN > 0 with -Strict)
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$Strict,
    [switch]$NoRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:DoctorStatusBadges = @{
    "PASS" = "[PASS]"
    "WARN" = "[WARN]"
    "FAIL" = "[FAIL]"
    "INFO" = "[INFO]"
}

function New-DoctorResult {
    param(
        [Parameter(Mandatory = $true)][string]$Area,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "WARN", "FAIL", "INFO")][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail,
        [string]$Action = ""
    )
    [PSCustomObject]@{
        Area   = $Area
        Name   = $Name
        Status = $Status
        Detail = (Protect-SecretText -Text $Detail)
        Action = (Protect-SecretText -Text $Action)
    }
}

function Protect-SecretText {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return "" }
    $cleaned = $Text
    $cleaned = [regex]::Replace($cleaned, '(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)', '$1***$3')
    $cleaned = [regex]::Replace($cleaned, '(?i)\b(SECRET_KEY|PGPASSWORD|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN|SENTRY_DSN)(\s*[=:]\s*)([^\s,;''"]+)', '$1$2***')
    $cleaned = [regex]::Replace($cleaned, '(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+', '$1***')
    $cleaned = [regex]::Replace($cleaned, '\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b', '[REDACTED_JWT]')
    return $cleaned
}

function Format-SanitizedDsn {
    param([AllowNull()][string]$RawDsn)
    if ($null -eq $RawDsn) { return "<unset>" }
    $trimmed = $RawDsn.Trim()
    if ([string]::IsNullOrEmpty($trimmed)) { return "<empty>" }
    if ($trimmed -match '\$\{[^}]+\}') { return "<unexpanded-template>" }
    if ($trimmed -notmatch '^[A-Za-z][A-Za-z0-9+.-]*://') { return "<malformed-dsn-redacted>" }
    $m = [regex]::Match($trimmed, '^(?<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?:(?<user>[^:/?#\s@]+)(?::[^@#?\s/]*)?@)?(?<host>[^/:?#\s]+)(?::(?<port>\d+))?/(?<db>[^?#\s]*)')
    if (-not $m.Success) { return "<malformed-dsn-redacted>" }
    $scheme = $m.Groups["scheme"].Value
    $user = $m.Groups["user"].Value
    $hostName = $m.Groups["host"].Value
    $port = if ($m.Groups["port"].Success) { $m.Groups["port"].Value } else { "5432" }
    $db = $m.Groups["db"].Value
    $authPrefix = if ([string]::IsNullOrEmpty($user)) { "" } else { "${user}:***@" }
    return "${scheme}://${authPrefix}${hostName}:${port}/${db}"
}

function ConvertFrom-PostgresDsn {
    param([AllowNull()][string]$RawDsn)
    $sanitized = Format-SanitizedDsn -RawDsn $RawDsn
    if ([string]::IsNullOrWhiteSpace($RawDsn)) {
        return [PSCustomObject]@{ Valid = $false; Reason = "missing"; Sanitized = $sanitized }
    }
    $trimmed = $RawDsn.Trim()
    if ($trimmed -match '\$\{[^}]+\}') {
        return [PSCustomObject]@{ Valid = $false; Reason = "interpolated_template"; Sanitized = $sanitized }
    }
    $m = [regex]::Match($trimmed, '^(?<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?:(?<user>[^:/?#\s@]+)(?::(?<pass>[^@#?\s/]*))?@)?(?<host>[^/:?#\s]+)(?::(?<port>\d+))?/(?<db>[^?#\s/]+)(?:\?.*)?$')
    if (-not $m.Success) {
        return [PSCustomObject]@{ Valid = $false; Reason = "malformed_or_incomplete"; Sanitized = "<malformed-dsn-redacted>" }
    }
    $scheme = $m.Groups["scheme"].Value.ToLowerInvariant()
    $validSchemes = @("postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg")
    if ($validSchemes -notcontains $scheme) {
        return [PSCustomObject]@{ Valid = $false; Reason = "unsupported_scheme:$scheme"; Sanitized = $sanitized }
    }
    $portNum = if ($m.Groups["port"].Success) { [int]$m.Groups["port"].Value } else { 5432 }
    return [PSCustomObject]@{
        Valid       = $true
        Scheme      = $scheme
        Host        = $m.Groups["host"].Value
        Port        = $portNum
        Database    = $m.Groups["db"].Value
        Username    = $m.Groups["user"].Value
        HasPassword = ($m.Groups["pass"].Success -and $m.Groups["pass"].Value.Length -gt 0)
        Sanitized   = $sanitized
    }
}

function Read-DotEnvMap {
    param([Parameter(Mandatory = $true)][string]$FilePath)
    $map = @{}
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) { return $map }
    foreach ($rawLine in (Get-Content -LiteralPath $FilePath -Encoding UTF8)) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrEmpty($line) -or $line.StartsWith("#")) { continue }
        if ($line.StartsWith("export ")) { $line = $line.Substring(7).Trim() }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { continue }
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
            $val = $val.Substring(1, $val.Length - 2)
        } elseif ($val.Contains(" #")) {
            $val = $val.Split(@(" #"), 2, [System.StringSplitOptions]::None)[0].Trim()
        }
        $map[$key] = $val
    }
    return $map
}

function Test-OneDriveRepoPath {
    param([Parameter(Mandatory = $true)][string]$PathToCheck)
    if ([string]::IsNullOrWhiteSpace($PathToCheck)) { return $false }
    if ($PathToCheck -match '(?i)(?:^|[\\/])OneDrive(?:\s*-\s*[^\\/]+)?(?:[\\/]|$)') { return $true }
    foreach ($varName in @("OneDrive", "OneDriveCommercial", "OneDriveConsumer")) {
        $odRoot = [Environment]::GetEnvironmentVariable($varName)
        if (-not [string]::IsNullOrWhiteSpace($odRoot)) {
            $normPath = ($PathToCheck -replace '[\\/]+', '/').TrimEnd('/').ToLowerInvariant()
            $normOd = ($odRoot -replace '[\\/]+', '/').TrimEnd('/').ToLowerInvariant()
            if ($normOd.Length -gt 0 -and ($normPath -eq $normOd -or $normPath.StartsWith("$normOd/"))) {
                return $true
            }
        }
    }
    return $false
}

function Test-AlembicIniUrlBlank {
    param([AllowNull()][string]$IniContent)
    if ([string]::IsNullOrEmpty($IniContent)) { return $true }
    $urlMatch = [regex]::Match($IniContent, "(?m)^[ \t]*sqlalchemy\.url[ \t]*=[ \t]*([^\r\n#;]*)")
    if (-not $urlMatch.Success) { return $true }
    return [string]::IsNullOrWhiteSpace($urlMatch.Groups[1].Value)
}

function Get-StaticAlembicHeads {
    param([Parameter(Mandatory = $true)][string]$VersionsDir)
    if (-not (Test-Path -LiteralPath $VersionsDir -PathType Container)) {
        return [PSCustomObject]@{ Ok = $false; Heads = @(); Count = 0 }
    }
    $revs = New-Object 'System.Collections.Generic.HashSet[string]'
    $downRevs = New-Object 'System.Collections.Generic.HashSet[string]'
    $files = @(Get-ChildItem -LiteralPath $VersionsDir -Filter "*.py" -File | Where-Object { -not $_.Name.StartsWith("__") })
    foreach ($file in $files) {
        $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
        $mRev = [regex]::Match($content, '(?m)^revision\s*(?::\s*[^=]+)?=\s*[''"]([^''"]+)[''"]')
        if ($mRev.Success) { [void]$revs.Add($mRev.Groups[1].Value.Trim()) }
        $mDown = [regex]::Match($content, '(?m)^down_revision\s*(?::\s*[^=]+)?=\s*(.+)$')
        if ($mDown.Success) {
            $rawDown = ($mDown.Groups[1].Value -split '#', 2)[0].Trim()
            if ($rawDown -ne "None") {
                foreach ($token in [regex]::Matches($rawDown, '[''"]([^''"]+)[''"]')) {
                    [void]$downRevs.Add($token.Groups[1].Value.Trim())
                }
            }
        }
    }
    $heads = @($revs | Where-Object { -not $downRevs.Contains($_) } | Sort-Object)
    return [PSCustomObject]@{
        Ok    = ($heads.Count -eq 1)
        Heads = $heads
        Count = $revs.Count
    }
}

function Get-ListeningPortInfo {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listening = $false
    $ownerPid = $null
    $procName = $null

    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        try {
            $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
            if ($conns.Count -gt 0) {
                $listening = $true
                $ownerPid = [int]$conns[0].OwningProcess
            }
        } catch { $listening = $false }
    }

    if (-not $listening) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(250, $false) -and $client.Connected) { $listening = $true }
        } catch {
            $listening = $false
        } finally { $client.Close() }
    }

    if ($listening -and $null -ne $ownerPid -and $ownerPid -gt 0) {
        try {
            $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($null -ne $proc) { $procName = $proc.ProcessName }
        } catch { $procName = $null }
    }

    return [PSCustomObject]@{
        Port        = $Port
        Listening   = $listening
        Pid         = $ownerPid
        ProcessName = $procName
    }
}

function Get-PortClassification {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][bool]$Listening,
        [AllowNull()][string]$ProcessName = $null,
        [AllowNull()]$ProcessId = $null
    )
    $proc = if ($null -ne $ProcessName) { $ProcessName.Trim() } else { "" }
    $procLower = $proc.ToLowerInvariant()
    $pidSuffix = if ($null -ne $ProcessId -and $ProcessId -gt 0) {
        " (PID ${ProcessId}: $(if ($proc) { $proc } else { 'unknown' }))"
    } elseif ($proc) {
        " ($proc)"
    } else { "" }

    if ($Port -eq 5432) {
        if (-not $Listening) {
            return [PSCustomObject]@{
                Status = "FAIL"
                Detail = "Port 5432 is FREE (PostgreSQL is not listening)."
                Action = "Start the configured local PostgreSQL instance (Windows service or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
            }
        }
        if ([string]::IsNullOrEmpty($procLower) -or $procLower -match 'postgres|pg_ctl|docker|wslrelay|vpnkit') {
            return [PSCustomObject]@{
                Status = "PASS"
                Detail = "Port 5432 is LISTENING${pidSuffix}."
                Action = ""
            }
        }
        return [PSCustomObject]@{
            Status = "FAIL"
            Detail = "Port 5432 is occupied by unexpected process${pidSuffix}."
            Action = "Free port 5432${pidSuffix} so PostgreSQL can bind to it."
        }
    }

    if ($Port -eq 8000) {
        if (-not $Listening) {
            return [PSCustomObject]@{
                Status = "INFO"
                Detail = "Port 8000 is FREE (Backend FastAPI server is not currently running)."
                Action = ""
            }
        }
        if ([string]::IsNullOrEmpty($procLower) -or $procLower -match 'python|uvicorn') {
            return [PSCustomObject]@{
                Status = "PASS"
                Detail = "Port 8000 is LISTENING${pidSuffix}."
                Action = ""
            }
        }
        return [PSCustomObject]@{
            Status = "FAIL"
            Detail = "Port 8000 is occupied by unexpected process${pidSuffix}."
            Action = "Stop the conflicting process on port 8000${pidSuffix} before starting Uvicorn."
        }
    }

    if ($Port -eq 8080) {
        if (-not $Listening) {
            return [PSCustomObject]@{
                Status = "INFO"
                Detail = "Port 8080 is FREE (Dashboard Vite dev server is not currently running)."
                Action = ""
            }
        }
        if ([string]::IsNullOrEmpty($procLower) -or $procLower -match 'node|bun|deno|vite') {
            return [PSCustomObject]@{
                Status = "PASS"
                Detail = "Port 8080 is LISTENING${pidSuffix}."
                Action = ""
            }
        }
        return [PSCustomObject]@{
            Status = "FAIL"
            Detail = "Port 8080 is occupied by unexpected process${pidSuffix}."
            Action = "Free port 8080${pidSuffix}; dashboard/vite.config.ts requires port 8080."
        }
    }

    return [PSCustomObject]@{
        Status = "INFO"
        Detail = "Port $Port is $(if ($Listening) { 'LISTENING' } else { 'FREE' })${pidSuffix}."
        Action = ""
    }
}

function Invoke-RepoChecks {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $results = @()

    $requiredAnchors = @(
        "wa_backend\main.py",
        "wa_backend\config.py",
        "wa_backend\database.py",
        "dashboard\package.json",
        "wanasah_frontend\pubspec.yaml",
        "ARCHITECTURE.md",
        ".rules"
    )
    $missingAnchors = @()
    foreach ($rel in $requiredAnchors) {
        if (-not (Test-Path -LiteralPath (Join-Path $RootPath $rel))) { $missingAnchors += $rel }
    }

    if ($missingAnchors.Count -eq 0) {
        $results += New-DoctorResult -Area "Repository" -Name "Wanasah repository root" -Status "PASS" -Detail "Verified canonical repository structure at '$RootPath'."
    } else {
        $results += New-DoctorResult -Area "Repository" -Name "Wanasah repository root" -Status "FAIL" -Detail "Missing expected repository files: $($missingAnchors -join ', ')." -Action "Run .\ops\development\wanasah_doctor.ps1 from a complete Wanasah repository checkout."
    }

    $cwd = (Get-Location).Path
    if ($cwd.TrimEnd('\', '/') -ne $RootPath.TrimEnd('\', '/')) {
        $results += New-DoctorResult -Area "Repository" -Name "Working directory" -Status "WARN" -Detail "Current directory is '$cwd' (not repo root '$RootPath')." -Action "Set-Location '$RootPath' before running Wanasah startup commands."
    }

    if (Test-OneDriveRepoPath -PathToCheck $RootPath) {
        $results += New-DoctorResult -Area "Repository" -Name "OneDrive path check" -Status "WARN" -Detail "Repository path '$RootPath' is inside a OneDrive-synced folder (file locks can corrupt venv, node_modules, and Flutter .dart_tool)." -Action "Move the repository to a local non-OneDrive directory such as C:\dev\wanasah."
    } else {
        $results += New-DoctorResult -Area "Repository" -Name "OneDrive path check" -Status "PASS" -Detail "Repository path is outside OneDrive."
    }

    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $gitCmd) {
        $results += New-DoctorResult -Area "Repository" -Name "Git executable & branch" -Status "WARN" -Detail "git executable was not found on PATH; worker_cli.py requires git rev-parse HEAD unless WANASAH_RELEASE_COMMIT is set." -Action "Install Git for Windows and ensure 'git' is on PATH."
        return $results
    }

    $gitDir = Join-Path $RootPath ".git"
    if (-not (Test-Path -LiteralPath $gitDir)) {
        $results += New-DoctorResult -Area "Repository" -Name "Git worktree metadata" -Status "WARN" -Detail ".git directory not found in '$RootPath' (extracted archive or detached copy; worker_cli.py requires git rev-parse HEAD or WANASAH_RELEASE_COMMIT)." -Action "Use a Git clone of MohHamdallah1/wanasah or set WANASAH_RELEASE_COMMIT to a 40-char SHA."
        return $results
    }

    $branch = (& git -C $RootPath rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
    $headSha = (& git -C $RootPath rev-parse --short HEAD 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and $branch) {
        if ($branch -eq "main") {
            $results += New-DoctorResult -Area "Repository" -Name "Git branch" -Status "WARN" -Detail "Current branch is 'main' ($headSha). ARCHITECTURE.md forbids direct edits on main." -Action "Switch to a dedicated task branch before making changes."
        } else {
            $results += New-DoctorResult -Area "Repository" -Name "Git branch" -Status "PASS" -Detail "Active branch '$branch' at commit $headSha."
        }
    } else {
        $results += New-DoctorResult -Area "Repository" -Name "Git branch" -Status "WARN" -Detail "Could not resolve current Git branch/HEAD." -Action "Inspect git status in '$RootPath'."
    }

    $porcelain = @(& git -C $RootPath status --porcelain 2>$null | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($porcelain.Count -gt 0) {
        $results += New-DoctorResult -Area "Repository" -Name "Working tree cleanliness" -Status "WARN" -Detail "Working tree has $($porcelain.Count) uncommitted/untracked path(s)." -Action "Run 'git status' to review local changes before pulling or switching branches."
    } else {
        $results += New-DoctorResult -Area "Repository" -Name "Working tree cleanliness" -Status "PASS" -Detail "Working tree is clean."
    }

    return $results
}

function Invoke-PythonBackendChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [AllowNull()]$ProbeData = $null
    )
    $results = @()
    $backendRoot = Join-Path $RootPath "wa_backend"
    $venvDir = Join-Path $backendRoot "venv"
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    $pyvenvCfg = Join-Path $venvDir "pyvenv.cfg"

    if (-not (Test-Path -LiteralPath $venvDir -PathType Container)) {
        $results += New-DoctorResult -Area "Python/Backend" -Name "Backend virtualenv (wa_backend\venv)" -Status "FAIL" -Detail "Directory 'wa_backend\venv' does not exist." -Action "Recreate backend venv in wa_backend: py -3.12 -m venv wa_backend\venv and populate packages from wa_backend\requirements.txt."
    } elseif (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $results += New-DoctorResult -Area "Python/Backend" -Name "Backend venv Python executable" -Status "FAIL" -Detail "Missing '$venvPython' (all worker launchers require wa_backend\venv\Scripts\python.exe)." -Action "Recreate wa_backend\venv using Python 3.12+ on Windows."
    } else {
        $staleHome = $null
        if (Test-Path -LiteralPath $pyvenvCfg -PathType Leaf) {
            foreach ($line in (Get-Content -LiteralPath $pyvenvCfg -Encoding UTF8)) {
                if ($line -match '^\s*home\s*=\s*(.+)$') {
                    $homeDir = $matches[1].Trim()
                    if (-not (Test-Path -LiteralPath $homeDir -PathType Container)) { $staleHome = $homeDir }
                }
            }
        }
        if ($null -ne $staleHome) {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Backend venv Python executable" -Status "FAIL" -Detail "wa_backend\venv\pyvenv.cfg points to missing base Python directory '$staleHome' (stale venv after machine reformat or move)." -Action "Rebuild wa_backend\venv with the current machine's Python 3.12+ interpreter."
        } else {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Backend venv Python executable" -Status "PASS" -Detail "Found '$venvPython'."
        }
    }

    if ($null -ne $ProbeData -and $null -ne $ProbeData.python) {
        $pyVer = [string]$ProbeData.python.version
        if ([bool]$ProbeData.python.compatible) {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Python version compatibility" -Status "PASS" -Detail "Python $pyVer (>= 3.12 required for asyncio.run loop_factory in worker_cli.py/recover_cli.py)."
        } else {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Python version compatibility" -Status "FAIL" -Detail "Python $pyVer is too old; Wanasah requires Python >= 3.12 (asyncio.run loop_factory is used on Windows)." -Action "Install Python 3.12+ and recreate wa_backend\venv."
        }

        $reqs = $ProbeData.requirements
        if ($null -ne $reqs) {
            $missingList = @($reqs.missing)
            $mismatchList = @($reqs.mismatched)
            if ($missingList.Count -gt 0) {
                $results += New-DoctorResult -Area "Python/Backend" -Name "Backend requirements.txt dependencies" -Status "FAIL" -Detail "Missing $($missingList.Count) required package(s): $($missingList -join ', ')." -Action "Sync backend dependencies into wa_backend\venv from wa_backend\requirements.txt."
            } elseif ($mismatchList.Count -gt 0) {
                $results += New-DoctorResult -Area "Python/Backend" -Name "Backend requirements.txt dependencies" -Status "WARN" -Detail "All $($reqs.checked) required packages are installed, but version drift detected: $($mismatchList -join '; ')." -Action "Align wa_backend\venv package versions with wa_backend\requirements.txt."
            } else {
                $results += New-DoctorResult -Area "Python/Backend" -Name "Backend requirements.txt dependencies" -Status "PASS" -Detail "All $($reqs.checked) pinned packages in wa_backend/requirements.txt are installed and match expected versions."
            }
        }
    } else {
        $sysPy = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $sysPy) {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Python interpreter discovery" -Status "FAIL" -Detail "Neither wa_backend\venv\Scripts\python.exe nor system 'python' could be executed." -Action "Install Python 3.12+ (64-bit) on Windows and create wa_backend\venv."
        } else {
            $results += New-DoctorResult -Area "Python/Backend" -Name "Backend dependency probe" -Status "WARN" -Detail "Skipped in-venv dependency verification because wa_backend\venv\Scripts\python.exe is unavailable." -Action "Create wa_backend\venv and populate packages from wa_backend\requirements.txt."
        }
    }

    return $results
}

function Invoke-BackendEnvChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [AllowNull()]$ProbeData = $null
    )
    $results = @()
    $envPath = Join-Path $RootPath "wa_backend\.env"
    $envMap = Read-DotEnvMap -FilePath $envPath

    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        $results += New-DoctorResult -Area "Backend Env" -Name "wa_backend/.env file" -Status "FAIL" -Detail "Missing 'wa_backend\.env' (config.py loads wa_backend\.env and requires SECRET_KEY and DATABASE_URL)." -Action "Create wa_backend\.env with SECRET_KEY (>=32 chars, mixed case + digits), DATABASE_URL, and DATABASE_URL_MIGRATION."
    } else {
        $results += New-DoctorResult -Area "Backend Env" -Name "wa_backend/.env file" -Status "PASS" -Detail "Found 'wa_backend\.env' ($($envMap.Keys.Count) key(s) declared)."
    }

    $conflicts = @()
    foreach ($k in @("DATABASE_URL", "DATABASE_URL_MIGRATION", "SECRET_KEY")) {
        $procVal = [Environment]::GetEnvironmentVariable($k)
        if (-not [string]::IsNullOrEmpty($procVal) -and $envMap.ContainsKey($k) -and $procVal -ne $envMap[$k]) {
            $conflicts += $k
        }
    }
    if ($conflicts.Count -gt 0) {
        $results += New-DoctorResult -Area "Backend Env" -Name "Process env vs .env override check" -Status "WARN" -Detail "Inherited environment variable(s) [$($conflicts -join ', ')] differ from wa_backend\.env (load_dotenv override=False means process env silently wins)." -Action "Clear stale User/System/Process environment variables for $($conflicts -join ', ') so wa_backend\.env is authoritative."
    }

    $secretKey = if ([Environment]::GetEnvironmentVariable("SECRET_KEY")) {
        [Environment]::GetEnvironmentVariable("SECRET_KEY")
    } elseif ($envMap.ContainsKey("SECRET_KEY")) {
        $envMap["SECRET_KEY"]
    } else { "" }
    if ([string]::IsNullOrEmpty($secretKey)) {
        $results += New-DoctorResult -Area "Backend Env" -Name "SECRET_KEY policy (S-08)" -Status "FAIL" -Detail "SECRET_KEY is missing (config.py refuses startup without SECRET_KEY)." -Action "Set SECRET_KEY in wa_backend\.env (at least 32 chars with uppercase, lowercase, and digits)."
    } elseif ($secretKey.Length -lt 32 -or $secretKey -notmatch '[A-Z]' -or $secretKey -notmatch '[a-z]' -or $secretKey -notmatch '[0-9]') {
        $results += New-DoctorResult -Area "Backend Env" -Name "SECRET_KEY policy (S-08)" -Status "FAIL" -Detail "SECRET_KEY fails config.py S-08 policy (length=$($secretKey.Length); requires >=32 chars with upper, lower, and digits; value redacted)." -Action "Update SECRET_KEY in wa_backend\.env to a strong >=32-character mixed-case alphanumeric secret."
    } else {
        $results += New-DoctorResult -Area "Backend Env" -Name "SECRET_KEY policy (S-08)" -Status "PASS" -Detail "SECRET_KEY satisfies config.py length and complexity requirements (value redacted)."
    }

    $rawDbUrl = if ([Environment]::GetEnvironmentVariable("DATABASE_URL")) {
        [Environment]::GetEnvironmentVariable("DATABASE_URL")
    } elseif ($envMap.ContainsKey("DATABASE_URL")) {
        $envMap["DATABASE_URL"]
    } else { "" }
    $rawMigUrl = if ([Environment]::GetEnvironmentVariable("DATABASE_URL_MIGRATION")) {
        [Environment]::GetEnvironmentVariable("DATABASE_URL_MIGRATION")
    } elseif ($envMap.ContainsKey("DATABASE_URL_MIGRATION")) {
        $envMap["DATABASE_URL_MIGRATION"]
    } else { "" }

    $dbInfo = ConvertFrom-PostgresDsn -RawDsn $rawDbUrl
    if (-not $dbInfo.Valid) {
        $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL configuration" -Status "FAIL" -Detail "DATABASE_URL is invalid or missing ($($dbInfo.Reason)): $($dbInfo.Sanitized)." -Action "Set DATABASE_URL in wa_backend\.env (e.g. postgresql+asyncpg://wanasah_app:<password>@127.0.0.1:5432/wanasah_local)."
    } else {
        $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL configuration" -Status "PASS" -Detail "DATABASE_URL -> $($dbInfo.Sanitized)."
    }

    if ([string]::IsNullOrWhiteSpace($rawMigUrl)) {
        $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL_MIGRATION configuration" -Status "INFO" -Detail "DATABASE_URL_MIGRATION is not set; alembic/env.py uses DATABASE_URL as the valid migration target (explicit DATABASE_URL_MIGRATION is only needed for specialized D8 audit scripts)."
    } else {
        $migInfo = ConvertFrom-PostgresDsn -RawDsn $rawMigUrl
        if (-not $migInfo.Valid) {
            $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL_MIGRATION configuration" -Status "FAIL" -Detail "DATABASE_URL_MIGRATION is malformed ($($migInfo.Reason)): $($migInfo.Sanitized)." -Action "Fix DATABASE_URL_MIGRATION in wa_backend\.env."
        } elseif ($dbInfo.Valid -and (($dbInfo.Host.ToLowerInvariant() -ne $migInfo.Host.ToLowerInvariant()) -or ($dbInfo.Port -ne $migInfo.Port) -or ($dbInfo.Database -ne $migInfo.Database))) {
            $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL_MIGRATION target match" -Status "FAIL" -Detail "DATABASE_URL ($($dbInfo.Sanitized)) and DATABASE_URL_MIGRATION ($($migInfo.Sanitized)) point to different host/port/database targets." -Action "Align DATABASE_URL and DATABASE_URL_MIGRATION in wa_backend\.env to the same PostgreSQL instance and database."
        } else {
            $results += New-DoctorResult -Area "Backend Env" -Name "DATABASE_URL_MIGRATION configuration" -Status "PASS" -Detail "DATABASE_URL_MIGRATION -> $($migInfo.Sanitized) (matches runtime target)."
        }
    }

    if ($null -ne $ProbeData -and $null -ne $ProbeData.env -and $null -ne $ProbeData.env.budget_errors) {
        $bErrs = @($ProbeData.env.budget_errors)
        if ($bErrs.Count -gt 0) {
            $results += New-DoctorResult -Area "Backend Env" -Name "PostgreSQL connection budget contract" -Status "FAIL" -Detail "Connection budget violation: $($bErrs -join ' ')" -Action "Check WEB_CONCURRENCY, DB_POOL_SIZE, DB_APP_CONNECTION_BUDGET, and DB_DEPLOYMENT_CONNECTION_BUDGET in wa_backend\.env."
        } else {
            $results += New-DoctorResult -Area "Backend Env" -Name "PostgreSQL connection budget contract" -Status "PASS" -Detail "Web, Operational Worker, and Product Import connection budgets satisfy config.py invariants."
        }
    }

    return $results
}

function Find-PostgresBinaries {
    $found = @{}
    $searchDirs = @()
    foreach ($pgBase in @("C:\Tools\PostgreSQL", "C:\Program Files\PostgreSQL")) {
        if (Test-Path -LiteralPath $pgBase -PathType Container) {
            $verDirs = @(Get-ChildItem -LiteralPath $pgBase -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)
            foreach ($d in $verDirs) {
                foreach ($sub in @("pgsql\bin", "bin")) {
                    $binCandidate = Join-Path $d.FullName $sub
                    if (Test-Path -LiteralPath $binCandidate -PathType Container) { $searchDirs += $binCandidate }
                }
            }
        }
    }
    foreach ($tool in @("psql", "postgres", "pg_ctl", "pg_isready")) {
        $cmd = Get-Command $tool -ErrorAction SilentlyContinue
        if ($null -ne $cmd -and $cmd.Source) {
            $found[$tool] = $cmd.Source
            continue
        }
        foreach ($dir in $searchDirs) {
            $exe = Join-Path $dir "${tool}.exe"
            if (Test-Path -LiteralPath $exe -PathType Leaf) {
                $found[$tool] = $exe
                break
            }
        }
    }
    return $found
}

function Invoke-PostgresChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)]$Port5432Info,
        [Parameter(Mandatory = $true)][hashtable]$PgBinaries,
        [AllowNull()]$ProbeData = $null
    )
    $results = @()
    $hasBins = ($PgBinaries.Keys.Count -gt 0)

    if ($PgBinaries.ContainsKey("psql") -and $PgBinaries.ContainsKey("pg_ctl")) {
        $binDir = Split-Path -Parent $PgBinaries["psql"]
        $results += New-DoctorResult -Area "PostgreSQL" -Name "PostgreSQL binaries (psql/postgres/pg_ctl)" -Status "PASS" -Detail "Found PostgreSQL binaries in '$binDir' ($($PgBinaries.Keys -join ', '))."
    } elseif ($hasBins) {
        $results += New-DoctorResult -Area "PostgreSQL" -Name "PostgreSQL binaries (psql/postgres/pg_ctl)" -Status "WARN" -Detail "Partial PostgreSQL binaries found ($($PgBinaries.Keys -join ', '))." -Action "Ensure PostgreSQL 16 bin directory (C:\Program Files\PostgreSQL\16\bin) is installed and on PATH."
    } else {
        $statusIfMissing = if ($Port5432Info.Listening) { "WARN" } else { "FAIL" }
        $results += New-DoctorResult -Area "PostgreSQL" -Name "PostgreSQL binaries (psql/postgres/pg_ctl)" -Status $statusIfMissing -Detail "psql, postgres, and pg_ctl were not found on PATH or under 'C:\Program Files\PostgreSQL\*\bin'." -Action "Install PostgreSQL 16 or add 'C:\Program Files\PostgreSQL\16\bin' to PATH."
    }

    if (Get-Command Get-Service -ErrorAction SilentlyContinue) {
        try {
            $pgServices = @(Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue)
            if ($pgServices.Count -gt 0) {
                $svcSummary = @($pgServices | ForEach-Object { "$($_.Name)=$($_.Status)" }) -join ", "
                $anyRunning = @($pgServices | Where-Object { $_.Status -eq "Running" }).Count -gt 0
                if ($anyRunning) {
                    $results += New-DoctorResult -Area "PostgreSQL" -Name "Windows PostgreSQL service" -Status "PASS" -Detail "Detected Windows service(s): $svcSummary."
                } elseif ($Port5432Info.Listening) {
                    $results += New-DoctorResult -Area "PostgreSQL" -Name "Windows PostgreSQL service" -Status "INFO" -Detail "Windows service is not running ($svcSummary), but port 5432 is active via a custom/pg_ctl PostgreSQL instance."
                } else {
                    $results += New-DoctorResult -Area "PostgreSQL" -Name "Windows PostgreSQL service" -Status "FAIL" -Detail "Windows PostgreSQL service is not running ($svcSummary) and port 5432 is not listening." -Action "Start the configured local PostgreSQL instance (Windows service or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
                }
            }
        } catch {
            # Ignore service enumeration errors on non-Windows or restricted shells
        }
    }

    if ($Port5432Info.Listening) {
        $results += New-DoctorResult -Area "PostgreSQL" -Name "Port 5432 listener" -Status "PASS" -Detail "TCP port 5432 is listening."
    } else {
        $diagStatus = if ($hasBins) { "SERVER_NOT_RUNNING" } else { "BINARIES_MISSING" }
        $results += New-DoctorResult -Area "PostgreSQL" -Name "Port 5432 listener" -Status "FAIL" -Detail "TCP port 5432 is not listening [$diagStatus]." -Action "Start the configured local PostgreSQL instance (Windows service or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
    }

    if ($null -ne $ProbeData -and $null -ne $ProbeData.db_probe) {
        $dbp = $ProbeData.db_probe
        if ([bool]$dbp.connected) {
            $maxC = $dbp.max_connections
            $resC = $dbp.superuser_reserved_connections
            $results += New-DoctorResult -Area "PostgreSQL" -Name "Database connectivity (READ ONLY)" -Status "PASS" -Detail "Connected cleanly in READ ONLY mode (max_connections=$maxC, superuser_reserved=$resC)."
            if (-not [bool]$dbp.headroom_ok) {
                $results += New-DoctorResult -Area "PostgreSQL" -Name "PostgreSQL max_connections headroom" -Status "WARN" -Detail "DB_DEPLOYMENT_CONNECTION_BUDGET exceeds available non-superuser connections (max_connections=$maxC, reserved=$resC)." -Action "Increase PostgreSQL max_connections (>=100) or lower DB_DEPLOYMENT_CONNECTION_BUDGET in wa_backend\.env."
            }
        } elseif ($null -ne $dbp.classification) {
            $cls = $dbp.classification
            $results += New-DoctorResult -Area "PostgreSQL" -Name "Database connectivity [$($cls.category)]" -Status ([string]$cls.status) -Detail ([string]$cls.summary) -Action ([string]$cls.action)
        }
    } elseif (-not $Port5432Info.Listening) {
        $category = if ($hasBins) { "SERVER_NOT_RUNNING" } else { "BINARIES_MISSING" }
        $msg = if ($hasBins) {
            "PostgreSQL binaries exist, but the server is not running on port 5432."
        } else { "PostgreSQL binaries are missing and no server is listening on port 5432." }
        $act = if ($hasBins) {
            "Start the configured local PostgreSQL instance (Windows service or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
        } else { "Install PostgreSQL 16 and start its Windows service." }
        $results += New-DoctorResult -Area "PostgreSQL" -Name "Database connectivity [$category]" -Status "FAIL" -Detail $msg -Action $act
    } else {
        $results += New-DoctorResult -Area "PostgreSQL" -Name "Database connectivity" -Status "WARN" -Detail "Port 5432 is listening, but full SQL authentication/database probe requires wa_backend\venv\Scripts\python.exe (with psycopg)." -Action "Recreate wa_backend\venv and rerun .\ops\development\wanasah_doctor.ps1 to verify DB credentials and target database."
    }

    return $results
}

function Invoke-AlembicChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [AllowNull()]$ProbeData = $null
    )
    $results = @()
    $alembicIni = Join-Path $RootPath "wa_backend\alembic.ini"
    $alembicEnv = Join-Path $RootPath "wa_backend\alembic\env.py"
    $versionsDir = Join-Path $RootPath "wa_backend\alembic\versions"

    if (-not (Test-Path -LiteralPath $alembicIni -PathType Leaf) -or -not (Test-Path -LiteralPath $alembicEnv -PathType Leaf)) {
        $results += New-DoctorResult -Area "Alembic" -Name "Alembic configuration files" -Status "FAIL" -Detail "Missing wa_backend\alembic.ini or wa_backend\alembic\env.py." -Action "Restore wa_backend\alembic.ini and wa_backend\alembic\env.py from Git."
        return $results
    }

    $iniContent = Get-Content -LiteralPath $alembicIni -Raw -Encoding UTF8
    if (-not (Test-AlembicIniUrlBlank -IniContent $iniContent)) {
        $results += New-DoctorResult -Area "Alembic" -Name "alembic.ini credential guard" -Status "FAIL" -Detail "wa_backend/alembic.ini has a non-empty sqlalchemy.url (violates repository security rule: DB URL must come from environment only)." -Action "Clear sqlalchemy.url in wa_backend\alembic.ini and set DATABASE_URL_MIGRATION in wa_backend\.env."
    } else {
        $results += New-DoctorResult -Area "Alembic" -Name "Alembic configuration availability" -Status "PASS" -Detail "wa_backend/alembic.ini and alembic/env.py present; sqlalchemy.url is safely blank."
    }

    $headInfo = Get-StaticAlembicHeads -VersionsDir $versionsDir
    if (-not $headInfo.Ok) {
        $results += New-DoctorResult -Area "Alembic" -Name "Repository migration head" -Status "FAIL" -Detail "Expected 1 linear Alembic head in wa_backend/alembic/versions ($($headInfo.Count) files), found $($headInfo.Heads.Count): $($headInfo.Heads -join ', ')." -Action "Inspect wa_backend\alembic\versions for diverged or missing migration files."
        return $results
    }
    $repoHead = $headInfo.Heads[0]
    $results += New-DoctorResult -Area "Alembic" -Name "Repository migration head" -Status "PASS" -Detail "Repository has 1 head revision '$repoHead' across $($headInfo.Count) migrations."

    if ($null -ne $ProbeData -and $null -ne $ProbeData.db_probe -and [bool]$ProbeData.db_probe.connected) {
        $dbp = $ProbeData.db_probe
        if (-not [bool]$dbp.has_alembic_table) {
            $results += New-DoctorResult -Area "Alembic" -Name "Database revision vs head" -Status "FAIL" -Detail "Connected database has no 'alembic_version' table (expected head '$repoHead')." -Action "Inspect target DB in wa_backend\.env and apply repository migrations to the intended development database."
        } else {
            $dbRevs = @($dbp.db_revisions)
            $dbRevStr = if ($dbRevs.Count -gt 0) { $dbRevs -join ", " } else { "<empty>" }
            if ([bool]$dbp.alembic_matches_head) {
                $results += New-DoctorResult -Area "Alembic" -Name "Database revision vs head" -Status "PASS" -Detail "Database alembic_version '$dbRevStr' matches repository head '$repoHead'."
            } else {
                $results += New-DoctorResult -Area "Alembic" -Name "Database revision vs head" -Status "FAIL" -Detail "Database alembic_version is '$dbRevStr', which differs from repository head '$repoHead'." -Action "Review pending migrations in wa_backend (.\venv\Scripts\python.exe -m alembic current / heads) before starting Backend or workers."
            }
        }
    } else {
        $results += New-DoctorResult -Area "Alembic" -Name "Database revision vs head" -Status "INFO" -Detail "Skipped live alembic_version table comparison because PostgreSQL is not currently connected (repo head is '$repoHead')."
    }

    return $results
}

function Invoke-ProductImportChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [AllowNull()]$ProbeData = $null
    )
    $results = @()

    $opsWrapper = Join-Path $RootPath "ops\development\run_product_import_worker.ps1"
    $backendLauncher = Join-Path $RootPath "wa_backend\scripts\run_product_import_worker.ps1"
    $workerCli = Join-Path $RootPath "wa_backend\domains\simple_products\imports\infrastructure\worker_cli.py"
    $queueDsn = Join-Path $RootPath "wa_backend\domains\simple_products\imports\infrastructure\queue_dsn.py"

    if ((Test-Path -LiteralPath $opsWrapper) -and (Test-Path -LiteralPath $backendLauncher) -and (Test-Path -LiteralPath $workerCli) -and (Test-Path -LiteralPath $queueDsn)) {
        $results += New-DoctorResult -Area "Product Import" -Name "Worker launchers & 3-role topology" -Status "PASS" -Detail "Verified ops wrapper, scripts launcher, worker_cli.py (roles: execution, control, maintenance), and queue_dsn.py."
    } else {
        $results += New-DoctorResult -Area "Product Import" -Name "Worker launchers & 3-role topology" -Status "FAIL" -Detail "One or more Product Import worker entrypoints are missing under ops/development or wa_backend." -Action "Restore Product Import launcher scripts from Git."
    }

    $envPath = Join-Path $RootPath "wa_backend\.env"
    $envMap = Read-DotEnvMap -FilePath $envPath
    $rawDbUrl = if ([Environment]::GetEnvironmentVariable("DATABASE_URL")) {
        [Environment]::GetEnvironmentVariable("DATABASE_URL")
    } elseif ($envMap.ContainsKey("DATABASE_URL")) {
        $envMap["DATABASE_URL"]
    } else { "" }
    $rawMigUrl = if ([Environment]::GetEnvironmentVariable("DATABASE_URL_MIGRATION")) {
        [Environment]::GetEnvironmentVariable("DATABASE_URL_MIGRATION")
    } elseif ($envMap.ContainsKey("DATABASE_URL_MIGRATION")) {
        $envMap["DATABASE_URL_MIGRATION"]
    } else { "" }

    $dbInfo = ConvertFrom-PostgresDsn -RawDsn $rawDbUrl
    $migInfo = ConvertFrom-PostgresDsn -RawDsn $rawMigUrl
    $usesLocalhost = ($dbInfo.Valid -and $dbInfo.Host.ToLowerInvariant() -eq "localhost") -or ($migInfo.Valid -and $migInfo.Host.ToLowerInvariant() -eq "localhost")

    if ($usesLocalhost) {
        $results += New-DoctorResult -Area "Product Import" -Name "Windows localhost vs 127.0.0.1 loopback check" -Status "WARN" -Detail "DATABASE_URL / DATABASE_URL_MIGRATION uses host 'localhost'. Product Import queue_dsn.py rewrites 'localhost' -> '127.0.0.1' on Windows (to prevent psycopg async pool AddConnection hangs), whereas workers/app.py (Operational/Reports PsycopgConnector), database.py, and alembic/env.py keep 'localhost'." -Action "Replace 'localhost' with '127.0.0.1' in DATABASE_URL and DATABASE_URL_MIGRATION inside wa_backend\.env for consistent IPv4 loopback behavior across all workers."
    } elseif ($dbInfo.Valid) {
        $results += New-DoctorResult -Area "Product Import" -Name "Windows localhost vs 127.0.0.1 loopback check" -Status "PASS" -Detail "Database DSN uses explicit host '$($dbInfo.Host)' (no Windows localhost vs 127.0.0.1 split between Product Import and Operational/API pools)."
    } else {
        $results += New-DoctorResult -Area "Product Import" -Name "Windows localhost vs 127.0.0.1 loopback check" -Status "INFO" -Detail "Configure DATABASE_URL with host '127.0.0.1' (not 'localhost') in wa_backend\.env to avoid Windows psycopg pool resolver hangs."
    }

    if ($null -ne $ProbeData -and $null -ne $ProbeData.db_probe -and [bool]$ProbeData.db_probe.connected) {
        $dbp = $ProbeData.db_probe
        $missingRls = @($dbp.missing_force_rls_tables)
        if ($missingRls.Count -gt 0) {
            $results += New-DoctorResult -Area "Product Import" -Name "Product Import table FORCE RLS" -Status "FAIL" -Detail "Missing FORCE RLS on table(s): $($missingRls -join ', ')." -Action "Ensure all Product Import and Catalog migrations up to repository head are applied."
        } else {
            $results += New-DoctorResult -Area "Product Import" -Name "Product Import table FORCE RLS" -Status "PASS" -Detail "All 6 required Product Import/Catalog tables have PostgreSQL FORCE RLS enabled."
        }

        $roles = @($dbp.observed_import_roles)
        if ($roles.Count -eq 0) {
            $results += New-DoctorResult -Area "Product Import" -Name "Active Product Import worker roles" -Status "INFO" -Detail "No Product Import worker roles currently connected (expected when not actively testing imports; start execution, control, and maintenance roles when needed)."
        } elseif ($roles.Count -lt 3) {
            $results += New-DoctorResult -Area "Product Import" -Name "Active Product Import worker roles" -Status "WARN" -Detail "Partial Product Import worker topology connected ($($roles -join ', ')); RUNBOOK.md requires execution, control, and maintenance roles together." -Action "Run .\ops\development\run_product_import_worker.ps1 for each missing role (-Role execution, -Role control, -Role maintenance)."
        } else {
            $results += New-DoctorResult -Area "Product Import" -Name "Active Product Import worker roles" -Status "PASS" -Detail "All 3 Product Import worker roles (execution, control, maintenance) are connected."
        }
    }

    return $results
}

function Invoke-DashboardChecks {
    param(
        [Parameter(Mandatory = $true)][string]$RootPath,
        [Parameter(Mandatory = $true)]$Port8000Info
    )
    $results = @()
    $dashRoot = Join-Path $RootPath "dashboard"
    $pkgJson = Join-Path $dashRoot "package.json"
    $nodeModules = Join-Path $dashRoot "node_modules"
    $viteCmd = Join-Path $nodeModules ".bin\vite.cmd"
    $viteBinPosix = Join-Path $nodeModules ".bin\vite"

    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue

    if ($null -eq $nodeCmd) {
        $results += New-DoctorResult -Area "Dashboard" -Name "Node.js executable" -Status "FAIL" -Detail "'node' was not found on PATH." -Action "Install Node.js LTS (v20+) on Windows and ensure 'node' and 'npm' are on PATH."
    } else {
        $nodeVer = (& node --version 2>$null | Out-String).Trim()
        $results += New-DoctorResult -Area "Dashboard" -Name "Node.js executable" -Status "PASS" -Detail "Found node $nodeVer ($($nodeCmd.Source))."
    }

    if ($null -eq $npmCmd) {
        $results += New-DoctorResult -Area "Dashboard" -Name "npm executable" -Status "FAIL" -Detail "'npm' was not found on PATH." -Action "Ensure npm is installed with Node.js and available on PATH."
    } else {
        $npmVer = (& npm --version 2>$null | Out-String).Trim()
        $results += New-DoctorResult -Area "Dashboard" -Name "npm executable" -Status "PASS" -Detail "Found npm $npmVer."
    }

    if (-not (Test-Path -LiteralPath $pkgJson -PathType Leaf)) {
        $results += New-DoctorResult -Area "Dashboard" -Name "dashboard/package.json" -Status "FAIL" -Detail "Missing 'dashboard\package.json'." -Action "Restore dashboard\package.json from Git."
    } elseif (-not (Test-Path -LiteralPath $nodeModules -PathType Container) -or (-not (Test-Path -LiteralPath $viteCmd) -and -not (Test-Path -LiteralPath $viteBinPosix))) {
        $results += New-DoctorResult -Area "Dashboard" -Name "dashboard/node_modules" -Status "FAIL" -Detail "Missing 'dashboard\node_modules' or Vite binary (.bin\vite.cmd)." -Action "Populate dashboard dependencies inside the 'dashboard' directory."
    } else {
        $results += New-DoctorResult -Area "Dashboard" -Name "dashboard/node_modules" -Status "PASS" -Detail "Found 'dashboard\node_modules' and local Vite toolchain binaries."
    }

    $dashEnvFiles = @(".env.development.local", ".env.local", ".env.development", ".env")
    $viteApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL")
    $viteSource = if (-not [string]::IsNullOrWhiteSpace($viteApiUrl)) { "process env" } else { $null }
    $foundEnvFiles = @()

    foreach ($ef in $dashEnvFiles) {
        $fullEf = Join-Path $dashRoot $ef
        if (Test-Path -LiteralPath $fullEf -PathType Leaf) {
            $foundEnvFiles += $ef
            $parsedEf = Read-DotEnvMap -FilePath $fullEf
            if ([string]::IsNullOrWhiteSpace($viteApiUrl) -and $parsedEf.ContainsKey("VITE_API_URL") -and -not [string]::IsNullOrWhiteSpace($parsedEf["VITE_API_URL"])) {
                $viteApiUrl = $parsedEf["VITE_API_URL"]
                $viteSource = "dashboard\$ef"
            }
        }
    }

    if ([string]::IsNullOrWhiteSpace($viteApiUrl)) {
        $envFileNote = if ($foundEnvFiles.Count -eq 0) { "no dashboard\.env* file exists" } else { "checked $($foundEnvFiles -join ', ')" }
        $results += New-DoctorResult -Area "Dashboard" -Name "VITE_API_URL configuration" -Status "FAIL" -Detail "VITE_API_URL is not set ($envFileNote). dashboard/src/hooks/useAuthFetch.ts throws 'Error: VITE_API_URL is not set.' at module load!" -Action "Create dashboard\.env containing VITE_API_URL=http://127.0.0.1:8000."
    } else {
        $trimmedUrl = $viteApiUrl.Trim()
        $uri = $null
        $isValidUri = [System.Uri]::TryCreate($trimmedUrl, [System.UriKind]::Absolute, [ref]$uri)
        if (-not $isValidUri -or ($uri.Scheme -ne "http" -and $uri.Scheme -ne "https")) {
            $results += New-DoctorResult -Area "Dashboard" -Name "VITE_API_URL configuration" -Status "FAIL" -Detail "VITE_API_URL '$trimmedUrl' ($viteSource) is not a valid http/https URL." -Action "Set VITE_API_URL=http://127.0.0.1:8000 in dashboard\.env."
        } elseif ($uri.Port -eq 8080 -and ($uri.Host -eq "localhost" -or $uri.Host -eq "127.0.0.1")) {
            $results += New-DoctorResult -Area "Dashboard" -Name "VITE_API_URL configuration" -Status "FAIL" -Detail "VITE_API_URL '$trimmedUrl' ($viteSource) points to port 8080 (the Vite dev server itself) instead of Backend port 8000." -Action "Change VITE_API_URL to http://127.0.0.1:8000 in $viteSource."
        } else {
            $results += New-DoctorResult -Area "Dashboard" -Name "VITE_API_URL configuration" -Status "PASS" -Detail "VITE_API_URL='$trimmedUrl' (from $viteSource)."
            if ($uri.Host -notin @("127.0.0.1", "localhost") -and $uri.Host -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[0-1])\.)') {
                $results += New-DoctorResult -Area "Dashboard" -Name "VITE_API_URL LAN IP check" -Status "WARN" -Detail "VITE_API_URL uses private LAN IP '$($uri.Host)' which can go stale after router/machine changes and may fail CORS Origin allowlist in ws_security.py." -Action "Prefer VITE_API_URL=http://127.0.0.1:8000 for local Windows development."
            }
        }
    }

    return $results
}

function Invoke-FlutterChecks {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $results = @()
    $flutterRoot = Join-Path $RootPath "wanasah_frontend"
    $pubspec = Join-Path $flutterRoot "pubspec.yaml"
    $pkgConfig = Join-Path $flutterRoot ".dart_tool\package_config.json"
    $flutterEnv = Join-Path $flutterRoot ".env"

    $flutterCmd = Get-Command flutter -ErrorAction SilentlyContinue
    if ($null -ne $flutterCmd) {
        $results += New-DoctorResult -Area "Flutter" -Name "Flutter executable" -Status "PASS" -Detail "Found flutter on PATH ($($flutterCmd.Source))."
    } else {
        $candidatePaths = @(
            "C:\src\flutter\bin\flutter.bat",
            "C:\flutter\bin\flutter.bat"
        )
        if ($env:LOCALAPPDATA) { $candidatePaths += (Join-Path $env:LOCALAPPDATA "flutter\bin\flutter.bat") }
        if ($env:USERPROFILE) { $candidatePaths += (Join-Path $env:USERPROFILE "flutter\bin\flutter.bat") }
        $foundOffPath = $null
        foreach ($cand in $candidatePaths) {
            if (Test-Path -LiteralPath $cand -PathType Leaf) {
                $foundOffPath = $cand
                break
            }
        }
        if ($null -ne $foundOffPath) {
            $results += New-DoctorResult -Area "Flutter" -Name "Flutter executable" -Status "FAIL" -Detail "'flutter' is not on PATH, though an installation was found at '$foundOffPath'." -Action "Add '$(Split-Path -Parent $foundOffPath)' to your Windows PATH."
        } else {
            $results += New-DoctorResult -Area "Flutter" -Name "Flutter executable" -Status "FAIL" -Detail "'flutter' executable was not found on PATH (wanasah_frontend/pubspec.yaml requires Dart SDK ^3.7.2)." -Action "Install Flutter SDK (with Dart ^3.7.2) and add flutter\bin to PATH."
        }
    }

    if (-not (Test-Path -LiteralPath $pubspec -PathType Leaf)) {
        $results += New-DoctorResult -Area "Flutter" -Name "wanasah_frontend/pubspec.yaml" -Status "FAIL" -Detail "Missing 'wanasah_frontend\pubspec.yaml'." -Action "Restore wanasah_frontend\pubspec.yaml from Git."
    } else {
        $results += New-DoctorResult -Area "Flutter" -Name "wanasah_frontend/pubspec.yaml" -Status "PASS" -Detail "Found 'wanasah_frontend\pubspec.yaml' (SDK constraint ^3.7.2)."
    }

    if (-not (Test-Path -LiteralPath $pkgConfig -PathType Leaf)) {
        $results += New-DoctorResult -Area "Flutter" -Name "Flutter package resolution (.dart_tool)" -Status "FAIL" -Detail "Missing 'wanasah_frontend\.dart_tool\package_config.json' (packages have not been resolved)." -Action "Resolve Dart packages inside wanasah_frontend before running Flutter."
    } else {
        $pkgRaw = Get-Content -LiteralPath $pkgConfig -Raw -Encoding UTF8
        $uriMatch = [regex]::Match($pkgRaw, '"rootUri"\s*:\s*"file:///([^"]+)"')
        $staleCachePath = $null
        if ($uriMatch.Success) {
            $samplePath = [System.Uri]::UnescapeDataString($uriMatch.Groups[1].Value) -replace '/', '\'
            if (-not (Test-Path -LiteralPath $samplePath)) { $staleCachePath = $samplePath }
        }
        if ($null -ne $staleCachePath) {
            $results += New-DoctorResult -Area "Flutter" -Name "Flutter package resolution (.dart_tool)" -Status "FAIL" -Detail "package_config.json references missing cached path '$staleCachePath' (stale after machine reformat or move)." -Action "Regenerate wanasah_frontend\.dart_tool\package_config.json via Flutter package resolution."
        } else {
            $results += New-DoctorResult -Area "Flutter" -Name "Flutter package resolution (.dart_tool)" -Status "PASS" -Detail "Found valid 'wanasah_frontend\.dart_tool\package_config.json'."
        }
    }

    if (-not (Test-Path -LiteralPath $flutterEnv -PathType Leaf)) {
        $results += New-DoctorResult -Area "Flutter" -Name "wanasah_frontend/.env asset" -Status "FAIL" -Detail "Missing 'wanasah_frontend\.env' (declared under flutter.assets in pubspec.yaml; missing file breaks Flutter asset bundling and causes debug fallback to stale IP 192.168.1.115:8000)." -Action "Create wanasah_frontend\.env with API_BASE_URL=http://127.0.0.1:8000 (or your active dev LAN IP for physical devices)."
    } else {
        $fEnvMap = Read-DotEnvMap -FilePath $flutterEnv
        if (-not $fEnvMap.ContainsKey("API_BASE_URL") -or [string]::IsNullOrWhiteSpace($fEnvMap["API_BASE_URL"])) {
            $results += New-DoctorResult -Area "Flutter" -Name "wanasah_frontend/.env API_BASE_URL" -Status "WARN" -Detail "wanasah_frontend\.env exists but API_BASE_URL is unset; api_constants.dart will fall back to hardcoded 'http://192.168.1.115:8000' in debug mode." -Action "Set API_BASE_URL in wanasah_frontend\.env to your current Backend URL."
        } else {
            $results += New-DoctorResult -Area "Flutter" -Name "wanasah_frontend/.env API_BASE_URL" -Status "PASS" -Detail "wanasah_frontend\.env present with API_BASE_URL='$($fEnvMap['API_BASE_URL'])'."
        }
    }

    return $results
}

function Invoke-PortRuntimeChecks {
    param(
        [Parameter(Mandatory = $true)]$Port5432Info,
        [Parameter(Mandatory = $true)]$Port8000Info,
        [Parameter(Mandatory = $true)]$Port8080Info
    )
    $results = @()

    foreach ($info in @($Port5432Info, $Port8000Info, $Port8080Info)) {
        $cls = Get-PortClassification -Port $info.Port -Listening $info.Listening -ProcessName $info.ProcessName -ProcessId $info.Pid
        $results += New-DoctorResult -Area "Ports/Runtime" -Name "TCP Port $($info.Port)" -Status $cls.Status -Detail $cls.Detail -Action $cls.Action
    }

    return $results
}

function Invoke-HealthChecks {
    param([Parameter(Mandatory = $true)]$Port8000Info)
    $results = @()

    if (-not $Port8000Info.Listening) {
        $results += New-DoctorResult -Area "Health" -Name "Backend HTTP health (/health, /ready)" -Status "INFO" -Detail "Backend is not currently running on port 8000; skipped live /health and /ready probes."
        return $results
    }

    try {
        $healthResp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $healthJson = $healthResp.Content | ConvertFrom-Json
        if ($healthResp.StatusCode -eq 200 -and $null -ne $healthJson -and $healthJson.status -eq "alive") {
            $results += New-DoctorResult -Area "Health" -Name "GET http://127.0.0.1:8000/health" -Status "PASS" -Detail "HTTP 200 {'status': 'alive'}."
        } else {
            $results += New-DoctorResult -Area "Health" -Name "GET http://127.0.0.1:8000/health" -Status "FAIL" -Detail "Unexpected response from /health (HTTP $($healthResp.StatusCode))." -Action "Verify Wanasah FastAPI (uvicorn main:app) is the process bound to port 8000."
        }
    } catch {
        $errMsg = Protect-SecretText -Text $_.Exception.Message
        $results += New-DoctorResult -Area "Health" -Name "GET http://127.0.0.1:8000/health" -Status "FAIL" -Detail "Port 8000 is listening, but GET /health failed: $errMsg" -Action "Inspect the process on port 8000 and Backend Uvicorn logs."
    }

    $readyPassed = $false
    $readyAttempt = 0
    $lastReadyErr = ""
    while (-not $readyPassed -and $readyAttempt -lt 2) {
        $readyAttempt++
        if ($readyAttempt -gt 1) { Start-Sleep -Milliseconds 250 }
        try {
            $readyResp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/ready" -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            $readyJson = $readyResp.Content | ConvertFrom-Json
            if ($readyResp.StatusCode -eq 200 -and $null -ne $readyJson -and $readyJson.status -eq "ready") {
                $retryNote = if ($readyAttempt -gt 1) { "; succeeded on retry 2/2" } else { "" }
                $results += New-DoctorResult -Area "Health" -Name "GET http://127.0.0.1:8000/ready" -Status "PASS" -Detail "HTTP 200 {'status': 'ready'} (Backend database pool is connected$retryNote)."
                $readyPassed = $true
            } else {
                $lastReadyErr = "Unexpected HTTP $($readyResp.StatusCode)"
            }
        } catch {
            $lastReadyErr = Protect-SecretText -Text $_.Exception.Message
        }
    }
    if (-not $readyPassed) {
        $results += New-DoctorResult -Area "Health" -Name "GET http://127.0.0.1:8000/ready" -Status "FAIL" -Detail "Backend /ready probe failed after $readyAttempt attempts ($lastReadyErr) - Backend cannot query PostgreSQL." -Action "Verify PostgreSQL is running on port 5432 and DATABASE_URL in wa_backend\.env is valid."
    }

    return $results
}

function Invoke-DoctorSectionSafely {
    param(
        [Parameter(Mandatory = $true)][string]$Area,
        [Parameter(Mandatory = $true)][scriptblock]$CheckBlock
    )
    try {
        return @(& $CheckBlock)
    } catch {
        $safeErr = Protect-SecretText -Text $_.Exception.Message
        return @(
            New-DoctorResult -Area $Area -Name "$Area diagnostic internal guard" -Status "FAIL" -Detail "Check threw an unexpected error: $safeErr" -Action "Inspect the '$Area' environment settings and rerun .\ops\development\wanasah_doctor.ps1."
        )
    }
}

function Get-DoctorSummary {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Results,
        [switch]$StrictMode
    )
    $counts = @{
        PASS = 0
        WARN = 0
        FAIL = 0
        INFO = 0
    }
    $failActions = New-Object 'System.Collections.Generic.List[string]'
    $warnActions = New-Object 'System.Collections.Generic.List[string]'
    $infoActions = New-Object 'System.Collections.Generic.List[string]'

    foreach ($r in $Results) {
        $st = [string]$r.Status
        if ($counts.ContainsKey($st)) { $counts[$st]++ }
        $act = ([string]$r.Action).Trim()
        if ([string]::IsNullOrEmpty($act)) { continue }
        if ($st -eq "FAIL" -and -not $failActions.Contains($act)) {
            [void]$failActions.Add($act)
        } elseif ($st -eq "WARN" -and -not $warnActions.Contains($act) -and -not $failActions.Contains($act)) {
            [void]$warnActions.Add($act)
        } elseif ($st -eq "INFO" -and -not $infoActions.Contains($act) -and -not $failActions.Contains($act) -and -not $warnActions.Contains($act)) {
            [void]$infoActions.Add($act)
        }
    }

    $combined = @($failActions) + @($warnActions) + @($infoActions)
    $top3 = @($combined | Select-Object -First 3)
    if ($top3.Count -eq 0) {
        $top3 = @(
            "Start Backend API: cd wa_backend; .\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload",
            "Start Operational Worker: .\ops\development\run_operational_worker.ps1",
            "Start Dashboard: cd dashboard; npm run dev"
        )
    }

    $exitCode = Get-DoctorExitCode -Counts $counts -StrictMode:$StrictMode
    return [PSCustomObject]@{
        Counts      = $counts
        NextActions = $top3
        ExitCode    = $exitCode
    }
}

function Get-DoctorExitCode {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Counts,
        [switch]$StrictMode
    )
    if ([int]$Counts["FAIL"] -gt 0) { return 1 }
    if ($StrictMode -and [int]$Counts["WARN"] -gt 0) { return 1 }
    return 0
}

function Write-DoctorReport {
    param(
        [Parameter(Mandatory = $true)][object[]]$Results,
        [Parameter(Mandatory = $true)]$Summary,
        [Parameter(Mandatory = $true)][string]$ResolvedRepoRoot
    )
    Write-Host "============================================================"
    Write-Host "WANASAH WINDOWS DEV DOCTOR (READ-ONLY)"
    Write-Host "Repo Root: $ResolvedRepoRoot"
    Write-Host "============================================================"

    $currentArea = ""
    foreach ($item in $Results) {
        if ($item.Area -ne $currentArea) {
            $currentArea = $item.Area
            Write-Host ""
            Write-Host "-- $currentArea --"
        }
        $tag = $script:DoctorStatusBadges[[string]$item.Status]
        if ([string]::IsNullOrEmpty($tag)) { $tag = "[INFO]" }
        $line = Protect-SecretText -Text "$tag $($item.Name): $($item.Detail)"
        Write-Host $line
    }

    Write-Host ""
    Write-Host "------------------------------------------------------------"
    Write-Host "PASS: $($Summary.Counts['PASS'])"
    Write-Host "WARN: $($Summary.Counts['WARN'])"
    Write-Host "FAIL: $($Summary.Counts['FAIL'])"
    Write-Host "INFO: $($Summary.Counts['INFO'])"
    Write-Host "------------------------------------------------------------"
    Write-Host "Top 3 Next Actions:"
    $idx = 1
    foreach ($act in $Summary.NextActions) {
        Write-Host "  $idx. $(Protect-SecretText -Text $act)"
        $idx++
    }
    Write-Host "============================================================"
}

function Invoke-WanasahDoctor {
    param(
        [string]$TargetRepoRoot = "",
        [switch]$StrictMode
    )
    $resolvedRoot = if (-not [string]::IsNullOrWhiteSpace($TargetRepoRoot)) {
        (Resolve-Path -LiteralPath $TargetRepoRoot).Path
    } else { (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path }

    $port5432 = Get-ListeningPortInfo -Port 5432
    $port8000 = Get-ListeningPortInfo -Port 8000
    $port8080 = Get-ListeningPortInfo -Port 8080
    $pgBins = Find-PostgresBinaries

    $probeData = $null
    $venvPy = Join-Path $resolvedRoot "wa_backend\venv\Scripts\python.exe"
    $probeScript = Join-Path $resolvedRoot "wa_backend\scripts\wanasah_doctor_probe.py"
    $pyRunner = $null
    if (Test-Path -LiteralPath $venvPy -PathType Leaf) { $pyRunner = $venvPy }

    if ($null -ne $pyRunner -and (Test-Path -LiteralPath $probeScript -PathType Leaf)) {
        try {
            $probeArgs = @($probeScript, "--repo-root", $resolvedRoot)
            if ($pgBins.Keys.Count -gt 0) { $probeArgs += "--binaries-present" }
            if ($port5432.Listening) { $probeArgs += "--port-5432-listening" }
            $rawJson = (& $pyRunner @probeArgs 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($rawJson)) {
                $probeData = $rawJson | ConvertFrom-Json
            }
        } catch { $probeData = $null }
    }

    $allResults = @()
    $allResults += Invoke-DoctorSectionSafely -Area "Repository" -CheckBlock {
        Invoke-RepoChecks -RootPath $resolvedRoot
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Python/Backend" -CheckBlock {
        Invoke-PythonBackendChecks -RootPath $resolvedRoot -ProbeData $probeData
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Backend Env" -CheckBlock {
        Invoke-BackendEnvChecks -RootPath $resolvedRoot -ProbeData $probeData
    }
    $allResults += Invoke-DoctorSectionSafely -Area "PostgreSQL" -CheckBlock {
        Invoke-PostgresChecks -RootPath $resolvedRoot -Port5432Info $port5432 -PgBinaries $pgBins -ProbeData $probeData
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Alembic" -CheckBlock {
        Invoke-AlembicChecks -RootPath $resolvedRoot -ProbeData $probeData
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Product Import" -CheckBlock {
        Invoke-ProductImportChecks -RootPath $resolvedRoot -ProbeData $probeData
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Dashboard" -CheckBlock {
        Invoke-DashboardChecks -RootPath $resolvedRoot -Port8000Info $port8000
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Flutter" -CheckBlock {
        Invoke-FlutterChecks -RootPath $resolvedRoot
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Ports/Runtime" -CheckBlock {
        Invoke-PortRuntimeChecks -Port5432Info $port5432 -Port8000Info $port8000 -Port8080Info $port8080
    }
    $allResults += Invoke-DoctorSectionSafely -Area "Health" -CheckBlock {
        Invoke-HealthChecks -Port8000Info $port8000
    }

    $summary = Get-DoctorSummary -Results $allResults -StrictMode:$StrictMode
    Write-DoctorReport -Results $allResults -Summary $summary -ResolvedRepoRoot $resolvedRoot
    return [int]$summary.ExitCode
}

if (-not $NoRun -and $MyInvocation.InvocationName -ne '.') {
    $code = Invoke-WanasahDoctor -TargetRepoRoot $RepoRoot -StrictMode:$Strict
    exit $code
}
