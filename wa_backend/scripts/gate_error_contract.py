from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

checks = []

def check(condition: bool, label: str) -> None:
    checks.append((bool(condition), label))

main = (ROOT / "wa_backend/main.py").read_text(encoding="utf-8")
fetch = (ROOT / "dashboard/src/hooks/useAuthFetch.ts").read_text(encoding="utf-8")
api = (ROOT / "dashboard/src/lib/apiErrors.ts").read_text(encoding="utf-8")
resources = (ROOT / "dashboard/src/i18n/resources.ts").read_text(encoding="utf-8")
rules = (ROOT / ".rules").read_text(encoding="utf-8")
agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

check('"error": _error_contract(' in main, "canonical backend error envelope")
check('"message": legacy_message' in main, "legacy message compatibility")
check(main.count('"request_id": request_id') >= 2, "legacy and canonical request id compatibility")
check('"code": "VALIDATION_ERROR"' in main, "validation error code")
check('"code": "RATE_LIMITED"' in main, "rate limit error code")
check('"code": "REQUEST_TOO_LARGE"' in main, "request-too-large error code")
check('"code": "INTERNAL_SERVER_ERROR"' in main, "internal error code")
check("from starlette.exceptions import HTTPException as StarletteHTTPException" in main, "Starlette HTTP exception base imported")
check("@app.exception_handler(StarletteHTTPException)" in main, "404/405 use canonical HTTP handler")
check("await custom_send({" in main and '"status": 413' in main, "413 uses request-id middleware path")

check("normalizeApiErrorResponse" in fetch, "dashboard centralized response normalization")
check("normalized.context" in fetch, "dashboard preserves error context")
check("normalized.message" in fetch, "dashboard preserves safe server reason")
check('"X-Request-Id"' in fetch, "dashboard preserves response request id")

check("root.error" in api, "canonical frontend envelope")
check("root.message" in api, "legacy message frontend envelope")
check("root.detail" in api, "legacy detail frontend envelope")
check("status >= 500" in api, "5xx detail redaction")
status_pos = api.find("status >= 500")
translation_pos = api.find("if (code) {")
check(status_pos != -1 and translation_pos != -1 and status_pos < translation_pos, "5xx redaction precedes code translation")
check("fallbackWithCodeAndReference" in api, "unknown 4xx diagnostic fallback")
check(resources.count("unexpectedWithReference") >= 2, "localized referenced 5xx message")
check(resources.count("unexpected:") >= 2, "localized generic 5xx message")

for code in (
    "VALIDATION_ERROR",
    "RATE_LIMITED",
    "REQUEST_TOO_LARGE",
    "INTERNAL_SERVER_ERROR",
    "PRODUCT_LOCATION_REQUIRED",
    "PRODUCT_LOCATION_INBOUND_DISABLED",
):
    check(resources.count(code) >= 2, f"Arabic/English translation: {code}")

check("correlation/request id" in rules, "permanent error observability rule")
check("correlation/request id" in agents, "agent error observability rule")

failures = [label for ok, label in checks if not ok]
print(f"CHECKS={len(checks)}")
print(f"FAILURES={len(failures)}")
for label in failures:
    print(f"FAIL: {label}")

if failures:
    print("ERROR_CONTRACT_GATE=FAIL")
    raise SystemExit(1)

print("ERROR_CONTRACT_GATE=PASS")
