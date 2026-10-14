"""Read-only diagnostic helper and pure evaluators for Wanasah Windows Dev Doctor.

This module is strictly read-only:
- It never modifies files, environment files, database state, or migrations.
- It never prints or returns database passwords, SECRET_KEY values, JWTs, or
  unredacted credential-bearing DSNs.
- All database probes execute inside `SET TRANSACTION READ ONLY` with a short
  connection timeout.
"""
from __future__ import annotations

import argparse
import configparser
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

MIN_PYTHON_VERSION = (3, 12)
REQUIRED_RLS_TABLES = (
    "product_import_jobs",
    "product_import_rows",
    "product_import_sources",
    "product_import_schedule_candidates",
    "product_variants",
    "price_book_entries",
)

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "password",
        "pass",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "key",
    }
)

_URL_CREDENTIAL_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)"
)
_KV_SECRET_RE = re.compile(
    r"(?i)\b(SECRET_KEY|PGPASSWORD|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN|SENTRY_DSN)"
    r"(\s*[=:]\s*)([^\s,;\"']+)"
)
_BEARER_RE = re.compile(
    r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+"
)
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_ONEDRIVE_SEGMENT_RE = re.compile(
    r"(?i)(?:^|[\\/])OneDrive(?:\s*-\s*[^\\/]+)?(?:[\\/]|$)"
)

def redact_secrets(text: str | None) -> str:
    """Redact credentials, tokens, and secret key assignments from arbitrary text."""
    if not text:
        return ""
    cleaned = str(text)
    cleaned = _URL_CREDENTIAL_RE.sub(r"\1***\3", cleaned)
    cleaned = _KV_SECRET_RE.sub(r"\1\2***", cleaned)
    cleaned = _BEARER_RE.sub(r"\1***", cleaned)
    cleaned = _JWT_RE.sub("[REDACTED_JWT]", cleaned)
    return cleaned

def sanitize_dsn(raw_dsn: str | None) -> str:
    """Return a safe display representation of a DSN without credentials.

    Never echoes unparsed credential-bearing strings if URL parsing fails.
    """
    if raw_dsn is None:
        return "<unset>"
    value = str(raw_dsn).strip()
    if not value:
        return "<empty>"
    if "${" in value:
        return "<unexpanded-template>"

    try:
        parts = urlsplit(value)
    except ValueError:
        return "<malformed-dsn-redacted>"

    if not parts.scheme or "://" not in value:
        return "<malformed-dsn-redacted>"

    netloc = parts.netloc
    if "@" in netloc:
        userinfo, hostinfo = netloc.rsplit("@", 1)
        username = userinfo.split(":", 1)[0] if ":" in userinfo else userinfo
        safe_user = username if username else "user"
        netloc = f"{safe_user}:***@{hostinfo}"

    if not netloc or netloc.startswith("@"):
        return "<malformed-dsn-redacted>"

    query = parts.query
    if query:
        safe_pairs = []
        for k, v in parse_qsl(query, keep_blank_values=True):
            if k.lower() in _SENSITIVE_QUERY_KEYS or any(
                s in k.lower() for s in ("pass", "secret", "token", "key")
            ):
                safe_pairs.append((k, "***"))
            else:
                safe_pairs.append((k, v))
        query = urlencode(safe_pairs)

    sanitized = urlunsplit(
        SplitResult(
            scheme=parts.scheme,
            netloc=netloc,
            path=parts.path,
            query=query,
            fragment="",
        )
    )
    return redact_secrets(sanitized)

def parse_postgres_dsn(raw_dsn: str | None) -> dict[str, Any]:
    """Parse a PostgreSQL DSN into non-secret structural fields."""
    sanitized = sanitize_dsn(raw_dsn)
    if not raw_dsn or not str(raw_dsn).strip():
        return {
            "valid": False,
            "reason": "missing",
            "sanitized": sanitized,
        }
    value = str(raw_dsn).strip()
    if "${" in value:
        return {
            "valid": False,
            "reason": "interpolated_template",
            "sanitized": sanitized,
        }
    try:
        parts = urlsplit(value)
        port = parts.port or 5432
    except ValueError:
        return {
            "valid": False,
            "reason": "malformed_url",
            "sanitized": "<malformed-dsn-redacted>",
        }

    scheme = parts.scheme.lower()
    valid_schemes = (
        "postgres",
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg",
    )
    if scheme not in valid_schemes:
        return {
            "valid": False,
            "reason": f"unsupported_scheme:{scheme or 'none'}",
            "sanitized": sanitized,
        }

    host = (parts.hostname or "").strip()
    database = parts.path.lstrip("/")
    if not host or not database or "/" in database:
        return {
            "valid": False,
            "reason": "missing_host_or_database",
            "sanitized": sanitized,
        }

    return {
        "valid": True,
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "database": database,
        "username": parts.username or "",
        "has_password": bool(parts.password),
        "sanitized": sanitized,
    }

