from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
main = (ROOT / "wa_backend/main.py").read_text(encoding="utf-8")
obs = (ROOT / "wa_backend/observability/http_errors.py").read_text(
    encoding="utf-8"
)
runbook = (
    ROOT / "docs/operations/HTTP_5XX_OBSERVABILITY.md"
).read_text(encoding="utf-8")

checks: list[tuple[bool, str]] = []


def check(condition: bool, label: str) -> None:
    checks.append((bool(condition), label))


check(
    "from observability.http_errors import log_http_server_error" in main,
    "main uses centralized HTTP error observability",
)
check(
    "RotatingFileHandler" not in main
    and "async_log_error" not in main
    and "sanitize_error_message" not in main,
    "main no longer owns ad-hoc error-file logging",
)
check(
    "if int(exc.status_code) >= 500:" in main
    and "handled_http_exception=True" in main,
    "handled HTTP 5xx are logged centrally",
)
check(
    'error_code="INTERNAL_SERVER_ERROR"' in main
    and "handled_http_exception=False" in main,
    "unhandled exceptions use the same central logger",
)
check(
    'detail="Database connection failed",' in main
    and ") from exc" in main,
    "readiness 503 preserves its original cause",
)
check(
    "if int(status_code) < 500:" in obs
    and "return" in obs,
    "observability helper ignores non-5xx responses",
)
check(
    "_HttpServerErrorFilter" in obs
    and '_HTTP_EVENT_MARKER = "wanasah_http_server_error"' in obs,
    "error.log accepts only centralized correlated HTTP incidents",
)
check(
    '"event": "http_server_error"' in obs
    and '"request_id":' in obs
    and '"status_code":' in obs
    and '"error_code":' in obs
    and '"root_cause_type":' in obs
    and '"traceback":' in obs,
    "5xx log event carries incident diagnostics",
)
check(
    "current.__cause__" in obs
    and "current.__context__" in obs,
    "logger recovers explicit and implicit exception causes",
)
check(
    "postgresql(?:\\+[A-Za-z0-9_]+)?://" in obs
    and "SECRET_KEY|PASSWORD|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN" in obs,
    "server log sanitizer redacts common secrets",
)
check(
    "Observability failure must never replace the original API response." in obs,
    "logging failure cannot replace the business/server response",
)
check(
    "Select-String" in runbook
    and "request_id" in runbook
    and "4xx" in runbook
    and "5xx" in runbook,
    "operations runbook documents request-id lookup and log scope",
)

failures = [label for ok, label in checks if not ok]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for label in failures:
    print(f"FAILED_CHECK={label}")

if failures:
    print("HTTP_5XX_OBSERVABILITY_GATE=FAIL")
    sys.exit(1)

print("HTTP_5XX_OBSERVABILITY_GATE=PASS")
