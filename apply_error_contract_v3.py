from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path


EXPECTED_HEAD = "9f2cec60fdbf65316e47b166cfcc935e74dcbde5"
ROOT = Path(__file__).resolve().parent

EXPECTED_TEXT_SHA256 = {
    Path("wa_backend/main.py"): "79878de0e0549d12c42afd447063c3db63d404e23762323f7a6d50878fd59210",
    Path("dashboard/src/lib/apiErrors.ts"): "37adf302eef8a522702796e426e68be082f1fb93f0bd64508c71cef896b84423",
    Path("dashboard/src/lib/apiErrors.test.ts"): "69e18a3920c4a7884d1bdfa49e11a280ad444d91343d7211391b361952749927",
    Path("wa_backend/scripts/gate_error_contract.py"): "c89e77821a9fc6f7803e9af833aa9d5672bed7354b677bd6fc09b051203e2e1a",
}


def fail(message: str) -> None:
    print(f"ERROR_CONTRACT_V3_PATCH_ABORTED: {message}", file=sys.stderr)
    raise SystemExit(1)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected anchor exactly once, found {count}")
    return text.replace(old, new, 1)


# Fail closed against the exact successful v2 output before changing any byte.
head = git("rev-parse", "HEAD")
if head != EXPECTED_HEAD:
    fail(f"HEAD mismatch. expected={EXPECTED_HEAD} actual={head}")

originals: dict[Path, str] = {}
for rel, expected_hash in EXPECTED_TEXT_SHA256.items():
    path = ROOT / rel
    if not path.is_file():
        fail(f"missing target file: {rel}")
    value = path.read_text(encoding="utf-8")
    actual_hash = text_sha256(value)
    if actual_hash != expected_hash:
        fail(
            f"{rel}: v2 baseline mismatch. "
            f"expected_sha256={expected_hash} actual_sha256={actual_hash}"
        )
    originals[rel] = value

updated = dict(originals)


# 1) Backend: catch Starlette's base HTTP exception so automatic 404/405
#    responses use the same canonical contract as FastAPI-raised errors.
main_rel = Path("wa_backend/main.py")
main = updated[main_rel]

main = replace_once(
    main,
    "from fastapi.exceptions import HTTPException, RequestValidationError\n"
    "from fastapi.middleware.cors import CORSMiddleware\n",
    "from fastapi.exceptions import HTTPException, RequestValidationError\n"
    "from fastapi.middleware.cors import CORSMiddleware\n"
    "from starlette.exceptions import HTTPException as StarletteHTTPException\n",
    "main.py Starlette HTTPException import anchor",
)

main = replace_once(
    main,
    "@app.exception_handler(HTTPException)\n"
    "async def custom_http_exception_handler(request: Request, exc: HTTPException):\n",
    "@app.exception_handler(StarletteHTTPException)\n"
    "async def custom_http_exception_handler(\n"
    "    request: Request,\n"
    "    exc: StarletteHTTPException,\n"
    "):\n",
    "main.py Starlette HTTPException handler anchor",
)
updated[main_rel] = main


# 2) Dashboard: redact every 5xx before translated-code rendering so even
#    INTERNAL_SERVER_ERROR keeps its request reference without leaking details.
api_rel = Path("dashboard/src/lib/apiErrors.ts")
api = updated[api_rel]

old_render_order = '''  if (code) {
    const key =
      `errors.codes.${code}`;
    if (i18n.exists(key)) {
      return i18n.t(key, context);
    }
  }

  // Never expose an unexpected 5xx implementation message to the user.
  if (
    typeof status === "number" &&
    status >= 500
  ) {
    return requestId
      ? i18n.t(
          "errors.unexpectedWithReference",
          { requestId }
        )
      : fallback;
  }
'''

new_render_order = '''  // Handle every 5xx before code translation: internal details stay hidden,
  // while the request reference remains visible for production diagnosis.
  if (
    typeof status === "number" &&
    status >= 500
  ) {
    return requestId
      ? i18n.t(
          "errors.unexpectedWithReference",
          { requestId }
        )
      : fallback;
  }

  if (code) {
    const key =
      `errors.codes.${code}`;
    if (i18n.exists(key)) {
      return i18n.t(key, context);
    }
  }
'''