def is_onedrive_path(
    path_str: str | Path,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Detect whether a repository path lives inside a OneDrive-synced folder."""
    raw = str(path_str or "").strip()
    if not raw:
        return False
    if _ONEDRIVE_SEGMENT_RE.search(raw):
        return True

    env_map = os.environ if env is None else env
    norm_target = re.sub(r"[\\/]+", "/", raw).rstrip("/").lower()
    for var_name in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        od_root = str(env_map.get(var_name) or "").strip()
        if not od_root:
            continue
        norm_od = re.sub(r"[\\/]+", "/", od_root).rstrip("/").lower()
        if norm_od and (
            norm_target == norm_od or norm_target.startswith(norm_od + "/")
        ):
            return True
    return False

def detect_localhost_loopback_risk(
    raw_dsn: str | None,
    *,
    platform_name: str = "win32",
) -> dict[str, Any]:
    """Check for Windows localhost vs 127.0.0.1 DSN resolution mismatch.

    In `wa_backend/domains/simple_products/imports/infrastructure/queue_dsn.py`,
    Product Import rewrites `host=localhost` to `127.0.0.1` on Windows because
    psycopg's async pool background `AddConnection` can hang while resolving
    `localhost`. Meanwhile `wa_backend/workers/app.py` (Operational/Reports
    PsycopgConnector), `wa_backend/realtime/worker_event_relay.py`,
    `wa_backend/database.py`, and `wa_backend/alembic/env.py` do NOT rewrite
    `localhost`, creating an asymmetric loopback target and exposing
    Operational/Reports workers to the Windows localhost resolution hang.
    """
    parsed = parse_postgres_dsn(raw_dsn)
    if not parsed.get("valid"):
        return {
            "at_risk": False,
            "reason": "dsn_invalid",
            "host": None,
        }
    host = str(parsed["host"]).lower()
    is_win = platform_name.lower().startswith("win")
    if is_win and host == "localhost":
        return {
            "at_risk": True,
            "reason": (
                "DSN uses 'localhost' on Windows: Product Import queue_dsn.py "
                "rewrites localhost -> 127.0.0.1, whereas workers/app.py "
                "(Operational/Reports PsycopgConnector), database.py, and "
                "alembic/env.py keep 'localhost' (risking psycopg async pool "
                "AddConnection hangs or IPv6 ::1 vs IPv4 127.0.0.1 split)."
            ),
            "host": host,
            "recommended_host": "127.0.0.1",
        }
    return {
        "at_risk": False,
        "reason": "numeric_or_remote_host",
        "host": host,
    }

def classify_pg_error(
    error_text: str | Exception | None,
    *,
    binaries_present: bool,
    port_listening: bool,
) -> dict[str, str]:
    """Classify PostgreSQL failure into one of the 4 canonical diagnostic states:
    - BINARIES_MISSING
    - SERVER_NOT_RUNNING
    - AUTH_OR_CONFIG_ERROR
    - DATABASE_MISSING
    """
    msg = redact_secrets(str(error_text or "")).strip()
    lower = msg.lower()

    if not port_listening:
        if not binaries_present:
            return {
                "category": "BINARIES_MISSING",
                "status": "FAIL",
                "summary": (
                    "PostgreSQL CLI/server binaries (psql/postgres/pg_ctl) were "
                    "not found and port 5432 is not listening."
                ),
                "action": (
                    "Install PostgreSQL 16 (C:\\Program Files\\PostgreSQL\\16\\bin) "
                    "or add its bin directory to PATH, then start the PostgreSQL service."
                ),
            }
        return {
            "category": "SERVER_NOT_RUNNING",
            "status": "FAIL",
            "summary": (
                "PostgreSQL binaries are installed, but no server is listening "
                "on the configured PostgreSQL port."
            ),
            "action": (
                "Start the configured local PostgreSQL instance (Windows service "
                "or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
            ),
        }

    if (
        "3d000" in lower
        or ("database" in lower and "does not exist" in lower)
    ):
        return {
            "category": "DATABASE_MISSING",
            "status": "FAIL",
            "summary": (
                "PostgreSQL server is running and reachable, but the configured "
                "target database does not exist."
            ),
            "action": (
                "Verify the configured database name in wa_backend/.env and "
                "create/restore the intended development database."
            ),
        }

    if (
        "28p01" in lower
        or "28000" in lower
        or "password authentication failed" in lower
        or "no pg_hba.conf entry" in lower
        or "authentication failed" in lower
        or ("role" in lower and "does not exist" in lower)
        or "fe_sendauth" in lower
        or "permission denied" in lower
    ):
        return {
            "category": "AUTH_OR_CONFIG_ERROR",
            "status": "FAIL",
            "summary": (
                "PostgreSQL is listening, but authentication or pg_hba/role "
                "configuration rejected the connection."
            ),
            "action": (
                "Check the username/password and host (prefer 127.0.0.1) in "
                "wa_backend/.env (DATABASE_URL / DATABASE_URL_MIGRATION) and "
                "verify pg_hba.conf / role permissions for wanasah_app."
            ),
        }

    if (
        "connection refused" in lower
        or "could not connect to server" in lower
        or "timed out" in lower
        or "timeout expired" in lower
    ):
        return {
            "category": "SERVER_NOT_RUNNING",
            "status": "FAIL",
            "summary": (
                "PostgreSQL connection attempt was refused or timed out."
            ),
            "action": (
                "Start the configured local PostgreSQL instance (Windows service "
                "or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
            ),
        }

    return {
        "category": "AUTH_OR_CONFIG_ERROR",
        "status": "FAIL",
        "summary": (
            f"PostgreSQL connection check failed ({msg or 'unknown error'})."
        ),
        "action": (
            "Inspect wa_backend/.env DATABASE_URL settings and PostgreSQL server logs."
        ),
    }

def classify_port_state(
    port: int,
    *,
    listening: bool,
    process_name: str | None = None,
    pid: int | None = None,
) -> dict[str, str]:
    """Classify local TCP port state for 5432 (PostgreSQL), 8000 (Backend), 8080 (Dashboard)."""
    proc = (process_name or "").strip()
    proc_lower = proc.lower()
    pid_suffix = f" (PID {pid}: {proc or 'unknown'})" if pid else (
        f" ({proc})" if proc else ""
    )

    if port == 5432:
        if not listening:
            return {
                "status": "FAIL",
                "detail": "Port 5432 is FREE (PostgreSQL is not listening).",
                "action": (
                    "Start the configured local PostgreSQL instance (Windows service "
                    "or the project's pg_ctl/custom-cluster startup path) and verify port 5432."
                ),
            }
        expected = ("postgres", "pg_ctl", "com.docker", "wslrelay", "vpnkit")
        if not proc_lower or any(p in proc_lower for p in expected):
            return {
                "status": "PASS",
                "detail": f"Port 5432 is LISTENING{pid_suffix}.",
                "action": "",
            }
        return {
            "status": "FAIL",
            "detail": (
                f"Port 5432 is occupied by unexpected process{pid_suffix}."
            ),
            "action": (
                f"Free port 5432 (currently held by {proc or 'unknown'}) so "
                "PostgreSQL can bind to it."
            ),
        }

    if port == 8000:
        if not listening:
            return {
                "status": "INFO",
                "detail": "Port 8000 is FREE (Backend API is not currently running).",
                "action": "",
            }
        expected = ("python", "python3", "uvicorn")
        if not proc_lower or any(p in proc_lower for p in expected):
            return {
                "status": "PASS",
                "detail": f"Port 8000 is LISTENING{pid_suffix}.",
                "action": "",
            }
        return {
            "status": "FAIL",
            "detail": (
                f"Port 8000 is occupied by unexpected process{pid_suffix}."
            ),
            "action": (
                f"Stop or reconfigure the unexpected process on port 8000 "
                f"{pid_suffix} before starting Uvicorn."
            ),
        }

    if port == 8080:
        if not listening:
            return {
                "status": "INFO",
                "detail": "Port 8080 is FREE (Dashboard Vite dev server is not running).",
                "action": "",
            }
        expected = ("node", "bun", "deno", "vite")
        if not proc_lower or any(p in proc_lower for p in expected):
            return {
                "status": "PASS",
                "detail": f"Port 8080 is LISTENING{pid_suffix}.",
                "action": "",
            }
        return {
            "status": "FAIL",
            "detail": (
                f"Port 8080 is occupied by unexpected process{pid_suffix}."
            ),
            "action": (
                f"Stop the conflicting process on port 8080{pid_suffix}; "
                "dashboard/vite.config.ts binds to port 8080."
            ),
        }

    return {
        "status": "INFO",
        "detail": (
            f"Port {port} is {'LISTENING' if listening else 'FREE'}{pid_suffix}."
        ),
        "action": "",
    }

def classify_health_endpoints(
    *,
    port_listening: bool,
    health_status: int | None,
    health_body: Mapping[str, Any] | None,
    ready_status: int | None,
    ready_body: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """Classify Backend /health and /ready probes without failing when Backend is stopped."""
    if not port_listening:
        return [
            {
                "area": "Health",
                "name": "Backend runtime health (/health, /ready)",
                "status": "INFO",
                "detail": (
                    "Backend is not currently running on port 8000; skipped "
                    "live /health and /ready HTTP probes."
                ),
                "action": "",
            }
        ]

    checks: list[dict[str, str]] = []
    if health_status == 200 and isinstance(health_body, Mapping) and (
        health_body.get("status") == "alive"
    ):
        checks.append(
            {
                "area": "Health",
                "name": "GET /health",
                "status": "PASS",
                "detail": "HTTP 200 {'status': 'alive'}.",
                "action": "",
            }
        )
    else:
        checks.append(
            {
                "area": "Health",
                "name": "GET /health",
                "status": "FAIL",
                "detail": (
                    f"Port 8000 is listening, but GET /health returned "
                    f"HTTP {health_status or 'ERR'} (expected 200 {{'status': 'alive'}})."
                ),
                "action": (
                    "Verify that Wanasah FastAPI (uvicorn main:app) is the "
                    "service bound to port 8000 and inspect terminal output."
                ),
            }
        )

    if ready_status == 200 and isinstance(ready_body, Mapping) and (
        ready_body.get("status") == "ready"
    ):
        checks.append(
            {
                "area": "Health",
                "name": "GET /ready",
                "status": "PASS",
                "detail": "HTTP 200 {'status': 'ready'} (database pool healthy).",
                "action": "",
            }
        )
    else:
        checks.append(
            {
                "area": "Health",
                "name": "GET /ready",
                "status": "FAIL",
                "detail": (
                    f"GET /ready returned HTTP {ready_status or 'ERR'} "
                    "(Backend is running but its database readiness check failed)."
                ),
                "action": (
                    "Check PostgreSQL availability on port 5432 and verify "
                    "DATABASE_URL in wa_backend/.env."
                ),
            }
        )

    return checks

def aggregate_results(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute PASS/WARN/FAIL/INFO counts and the top 3 prioritized next actions."""
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0}
    fail_actions: list[str] = []
    warn_actions: list[str] = []
    info_actions: list[str] = []

    for item in results:
        status = str(item.get("status") or "INFO").upper()
        if status not in counts:
            status = "INFO"
        counts[status] += 1
        action = redact_secrets(str(item.get("action") or "").strip())
        if not action:
            continue
        if status == "FAIL" and action not in fail_actions:
            fail_actions.append(action)
        elif status == "WARN" and action not in warn_actions and action not in fail_actions:
            warn_actions.append(action)
        elif (
            status == "INFO"
            and action not in info_actions
            and action not in fail_actions
            and action not in warn_actions
        ):
            info_actions.append(action)

    prioritized = (fail_actions + warn_actions + info_actions)[:3]
    return {
        "counts": counts,
        "next_actions": prioritized,
        "exit_code": compute_exit_code(counts),
    }

