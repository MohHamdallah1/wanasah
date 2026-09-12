from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "dashboard" / "src" / "hooks" / "useAuthFetch.ts"


def fail(msg: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {msg}")


if not TARGET.exists():
    fail("dashboard/src/hooks/useAuthFetch.ts not found.")

text = TARGET.read_text(encoding="utf-8")

replacements = [
    (
        'let failedQueue: Array<{ resolve: (token: string) => void, reject: (err: any) => void }> = [];\n',
        'let failedQueue: Array<{ resolve: (token: string) => void, reject: (err: unknown) => void }> = [];\n',
        "failed_queue_unknown",
    ),
    (
        'const makeHttpError = (message: string, status: number, data: any = null) => {\n'
        '    const error: any = new Error(message);\n'
        '    error.status = status;\n'
        '    error.data = data;\n'
        '    return error;\n'
        '};\n',
        'type HttpError = Error & {\n'
        '    status: number;\n'
        '    data: unknown;\n'
        '};\n\n'
        'const makeHttpError = (\n'
        '    message: string,\n'
        '    status: number,\n'
        '    data: unknown = null\n'
        '): HttpError => {\n'
        '    const error = new Error(message) as HttpError;\n'
        '    error.status = status;\n'
        '    error.data = data;\n'
        '    return error;\n'
        '};\n\n'
        'const getErrorStatus = (error: unknown): number | undefined => {\n'
        '    if (typeof error !== "object" || error === null || !("status" in error)) {\n'
        '        return undefined;\n'
        '    }\n'
        '    const status = (error as { status?: unknown }).status;\n'
        '    return typeof status === "number" ? status : undefined;\n'
        '};\n',
        "typed_http_error",
    ),
    (
        '                            (refreshErr as any)?.status || 401\n',
        '                            getErrorStatus(refreshErr) || 401\n',
        "typed_refresh_error_status",
    ),
    (
        '        } catch (err: any) {\n',
        '        } catch (err: unknown) {\n',
        "typed_outer_catch",
    ),
    (
        "            if (err.name === 'AbortError') {\n",
        "            if (err instanceof Error && err.name === 'AbortError') {\n",
        "typed_abort_check",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"ALREADY_PATCHED={label}")
        continue
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match, found {count}")
    text = text.replace(old, new, 1)
    print(f"PATCHED={label}")

TARGET.write_text(text, encoding="utf-8")

for forbidden in [": any", " as any", "<any>"]:
    if forbidden in text:
        fail(f"explicit any remains: {forbidden}")

checks = {
    "HTTP_ERROR_TYPED": "type HttpError = Error &" in text,
    "UNKNOWN_QUEUE_REJECT": "reject: (err: unknown)" in text,
    "UNKNOWN_OUTER_CATCH": "catch (err: unknown)" in text,
    "SAFE_ABORT_NARROWING": "err instanceof Error && err.name === 'AbortError'" in text,
    "SAFE_STATUS_NARROWING": "getErrorStatus(refreshErr)" in text,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"static verification failed: {failed}")

print("USE_AUTH_FETCH_NO_EXPLICIT_ANY=OK")
print("USE_AUTH_FETCH_TYPED_ERROR_CONTRACT=OK")
print("DASHBOARD_ALIGN_USE_AUTH_FETCH_TYPES_V2=OK")