api = replace_once(
    api,
    old_render_order,
    new_render_order,
    "apiErrors.ts 5xx-before-translation anchor",
)
updated[api_rel] = api


# 3) Frontend regression test: the real translated 500 code must still show
#    the request reference and must not expose server internals.
test_rel = Path("dashboard/src/lib/apiErrors.test.ts")
test = updated[test_rel]

test_anchor = '''  it("keeps an unknown deterministic 4xx reason and diagnostics", () => {
'''

test_replacement = '''  it("shows the request reference for a translated 5xx code", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 500,
        code: "INTERNAL_SERVER_ERROR",
        serverMessage:
          "database password and stack trace",
        requestId: "req-translated-500",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "req-translated-500"
    );
    expect(shown).not.toContain(
      "database password"
    );
  });

  it("keeps an unknown deterministic 4xx reason and diagnostics", () => {
'''

test = replace_once(
    test,
    test_anchor,
    test_replacement,
    "apiErrors.test.ts translated-500 test anchor",
)
updated[test_rel] = test


# 4) Gate: pin both fixes and verify the FastAPI/Starlette inheritance used by
#    the broader handler registration.
gate_rel = Path("wa_backend/scripts/gate_error_contract.py")
gate = updated[gate_rel]

gate = replace_once(
    gate,
    "from pathlib import Path\n",
    "from pathlib import Path\n\n"
    "from fastapi.exceptions import HTTPException as FastAPIHTTPException\n"
    "from starlette.exceptions import HTTPException as StarletteHTTPException\n",
    "gate_error_contract.py imports anchor",
)

gate = replace_once(
    gate,
    '''check("await custom_send({" in main and '"status": 413' in main, "413 uses request-id middleware path")

check("normalizeApiErrorResponse" in fetch, "dashboard centralized response normalization")
''',
    '''check("await custom_send({" in main and '"status": 413' in main, "413 uses request-id middleware path")
check(
    "from starlette.exceptions import HTTPException as StarletteHTTPException" in main,
    "Starlette HTTPException import",
)
check(
    "@app.exception_handler(StarletteHTTPException)" in main
    and "exc: StarletteHTTPException" in main,
    "automatic 404/405 use canonical HTTP handler",
)
check(
    issubclass(FastAPIHTTPException, StarletteHTTPException),
    "FastAPI HTTPException is covered by Starlette base handler",
)

check("normalizeApiErrorResponse" in fetch, "dashboard centralized response normalization")
''',
    "gate_error_contract.py Starlette handler checks anchor",
)

gate = replace_once(
    gate,
    '''check("status >= 500" in api, "5xx detail redaction")
check("serverReasonWithCodeAndReference" in api, "unknown 4xx diagnostic fallback")
''',
    '''check("status >= 500" in api, "5xx detail redaction")
check(
    api.index("status >= 500") < api.index("i18n.exists(key)"),
    "5xx redaction runs before translated-code rendering",
)
check(
    "req-translated-500" in (ROOT / "dashboard/src/lib/apiErrors.test.ts").read_text(encoding="utf-8"),
    "translated 5xx request-id regression test",
)
check("serverReasonWithCodeAndReference" in api, "unknown 4xx diagnostic fallback")
''',
    "gate_error_contract.py 5xx ordering checks anchor",
)
updated[gate_rel] = gate


# Validate every transformation before the first write.
for rel, value in updated.items():
    if value == originals[rel]:
        fail(f"no change produced for expected target: {rel}")
    if not value.strip():
        fail(f"refusing empty output: {rel}")

compile(updated[main_rel], str(main_rel), "exec")
compile(updated[gate_rel], str(gate_rel), "exec")

for rel, value in updated.items():
    (ROOT / rel).write_text(value, encoding="utf-8", newline="\n")

print("ERROR_CONTRACT_V3_PATCH_APPLIED_OK")
print("CHANGED_FILES=")
for rel in updated:
    print(f"  {rel}")