def compute_exit_code(
    counts: Mapping[str, int],
    *,
    strict: bool = False,
) -> int:
    """Return 0 when no blocking failures exist, or 1 when FAIL > 0 (or WARN > 0 in strict mode)."""
    if int(counts.get("FAIL", 0)) > 0:
        return 1
    if strict and int(counts.get("WARN", 0)) > 0:
        return 1
    return 0


_ALEMBIC_INI_URL_RE = re.compile(
    r"(?m)^[ \t]*sqlalchemy\.url[ \t]*=[ \t]*([^\r\n#;]*)"
)


def is_alembic_ini_url_blank(ini_text: str | None) -> bool:
    """Verify sqlalchemy.url in alembic.ini is blank without crossing newlines."""
    if not ini_text:
        return True
    match = _ALEMBIC_INI_URL_RE.search(ini_text)
    if not match:
        return True
    return match.group(1).strip() == ""


def evaluate_backend_db_env(
    raw_db_url: str | None,
    raw_mig_url: str | None,
) -> list[dict[str, str]]:
    """Evaluate DATABASE_URL and DATABASE_URL_MIGRATION without overfitting to specialized D8 database names."""
    checks: list[dict[str, str]] = []
    db_info = parse_postgres_dsn(raw_db_url)
    if not db_info.get("valid"):
        checks.append(
            {
                "area": "Backend Env",
                "name": "DATABASE_URL configuration",
                "status": "FAIL",
                "detail": (
                    f"DATABASE_URL is invalid or missing ({db_info.get('reason')}): "
                    f"{db_info.get('sanitized')}."
                ),
                "action": (
                    "Set DATABASE_URL in wa_backend\\.env "
                    "(e.g. postgresql+asyncpg://wanasah_app:<password>@127.0.0.1:5432/wanasah_local)."
                ),
            }
        )
    else:
        checks.append(
            {
                "area": "Backend Env",
                "name": "DATABASE_URL configuration",
                "status": "PASS",
                "detail": f"DATABASE_URL -> {db_info['sanitized']}.",
                "action": "",
            }
        )

    if not raw_mig_url or not str(raw_mig_url).strip():
        checks.append(
            {
                "area": "Backend Env",
                "name": "DATABASE_URL_MIGRATION configuration",
                "status": "INFO",
                "detail": (
                    "DATABASE_URL_MIGRATION is not set; alembic/env.py uses DATABASE_URL "
                    "as the valid migration target (explicit DATABASE_URL_MIGRATION is "
                    "only needed for specialized D8 audit scripts)."
                ),
                "action": "",
            }
        )
    else:
        mig_info = parse_postgres_dsn(raw_mig_url)
        if not mig_info.get("valid"):
            checks.append(
                {
                    "area": "Backend Env",
                    "name": "DATABASE_URL_MIGRATION configuration",
                    "status": "FAIL",
                    "detail": (
                        f"DATABASE_URL_MIGRATION is malformed ({mig_info.get('reason')}): "
                        f"{mig_info.get('sanitized')}."
                    ),
                    "action": "Fix DATABASE_URL_MIGRATION in wa_backend\\.env.",
                }
            )
        elif db_info.get("valid") and (
            db_info["host"].lower().rstrip("."),
            int(db_info["port"]),
            db_info["database"],
        ) != (
            mig_info["host"].lower().rstrip("."),
            int(mig_info["port"]),
            mig_info["database"],
        ):
            checks.append(
                {
                    "area": "Backend Env",
                    "name": "DATABASE_URL_MIGRATION target match",
                    "status": "FAIL",
                    "detail": (
                        f"DATABASE_URL ({db_info['sanitized']}) and "
                        f"DATABASE_URL_MIGRATION ({mig_info['sanitized']}) point to "
                        "different host/port/database targets."
                    ),
                    "action": (
                        "Align DATABASE_URL and DATABASE_URL_MIGRATION in wa_backend\\.env "
                        "to the same PostgreSQL instance and database."
                    ),
                }
            )
        else:
            checks.append(
                {
                    "area": "Backend Env",
                    "name": "DATABASE_URL_MIGRATION configuration",
                    "status": "PASS",
                    "detail": (
                        f"DATABASE_URL_MIGRATION -> {mig_info['sanitized']} "
                        "(matches runtime target)."
                    ),
                    "action": "",
                }
            )
    return checks


def classify_ready_probe_attempts(
    attempts: Sequence[tuple[int | None, Mapping[str, Any] | None, str | None]],
) -> dict[str, str]:
    """Classify /ready HTTP probe across up to 2 bounded attempts."""
    last_err = "unknown readiness error"
    for idx, (status_code, body, err_text) in enumerate(attempts, start=1):
        if (
            status_code == 200
            and isinstance(body, Mapping)
            and body.get("status") == "ready"
        ):
            retry_note = "; succeeded on retry 2/2" if idx > 1 else ""
            return {
                "area": "Health",
                "name": "GET /ready",
                "status": "PASS",
                "detail": f"HTTP 200 {{'status': 'ready'}} (database pool healthy{retry_note}).",
                "action": "",
            }
        if err_text:
            last_err = redact_secrets(err_text)
        else:
            last_err = f"HTTP {status_code or 'ERR'}"

    total = max(1, len(attempts))
    return {
        "area": "Health",
        "name": "GET /ready",
        "status": "FAIL",
        "detail": (
            f"Backend /ready probe failed after {total} attempt(s) ({last_err}) - "
            "Backend cannot query PostgreSQL."
        ),
        "action": (
            "Check PostgreSQL availability on port 5432 and verify "
            "DATABASE_URL in wa_backend/.env."
        ),
    }


def resolve_alembic_repo_heads(versions_dir: Path) -> dict[str, Any]:
    """Statically compute Alembic head revision(s) from wa_backend/alembic/versions/*.py."""
    if not versions_dir.is_dir():
        return {"ok": False, "heads": [], "count": 0, "error": "versions_dir_missing"}

    revs: dict[str, str] = {}
    down_revs: set[str] = set()
    rev_re = re.compile(
        r"^revision\s*(?::\s*[^=]+)?=\s*['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )
    down_re = re.compile(
        r"^down_revision\s*(?::\s*[^=]+)?=\s*(.+)$",
        re.MULTILINE,
    )

    for path in sorted(versions_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m_rev = rev_re.search(text)
        if not m_rev:
            continue
        rev = m_rev.group(1).strip()
        revs[rev] = path.name
        m_down = down_re.search(text)
        if m_down:
            raw_down = m_down.group(1).split("#", 1)[0].strip()
            if raw_down != "None":
                for token in re.findall(r"['\"]([^'\"]+)['\"]", raw_down):
                    down_revs.add(token.strip())

    heads = sorted(set(revs.keys()) - down_revs)
    return {
        "ok": len(heads) == 1,
        "heads": heads,
        "count": len(revs),
        "error": None if len(heads) == 1 else f"expected_1_head_found_{len(heads)}",
    }

def parse_dotenv_file(env_path: Path) -> dict[str, str]:
    """Read key=value pairs from a .env file without mutating os.environ."""
    values: dict[str, str] = {}
    if not env_path.is_file():
        return values
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        elif " #" in val:
            val = val.split(" #", 1)[0].strip()
        if key:
            values[key] = val
    return values

def check_requirements(requirements_path: Path) -> dict[str, Any]:
    """Verify installed package versions in the current Python interpreter against requirements.txt."""
    if not requirements_path.is_file():
        return {
            "ok": False,
            "missing": ["requirements.txt missing"],
            "mismatched": [],
            "checked": 0,
        }
    missing: list[str] = []
    mismatched: list[str] = []
    checked = 0

    req_re = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*==\s*([^\s;#]+)")
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = req_re.match(line)
        if not m:
            continue
        pkg_name, expected_ver = m.group(1), m.group(2)
        checked += 1
        try:
            installed_ver = importlib.metadata.version(pkg_name)
            if installed_ver != expected_ver:
                mismatched.append(
                    f"{pkg_name} (installed {installed_ver}, expected {expected_ver})"
                )
        except importlib.metadata.PackageNotFoundError:
            missing.append(f"{pkg_name}=={expected_ver}")

    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "mismatched": mismatched,
        "checked": checked,
    }

def probe_database_readonly(
    raw_dsn: str,
    *,
    binaries_present: bool,
    port_listening: bool,
    expected_heads: Sequence[str],
    deployment_budget: int = 60,
) -> dict[str, Any]:
    """Perform a strictly READ ONLY PostgreSQL diagnostic probe using psycopg."""
    parsed = parse_postgres_dsn(raw_dsn)
    if not parsed.get("valid"):
        return {
            "connected": False,
            "classification": classify_pg_error(
                f"Invalid DSN ({parsed.get('reason')})",
                binaries_present=binaries_present,
                port_listening=port_listening,
            ),
        }

    if not port_listening:
        return {
            "connected": False,
            "classification": classify_pg_error(
                "Connection refused (port not listening)",
                binaries_present=binaries_present,
                port_listening=False,
            ),
        }

    try:
        import psycopg
    except ImportError:
        return {
            "connected": False,
            "psycopg_missing": True,
            "classification": {
                "category": "CLIENT_DRIVER_MISSING",
                "status": "WARN",
                "summary": "psycopg is not installed in the active Python environment; skipped live SQL query probe.",
                "action": "Verify wa_backend\\venv has requirements.txt installed.",
            },
        }

    # Build a clean libpq/psycopg conninfo without driver suffix (+asyncpg/+psycopg)
    parts = urlsplit(str(raw_dsn).strip())
    clean_dsn = urlunsplit(
        SplitResult(
            scheme="postgresql",
            netloc=parts.netloc,
            path=parts.path,
            query=parts.query,
            fragment="",
        )
    )

    try:
        with psycopg.connect(
            clean_dsn,
            connect_timeout=3,
            autocommit=True,
            options="-c default_transaction_read_only=on",
        ) as conn:
            conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            conn.execute("SELECT 1").fetchone()

            max_conn = int(
                conn.execute("SHOW max_connections").fetchone()[0]
            )
            reserved_conn = int(
                conn.execute("SHOW superuser_reserved_connections").fetchone()[0]
            )

            # Check alembic_version table safely
            has_alembic_table = bool(
                conn.execute(
                    "SELECT EXISTS ("
                    "  SELECT 1 FROM information_schema.tables "
                    "  WHERE table_schema = 'public' AND table_name = 'alembic_version'"
                    ")"
                ).fetchone()[0]
            )
            db_revisions: list[str] = []
            if has_alembic_table:
                db_revisions = sorted(
                    str(row[0])
                    for row in conn.execute(
                        "SELECT version_num FROM public.alembic_version"
                    ).fetchall()
                    if row and row[0]
                )

            # Check Product Import FORCE RLS tables
            rls_rows = conn.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND c.relname = ANY(%s)
                ORDER BY c.relname
                """,
                (list(REQUIRED_RLS_TABLES),),
            ).fetchall()
            rls_map = {
                str(name): (bool(enabled), bool(forced))
                for name, enabled, forced in rls_rows
            }
            missing_rls = [
                t for t in REQUIRED_RLS_TABLES
                if t not in rls_map or not all(rls_map[t])
            ]

            # Check active Product Import worker connections by exact PGAPPNAME
            role_rows = conn.execute(
                """
                SELECT application_name, count(*)
                FROM pg_stat_activity
                WHERE application_name IN (
                    'wanasah-product-import-execution',
                    'wanasah-product-import-control',
                    'wanasah-product-import-maintenance'
                )
                GROUP BY application_name
                """
            ).fetchall()
            role_counts = {str(app): int(cnt) for app, cnt in role_rows}
            observed_roles = [
                role
                for role in ("execution", "control", "maintenance")
                if role_counts.get(f"wanasah-product-import-{role}", 0) > 0
            ]

            return {
                "connected": True,
                "max_connections": max_conn,
                "superuser_reserved_connections": reserved_conn,
                "headroom_ok": deployment_budget < (max_conn - reserved_conn),
                "has_alembic_table": has_alembic_table,
                "db_revisions": db_revisions,
                "alembic_matches_head": (
                    has_alembic_table and db_revisions == sorted(expected_heads)
                ),
                "missing_force_rls_tables": missing_rls,
                "observed_import_roles": observed_roles,
            }
    except Exception as exc:
        return {
            "connected": False,
            "classification": classify_pg_error(
                exc,
                binaries_present=binaries_present,
                port_listening=port_listening,
            ),
        }

def _strip_ps1_strings_and_comments(text: str) -> str:
    no_block = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    out_lines: list[str] = []
    for raw_line in no_block.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("#"):
            continue
        buf: list[str] = []
        in_sq = False
        in_dq = False
        for ch in raw_line:
            if ch == "'" and not in_dq:
                in_sq = not in_sq
                buf.append(" ")
            elif ch == chr(34) and not in_sq:
                in_dq = not in_dq
                buf.append(" ")
            elif not in_sq and not in_dq:
                buf.append(ch)
            else:
                buf.append(" ")
        out_lines.append("".join(buf))
    return "\n".join(out_lines)

def validate_powershell_script_contract(ps1_path: Path) -> list[str]:
    """Static verification of wanasah_doctor.ps1 structure and read-only safety."""
    if not ps1_path.is_file():
        return [f"Missing PowerShell script: {ps1_path}"]

    raw_bytes = ps1_path.read_bytes()
    issues: list[str] = []
    for idx, b in enumerate(raw_bytes):
        if b not in (9, 10, 13) and not (32 <= b <= 126):
            issues.append(
                f"Non-ASCII byte 0x{b:02x} at byte offset {idx} "
                "(Windows PowerShell 5.1 ANSI parser hazard)"
            )
            break

    text = raw_bytes.decode("utf-8", errors="replace")
    code_only = _strip_ps1_strings_and_comments(text)

    if r"\s*sqlalchemy\.url\s*=\s*(.*)" in text:
        issues.append(
            "Unsafe multiline sqlalchemy.url regex using \\s* detected"
        )

    open_braces = code_only.count("{")
    close_braces = code_only.count("}")
    if open_braces != close_braces:
        issues.append(
            f"Unbalanced curly braces: {{={open_braces} vs }}={close_braces}"
        )

    open_parens = code_only.count("(")
    close_parens = code_only.count(")")
    if open_parens != close_parens:
        issues.append(
            f"Unbalanced parentheses: (={open_parens} vs )={close_parens}"
        )

    forbidden_patterns = (
        (r"(?im)\bpip\s+install\b", "pip install"),
        (r"(?im)\bnpm\s+(?:install|ci|update|audit\s+fix)\b", "npm install/ci"),
        (r"(?im)\bflutter\s+pub\s+(?:get|upgrade)\b", "flutter pub get/upgrade"),
        (r"(?im)\balembic\s+(?:upgrade|downgrade|stamp|revision)\b", "alembic mutation"),
        (r"(?im)\binitdb(?:\.exe)?\b", "initdb cluster creation"),
        (r"(?im)\bpg_ctl(?:\.exe)?\s+[^\r\n]*\b(?:start|stop|restart|register)\b", "pg_ctl start/stop/register"),
        (r"(?im)\b(?:Start-Service|Stop-Service|Restart-Service|Set-Service|New-Service)\b", "Windows service mutation"),
        (r"(?im)\b(?:Stop-Process|Remove-Item|Set-Content|Add-Content|Out-File|Clear-Content|New-ItemProperty|Set-ItemProperty)\b", "filesystem/process/registry mutation"),
        (r"(?im)\bgit\s+(?:checkout|reset|clean|commit|push|merge|rebase|stash)\b", "git state mutation"),
    )
    for pattern, label in forbidden_patterns:
        if re.search(pattern, code_only):
            issues.append(f"Forbidden mutating pattern detected in active code: {label}")

    required_markers = (
        "Invoke-RepoChecks",
        "Invoke-PythonBackendChecks",
        "Invoke-BackendEnvChecks",
        "Invoke-PostgresChecks",
        "Invoke-AlembicChecks",
        "Invoke-ProductImportChecks",
        "Invoke-DashboardChecks",
        "Invoke-FlutterChecks",
        "Invoke-PortRuntimeChecks",
        "Invoke-HealthChecks",
        "[PASS]",
        "[WARN]",
        "[FAIL]",
        "[INFO]",
        "PASS:",
        "WARN:",
        "FAIL:",
    )
    for marker in required_markers:
        if marker not in text:
            issues.append(f"Missing required diagnostic marker/function: {marker}")

    return issues

def run_probe_cli(repo_root: Path, binaries_present: bool, port_5432_listening: bool) -> dict[str, Any]:
    """Run all Python-assisted read-only checks and return a sanitized JSON dictionary."""
    backend_root = repo_root / "wa_backend"
    env_file = backend_root / ".env"
    req_file = backend_root / "requirements.txt"
    alembic_ini = backend_root / "alembic.ini"
    versions_dir = backend_root / "alembic" / "versions"

    dotenv_vals = parse_dotenv_file(env_file)

    def _effective(name: str, default: str = "") -> str:
        if name in os.environ:
            return os.environ[name]
        return dotenv_vals.get(name, default)

    # Check inherited env vs .env conflicts
    env_conflicts: list[str] = []
    for key in ("DATABASE_URL", "DATABASE_URL_MIGRATION", "SECRET_KEY"):
        if key in os.environ and key in dotenv_vals and os.environ[key] != dotenv_vals[key]:
            env_conflicts.append(key)

    # SECRET_KEY check (never output value)
    secret_key = _effective("SECRET_KEY", "")
    secret_key_status = "PASS"
    secret_key_reason = "SECRET_KEY is present and meets length/complexity rules (value redacted)."
    if not secret_key:
        secret_key_status = "FAIL"
        secret_key_reason = "SECRET_KEY is missing in wa_backend/.env and process environment."
    elif len(secret_key) < 32:
        secret_key_status = "FAIL"
        secret_key_reason = f"SECRET_KEY length ({len(secret_key)}) is below the 32-character minimum in config.py."
    elif not (
        re.search(r"[A-Z]", secret_key)
        and re.search(r"[a-z]", secret_key)
        and re.search(r"[0-9]", secret_key)
    ):
        secret_key_status = "FAIL"
        secret_key_reason = "SECRET_KEY must contain uppercase, lowercase, and numeric characters (config.py S-08)."

    raw_db_url = _effective("DATABASE_URL", "")
    raw_mig_url = _effective("DATABASE_URL_MIGRATION", "")
    db_parsed = parse_postgres_dsn(raw_db_url)
    mig_parsed = parse_postgres_dsn(raw_mig_url) if raw_mig_url else None

    target_mismatch = False
    if db_parsed.get("valid") and mig_parsed and mig_parsed.get("valid"):
        target_mismatch = (
            db_parsed["host"].lower().rstrip("."),
            int(db_parsed["port"]),
            db_parsed["database"],
        ) != (
            mig_parsed["host"].lower().rstrip("."),
            int(mig_parsed["port"]),
            mig_parsed["database"],
        )

    # Connection budget math from config.py & resource_budget.py
    budget_errors: list[str] = []
    deployment_budget = 60
    try:
        web_conc = int(_effective("WEB_CONCURRENCY", "4"))
        app_budget = int(_effective("DB_APP_CONNECTION_BUDGET", "20"))
        pool_size = int(_effective("DB_POOL_SIZE", "5"))
        max_overflow = int(_effective("DB_MAX_OVERFLOW", "0"))
        deployment_budget = int(_effective("DB_DEPLOYMENT_CONNECTION_BUDGET", "60"))
        op_procs = int(_effective("OPERATIONAL_WORKER_PROCESS_COUNT", "2"))
        op_max = int(_effective("OPERATIONAL_WORKER_DB_POOL_MAX", "5"))
        import_budget = int(_effective("PRODUCT_IMPORT_DB_CONNECTION_BUDGET", "16"))
        pi_q_min = int(_effective("PRODUCT_IMPORT_QUEUE_POOL_MIN", "1"))
        pi_q_max = int(_effective("PRODUCT_IMPORT_QUEUE_POOL_MAX", "2"))
        pi_exec = int(_effective("PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS", "2"))
        pi_ctrl = int(_effective("PRODUCT_IMPORT_CONTROL_WORKER_SLOTS", "1"))
        pi_maint = int(_effective("PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS", "1"))

        web_total = (pool_size + max_overflow) * web_conc
        if web_total > app_budget:
            budget_errors.append(
                f"Web SQLAlchemy connections ({web_total}) exceed DB_APP_CONNECTION_BUDGET ({app_budget})."
            )
        op_reserved = op_procs * op_max
        deploy_reserved = web_total + op_reserved + import_budget
        if deploy_reserved > deployment_budget:
            budget_errors.append(
                f"Deployment reserved connections ({deploy_reserved}) exceed DB_DEPLOYMENT_CONNECTION_BUDGET ({deployment_budget})."
            )
        pi_estimated = (3 * pi_q_max) + (2 * pi_exec) + (2 * pi_maint) + pi_ctrl
        if pi_q_min > pi_q_max:
            budget_errors.append("PRODUCT_IMPORT_QUEUE_POOL_MIN exceeds PRODUCT_IMPORT_QUEUE_POOL_MAX.")
        if pi_exec > pool_size:
            budget_errors.append("PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS exceeds DB_POOL_SIZE.")
        if pi_estimated > import_budget:
            budget_errors.append(
                f"Product Import estimated peak connections ({pi_estimated}) exceed PRODUCT_IMPORT_DB_CONNECTION_BUDGET ({import_budget})."
            )
    except ValueError as exc:
        budget_errors.append(f"Invalid integer in connection budget setting: {redact_secrets(str(exc))}")

    alembic_ini_clean = False
    if alembic_ini.is_file():
        ini_raw = alembic_ini.read_text(encoding="utf-8", errors="replace")
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(ini_raw)
        alembic_ini_clean = (
            is_alembic_ini_url_blank(ini_raw)
            and cp.get("alembic", "sqlalchemy.url", fallback="").strip() == ""
        )

    alembic_heads = resolve_alembic_repo_heads(versions_dir)
    reqs = check_requirements(req_file)
    localhost_risk = detect_localhost_loopback_risk(raw_db_url or raw_mig_url, platform_name="win32")

    db_probe = None
    if db_parsed.get("valid"):
        db_probe = probe_database_readonly(
            raw_db_url,
            binaries_present=binaries_present,
            port_listening=port_5432_listening,
            expected_heads=alembic_heads.get("heads", []),
            deployment_budget=deployment_budget,
        )

    return {
        "python": {
            "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "compatible": (sys.version_info.major, sys.version_info.minor) >= MIN_PYTHON_VERSION,
            "executable": sys.executable,
        },
        "requirements": reqs,
        "env": {
            "env_file_exists": env_file.is_file(),
            "env_conflicts": env_conflicts,
            "secret_key_status": secret_key_status,
            "secret_key_reason": secret_key_reason,
            "database_url": db_parsed,
            "database_url_migration": mig_parsed,
            "target_mismatch": target_mismatch,
            "budget_errors": budget_errors,
            "localhost_risk": localhost_risk,
        },
        "alembic": {
            "alembic_ini_exists": alembic_ini.is_file(),
            "alembic_ini_url_blank": alembic_ini_clean,
            "repo_heads": alembic_heads,
        },
        "db_probe": db_probe,
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--binaries-present", action="store_true")
    parser.add_argument("--port-5432-listening", action="store_true")
    args = parser.parse_args()

    payload = run_probe_cli(
        args.repo_root.resolve(),
        binaries_present=args.binaries_present,
        port_5432_listening=args.port_5432_listening,
    )
    print(json.dumps(payload, ensure_ascii=True))

if __name__ == "__main__":
    main()
