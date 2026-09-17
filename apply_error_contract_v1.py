from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXPECTED_HEAD = "9f2cec60fdbf65316e47b166cfcc935e74dcbde5"

ROOT = Path(__file__).resolve().parent

TARGETS = [
    Path("wa_backend/main.py"),
    Path("dashboard/src/hooks/useAuthFetch.ts"),
    Path("dashboard/src/lib/apiErrors.ts"),
    Path("dashboard/src/i18n/resources.ts"),
    Path(".rules"),
    Path("AGENTS.md"),
]

NEW_FILES = [
    Path("dashboard/src/lib/apiErrors.test.ts"),
    Path("wa_backend/scripts/gate_error_contract.py"),
]


def fail(message: str) -> None:
    print(f"ERROR_CONTRACT_PATCH_ABORTED: {message}", file=sys.stderr)
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


def require_once(text: str, anchor: str, label: str) -> None:
    count = text.count(anchor)
    if count != 1:
        fail(f"{label}: expected anchor exactly once, found {count}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    require_once(text, old, label)
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 0) Fail closed before touching any file.
# ---------------------------------------------------------------------------
head = git("rev-parse", "HEAD")
if head != EXPECTED_HEAD:
    fail(f"HEAD mismatch. expected={EXPECTED_HEAD} actual={head}")

for rel in TARGETS:
    path = ROOT / rel
    if not path.is_file():
        fail(f"missing target file: {rel}")
    result = subprocess.run(
        ["git", "diff", "--quiet", "--", str(rel)],
        cwd=ROOT,
    )
    if result.returncode != 0:
        fail(f"tracked target has local changes: {rel}")

for rel in NEW_FILES:
    if (ROOT / rel).exists():
        fail(f"new file already exists: {rel}")

originals = {
    rel: (ROOT / rel).read_text(encoding="utf-8")
    for rel in TARGETS
}
updated = dict(originals)

# ---------------------------------------------------------------------------
# 1) Backend: one canonical error envelope + legacy compatibility.
# ---------------------------------------------------------------------------
main_rel = Path("wa_backend/main.py")
main = updated[main_rel]

rate_anchor = '''# S-02: Global rate limiter (1000 req/min default per IP)
# +++ رفع السقف هندسياً لمنع تداخل اختبارات الضغط (180 طلب) مع اختبارات المصادقة اللاحقة +++
limiter = Limiter(key_func=get_real_ip, default_limits=["1000/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429,
    content={"message": "تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة لاحقاً."},
))
'''

rate_replacement = '''# عقد الأخطاء المركزي: يحافظ على message القديم ويضيف error موحداً لكل العملاء الجدد.
def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else "N/A"


def _error_contract(
    *,
    status_code: int,
    detail,
    request_id: str,
) -> dict:
    code = f"HTTP_{int(status_code)}"
    message = "Request failed."
    context: dict = {}

    if isinstance(detail, dict):
        raw_code = detail.get("code")
        raw_message = detail.get("message")
        raw_context = detail.get("context")

        if isinstance(raw_code, str) and raw_code.strip():
            code = raw_code.strip()
        if isinstance(raw_message, str) and raw_message.strip():
            message = raw_message.strip()
        if isinstance(raw_context, dict):
            context = raw_context
    elif isinstance(detail, str) and detail.strip():
        message = detail.strip()

    return {
        "code": code,
        "message": message,
        "context": context,
        "request_id": request_id,
    }


def _error_response_payload(
    *,
    status_code: int,
    legacy_message,
    request_id: str,
    canonical_detail=None,
) -> dict:
    detail = legacy_message if canonical_detail is None else canonical_detail
    return {
        # Backward compatibility for current mobile/dashboard consumers.
        "message": legacy_message,
        # Canonical contract for all new/updated clients.
        "error": _error_contract(
            status_code=status_code,
            detail=detail,
            request_id=request_id,
        ),
    }


# S-02: Global rate limiter (1000 req/min default per IP)
# +++ رفع السقف هندسياً لمنع تداخل اختبارات الضغط (180 طلب) مع اختبارات المصادقة اللاحقة +++
limiter = Limiter(key_func=get_real_ip, default_limits=["1000/minute"])
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    legacy_message = "تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة لاحقاً."
    request_id = _request_id(request)
    return JSONResponse(
        status_code=429,
        content=_error_response_payload(
            status_code=429,
            legacy_message=legacy_message,
            request_id=request_id,
            canonical_detail={
                "code": "RATE_LIMITED",
                "message": legacy_message,
                "context": {},
            },
        ),
    )
'''
main = replace_once(main, rate_anchor, rate_replacement, "main.py rate-limit/error-contract anchor")

middleware_anchor = '''class WanasahRawASGIMiddleware:
    def __init__(self, app):
        self.app = app
        self.max_body_size = 10 * 1024 * 1024
        self.limit_body = json.dumps({"message": "حجم الطلب يتجاوز الحد المسموح (10MB)."}).encode('utf-8')

        # تجهيز الهيدرز مسبقاً لعدم استهلاك الـ CPU مع كل طلب
        self.sec_headers = [
            (b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self ws: wss: http: https:'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), interest-cohort=()")
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # 1. فحص الحجم المباشر (Fast Path)
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length and int(content_length) > self.max_body_size:
                await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": self.limit_body})
                return

        # 2. حقن Request ID بذاكرة النطاق
        req_id_str = str(uuid.uuid4())
        req_id_bytes = req_id_str.encode("ascii")
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = req_id_str

        # 3. اعتراض الـ send لحقن الهيدرز دون استنساخ كائنات Starlette
        async def custom_send(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(self.sec_headers)
                headers.append((b"x-request-id", req_id_bytes))
            await send(message)

        try:
            await self.app(scope, receive, custom_send)
        except asyncio.CancelledError:
            # صيد الانقطاع المفاجئ بصمت لمنع تسريب الاتصالات وانهيار الـ Event Loop
            raise
'''

middleware_replacement = '''class WanasahRawASGIMiddleware:
    def __init__(self, app):
        self.app = app
        self.max_body_size = 10 * 1024 * 1024
        self.limit_message = "حجم الطلب يتجاوز الحد المسموح (10MB)."

        # تجهيز الهيدرز مسبقاً لعدم استهلاك الـ CPU مع كل طلب
        self.sec_headers = [
            (b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self ws: wss: http: https:'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), interest-cohort=()")
        ]

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # أنشئ رقم التتبع قبل أي رفض، بما في ذلك 413.
        req_id_str = str(uuid.uuid4())
        req_id_bytes = req_id_str.encode("ascii")
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = req_id_str

        async def custom_send(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.extend(self.sec_headers)
                headers.append((b"x-request-id", req_id_bytes))
            await send(message)

        # فحص الحجم المباشر مع نفس عقد الأخطاء ورقم التتبع.
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            content_length = headers.get(b"content-length")
            if content_length and int(content_length) > self.max_body_size:
                payload = _error_response_payload(
                    status_code=413,
                    legacy_message=self.limit_message,
                    request_id=req_id_str,
                    canonical_detail={
                        "code": "REQUEST_TOO_LARGE",
                        "message": self.limit_message,
                        "context": {"max_bytes": self.max_body_size},
                    },
                )
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                await custom_send({
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")],
                })
                await custom_send({
                    "type": "http.response.body",
                    "body": body,
                })
                return

        try:
            await self.app(scope, receive, custom_send)
        except asyncio.CancelledError:
            # صيد الانقطاع المفاجئ بصمت لمنع تسريب الاتصالات وانهيار الـ Event Loop
            raise
'''
main = replace_once(main, middleware_anchor, middleware_replacement, "main.py middleware anchor")

handlers_anchor = '''# +++ المترجم العسكري: تحويل detail الخاصة بـ FastAPI إلى message مع الحفاظ على الترويسات +++
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code, 
        content={"message": exc.detail},
        headers=exc.headers
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # +++ سحب أول خطأ من Pydantic لحماية تطبيق الموبايل من الانهيار بـ Array +++
    error_msg = exc.errors()[0].get("msg", "بيانات غير صالحة")
    return JSONResponse(status_code=422, content={"message": f"خطأ إدخال: {error_msg}"})
'''

handlers_replacement = '''# عقد HTTP موحد مع إبقاء message القديم للتوافق مع العملاء الحاليين.
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    request_id = _request_id(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response_payload(
            status_code=exc.status_code,
            legacy_message=exc.detail,
            request_id=request_id,
        ),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # لا نعيد input الخام حتى لا نسرب أسراراً أو بيانات حساسة.
    errors = exc.errors()
    first = errors[0] if errors else {}
    error_msg = first.get("msg", "بيانات غير صالحة")
    location = [
        str(part)
        for part in first.get("loc", ())
        if part not in ("body", "query", "path", "header", "cookie")
    ]
    context = {
        "field": ".".join(location) if location else None,
        "type": first.get("type"),
    }
    legacy_message = f"خطأ إدخال: {error_msg}"
    return JSONResponse(
        status_code=422,
        content=_error_response_payload(
            status_code=422,
            legacy_message=legacy_message,
            request_id=_request_id(request),
            canonical_detail={
                "code": "VALIDATION_ERROR",
                "message": legacy_message,
                "context": context,
            },
        ),
    )
'''
main = replace_once(main, handlers_anchor, handlers_replacement, "main.py HTTP/validation handlers anchor")

global_return_anchor = '''    return JSONResponse(
        status_code=500,
        content={
            "message": "خطأ داخلي في الخادم. يرجى مراجعة سجلات النظام."
        }
    )
'''

global_return_replacement = '''    legacy_message = "خطأ داخلي في الخادم. يرجى مراجعة سجلات النظام."
    return JSONResponse(
        status_code=500,
        content=_error_response_payload(
            status_code=500,
            legacy_message=legacy_message,
            request_id=request_id,
            canonical_detail={
                "code": "INTERNAL_SERVER_ERROR",
                "message": legacy_message,
                "context": {},
            },
        ),
    )
'''
main = replace_once(main, global_return_anchor, global_return_replacement, "main.py global 500 anchor")
updated[main_rel] = main

# ---------------------------------------------------------------------------
# 2) Dashboard transport: normalize canonical + legacy errors centrally.
# ---------------------------------------------------------------------------
fetch_rel = Path("dashboard/src/hooks/useAuthFetch.ts")
fetch_ts = updated[fetch_rel]

import_anchor = '''import i18n from "@/i18n";
'''
import_replacement = '''import i18n from "@/i18n";
import { normalizeApiErrorResponse } from "@/lib/apiErrors";
'''
fetch_ts = replace_once(fetch_ts, import_anchor, import_replacement, "useAuthFetch import anchor")

type_anchor = '''export type HttpError = Error & {
  status: number;
  data: unknown;
  code?: string;
};

const makeHttpError = (
  message: string,
  status: number,
  data: unknown = null,
  code?: string
): HttpError => {
  const error = new Error(
    message
  ) as HttpError;
  error.status = status;
  error.data = data;
  if (code) error.code = code;
  return error;
};

const extractCode = (
  data: unknown
): string | undefined => {
  if (
    !data ||
    typeof data !== "object" ||
    !("detail" in data)
  ) {
    return undefined;
  }
  const detail = (
    data as { detail?: unknown }
  ).detail;
  if (
    detail &&
    typeof detail === "object" &&
    "code" in detail &&
    typeof detail.code === "string"
  ) {
    return detail.code;
  }
  return undefined;
};
'''

type_replacement = '''export type HttpError = Error & {
  status: number;
  data: unknown;
  code?: string;
  context?: Record<string, unknown>;
  requestId?: string;
  serverMessage?: string;
};

const makeHttpError = (
  message: string,
  status: number,
  data: unknown = null,
  code?: string,
  context?: Record<string, unknown>,
  requestId?: string,
  serverMessage?: string
): HttpError => {
  const error = new Error(
    message
  ) as HttpError;
  error.status = status;
  error.data = data;
  if (code) error.code = code;
  if (context) error.context = context;
  if (requestId) error.requestId = requestId;
  if (serverMessage) {
    error.serverMessage = serverMessage;
  }
  return error;
};
'''
fetch_ts = replace_once(fetch_ts, type_anchor, type_replacement, "useAuthFetch HttpError/extractCode anchor")

invalid_anchor = '''            throw makeHttpError(
              i18n.t(
                "network.invalidResponse"
              ),
              502,
              null,
              "INVALID_SERVER_RESPONSE"
            );
'''
invalid_replacement = '''            throw makeHttpError(
              i18n.t(
                "network.invalidResponse"
              ),
              502,
              null,
              "INVALID_SERVER_RESPONSE",
              undefined,
              res.headers.get(
                "X-Request-Id"
              ) || undefined
            );
'''
fetch_ts = replace_once(fetch_ts, invalid_anchor, invalid_replacement, "useAuthFetch invalid JSON anchor")

error_anchor = '''        if (!res.ok) {
          const code =
            extractCode(data);

          if (
            res.status === 403 &&
            !cleanPath.startsWith(
              "/inventory/access/me"
            )
          ) {
            window.dispatchEvent(
              new Event(
                "inventory-permission-denied"
              )
            );
          }

          if (
            res.status === 403 &&
            code ===
              "ACCOUNT_DISABLED"
          ) {
            forceLogout();
          }

          throw makeHttpError(
            i18n.t(
              "network.serverError"
            ),
            res.status,
            data,
            code
          );
        }
'''

error_replacement = '''        if (!res.ok) {
          const normalized =
            normalizeApiErrorResponse(
              data
            );
          const requestId =
            normalized.requestId ||
            res.headers.get(
              "X-Request-Id"
            ) ||
            undefined;

          if (
            res.status === 403 &&
            !cleanPath.startsWith(
              "/inventory/access/me"
            )
          ) {
            window.dispatchEvent(
              new Event(
                "inventory-permission-denied"
              )
            );
          }

          if (
            res.status === 403 &&
            normalized.code ===
              "ACCOUNT_DISABLED"
          ) {
            forceLogout();
          }

          throw makeHttpError(
            i18n.t(
              "network.serverError"
            ),
            res.status,
            data,
            normalized.code,
            normalized.context,
            requestId,
            normalized.message
          );
        }
'''
fetch_ts = replace_once(fetch_ts, error_anchor, error_replacement, "useAuthFetch response-error anchor")
updated[fetch_rel] = fetch_ts

# ---------------------------------------------------------------------------
# 3) Dashboard error renderer: never silently discard a real server reason.
# ---------------------------------------------------------------------------
api_rel = Path("dashboard/src/lib/apiErrors.ts")
api_errors = r'''import i18n from "@/i18n";

export type NormalizedApiErrorPayload = {
  code?: string;
  message?: string;
  context?: Record<string, unknown>;
  requestId?: string;
};

const asRecord = (
  value: unknown
): Record<string, unknown> | undefined =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;

const readStructuredError = (
  value: unknown
): NormalizedApiErrorPayload | undefined => {
  const record = asRecord(value);
  if (!record) return undefined;

  const code =
    typeof record.code === "string" &&
    record.code.trim()
      ? record.code.trim()
      : undefined;
  const message =
    typeof record.message === "string" &&
    record.message.trim()
      ? record.message.trim()
      : undefined;
  const context =
    asRecord(record.context);
  const requestIdValue =
    record.request_id ??
    record.requestId;
  const requestId =
    typeof requestIdValue === "string" &&
    requestIdValue.trim()
      ? requestIdValue.trim()
      : undefined;

  if (
    !code &&
    !message &&
    !context &&
    !requestId
  ) {
    return undefined;
  }

  return {
    code,
    message,
    context,
    requestId,
  };
};

export function normalizeApiErrorResponse(
  data: unknown
): NormalizedApiErrorPayload {
  const root = asRecord(data);
  if (!root) {
    return {};
  }

  // Canonical contract first, then all supported legacy envelopes.
  for (const candidate of [
    root.error,
    root.message,
    root.detail,
    root,
  ]) {
    const parsed =
      readStructuredError(candidate);
    if (parsed) return parsed;
  }

  const legacyMessage =
    typeof root.message === "string" &&
    root.message.trim()
      ? root.message.trim()
      : typeof root.detail === "string" &&
          root.detail.trim()
        ? root.detail.trim()
        : undefined;

  return legacyMessage
    ? { message: legacyMessage }
    : {};
}

export function apiErrorCode(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  if (
    typeof record.code === "string" &&
    record.code.trim()
  ) {
    return record.code.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).code;
}

export function apiErrorContext(
  error: unknown
): Record<string, unknown> | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  const direct =
    asRecord(record.context);
  if (direct) return direct;

  return normalizeApiErrorResponse(
    record.data
  ).context;
}

export function apiErrorRequestId(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  const direct =
    record.requestId ??
    record.request_id;
  if (
    typeof direct === "string" &&
    direct.trim()
  ) {
    return direct.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).requestId;
}

export function apiErrorServerMessage(
  error: unknown
): string | undefined {
  const record = asRecord(error);
  if (!record) return undefined;

  if (
    typeof record.serverMessage ===
      "string" &&
    record.serverMessage.trim()
  ) {
    return record.serverMessage.trim();
  }

  return normalizeApiErrorResponse(
    record.data
  ).message;
}

export function apiErrorMessage(
  error: unknown,
  fallback: string
): string {
  const code = apiErrorCode(error);
  const context =
    apiErrorContext(error) ?? {};
  const requestId =
    apiErrorRequestId(error);
  const status =
    apiErrorStatus(error);

  if (code) {
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

  const serverMessage =
    apiErrorServerMessage(error);
  if (serverMessage) {
    if (code && requestId) {
      return i18n.t(
        "errors.serverReasonWithCodeAndReference",
        {
          message: serverMessage,
          code,
          requestId,
        }
      );
    }
    if (code) {
      return i18n.t(
        "errors.serverReasonWithCode",
        {
          message: serverMessage,
          code,
        }
      );
    }
    if (requestId) {
      return i18n.t(
        "errors.serverReasonWithReference",
        {
          message: serverMessage,
          requestId,
        }
      );
    }
    return serverMessage;
  }

  if (
    error instanceof Error &&
    !(
      "status" in
      (error as object)
    ) &&
    error.message
  ) {
    return error.message;
  }

  if (code && requestId) {
    return i18n.t(
      "errors.fallbackWithCodeAndReference",
      {
        fallback,
        code,
        requestId,
      }
    );
  }
  if (code) {
    return i18n.t(
      "errors.fallbackWithCode",
      {
        fallback,
        code,
      }
    );
  }
  if (requestId) {
    return i18n.t(
      "errors.fallbackWithReference",
      {
        fallback,
        requestId,
      }
    );
  }

  return fallback;
}

export function apiErrorStatus(
  error: unknown
): number | undefined {
  const record = asRecord(error);
  return (
    record &&
    typeof record.status === "number"
  )
    ? record.status
    : undefined;
}

export function isAmbiguousRequestError(
  error: unknown
): boolean {
  const status =
    apiErrorStatus(error);
  const code =
    apiErrorCode(error);
  return (
    code ===
      "NETWORK_UNAVAILABLE" ||
    code === "REQUEST_TIMEOUT" ||
    status === 0 ||
    status === 408 ||
    (typeof status ===
      "number" &&
      status >= 500)
  );
}
'''
updated[api_rel] = api_errors

# ---------------------------------------------------------------------------
# 4) i18n: central rendering templates + important canonical/shared codes.
# ---------------------------------------------------------------------------
res_rel = Path("dashboard/src/i18n/resources.ts")
resources = updated[res_rel]

ar_anchor = '''      errors: {
        codes: {
          INBOUND_UNIT_COST_INVALID: "أدخل تكلفة شراء صحيحة حتى 6 منازل عشرية.",
'''
ar_replacement = '''      errors: {
        serverReasonWithCodeAndReference:
          "{{message}} — رمز الخطأ: {{code}} — رقم التتبع: {{requestId}}",
        serverReasonWithCode:
          "{{message}} — رمز الخطأ: {{code}}",
        serverReasonWithReference:
          "{{message}} — رقم التتبع: {{requestId}}",
        fallbackWithCodeAndReference:
          "{{fallback}} — رمز الخطأ: {{code}} — رقم التتبع: {{requestId}}",
        fallbackWithCode:
          "{{fallback}} — رمز الخطأ: {{code}}",
        fallbackWithReference:
          "{{fallback}} — رقم التتبع: {{requestId}}",
        unexpectedWithReference:
          "حدث خطأ غير متوقع في الخادم. رقم التتبع: {{requestId}}",
        codes: {
          VALIDATION_ERROR: "بيانات الطلب غير صالحة. راجع الحقول المدخلة.",
          RATE_LIMITED: "تم تجاوز الحد المسموح من الطلبات. حاول مرة أخرى لاحقاً.",
          REQUEST_TOO_LARGE: "حجم الطلب يتجاوز الحد المسموح.",
          INTERNAL_SERVER_ERROR: "حدث خطأ داخلي في الخادم.",
          PRODUCT_LOCATION_REQUIRED: "هذا المنتج غير مربوط بالمستودع المحدد.",
          PRODUCT_LOCATION_INBOUND_DISABLED: "التوريد لهذا المنتج معطّل في المستودع المحدد.",
          INBOUND_UNIT_COST_INVALID: "أدخل تكلفة شراء صحيحة حتى 6 منازل عشرية.",
'''
resources = replace_once(resources, ar_anchor, ar_replacement, "resources.ts Arabic errors anchor")

en_anchor = '''      errors: {
        codes: {
          INBOUND_UNIT_COST_INVALID: "Enter a valid purchase cost with at most 6 decimal places.",
'''
en_replacement = '''      errors: {
        serverReasonWithCodeAndReference:
          "{{message}} — error code: {{code}} — reference: {{requestId}}",
        serverReasonWithCode:
          "{{message}} — error code: {{code}}",
        serverReasonWithReference:
          "{{message}} — reference: {{requestId}}",
        fallbackWithCodeAndReference:
          "{{fallback}} — error code: {{code}} — reference: {{requestId}}",
        fallbackWithCode:
          "{{fallback}} — error code: {{code}}",
        fallbackWithReference:
          "{{fallback}} — reference: {{requestId}}",
        unexpectedWithReference:
          "An unexpected server error occurred. Reference: {{requestId}}",
        codes: {
          VALIDATION_ERROR: "The request data is invalid. Review the entered fields.",
          RATE_LIMITED: "The request limit was exceeded. Try again later.",
          REQUEST_TOO_LARGE: "The request is larger than the allowed limit.",
          INTERNAL_SERVER_ERROR: "An internal server error occurred.",
          PRODUCT_LOCATION_REQUIRED: "This product is not assigned to the selected warehouse.",
          PRODUCT_LOCATION_INBOUND_DISABLED: "Inbound is disabled for this product at the selected warehouse.",
          INBOUND_UNIT_COST_INVALID: "Enter a valid purchase cost with at most 6 decimal places.",
'''
resources = replace_once(resources, en_anchor, en_replacement, "resources.ts English errors anchor")
updated[res_rel] = resources

# ---------------------------------------------------------------------------
# 5) Permanent architecture rule.
# ---------------------------------------------------------------------------
rules_rel = Path(".rules")
rules = updated[rules_rel]
rules_anchor = '''- Backend error contracts must expose stable `code` + structured `context`; localized/fallback message text must never be used as program logic.
'''
rules_replacement = '''- Backend error contracts must expose stable `code` + structured `context`; localized/fallback message text must never be used as program logic.
- Every API failure must also carry a correlation/request id in the canonical error contract so production incidents are traceable directly to server logs.
- Updated dashboard transport must preserve `code`, `context`, safe server reason, and request id. A known translated error must show its translation; an unknown deterministic 4xx must never collapse into a generic message when a safe server reason exists; unexpected 5xx details must stay hidden while the request id is shown.
'''
rules = replace_once(rules, rules_anchor, rules_replacement, ".rules error-observability anchor")
updated[rules_rel] = rules

agents_rel = Path("AGENTS.md")
agents = updated[agents_rel]
agents_anchor = '''- rely on backend error `code` + structured `context`, never localized message text, for program logic;
'''
agents_replacement = '''- rely on backend error `code` + structured `context`, never localized message text, for program logic;
- require every API failure to expose a correlation/request id in the canonical error contract; dashboard transport must preserve code/context/safe reason/request id, show deterministic 4xx reasons instead of generic failures, and hide unexpected 5xx internals while surfacing the request id;
'''
agents = replace_once(agents, agents_anchor, agents_replacement, "AGENTS.md error-observability anchor")
updated[agents_rel] = agents

# ---------------------------------------------------------------------------
# 6) Targeted frontend tests for all supported envelopes.
# ---------------------------------------------------------------------------
test_content = r'''import { describe, expect, it } from "vitest";

import {
  apiErrorMessage,
  normalizeApiErrorResponse,
} from "./apiErrors";

describe("normalizeApiErrorResponse", () => {
  it("prefers the canonical error envelope", () => {
    expect(
      normalizeApiErrorResponse({
        message: "legacy",
        error: {
          code: "PRODUCT_LOCATION_REQUIRED",
          message: "canonical reason",
          context: { location_id: 119 },
          request_id: "req-1",
        },
      })
    ).toEqual({
      code: "PRODUCT_LOCATION_REQUIRED",
      message: "canonical reason",
      context: { location_id: 119 },
      requestId: "req-1",
    });
  });

  it("supports the current backend legacy message object", () => {
    expect(
      normalizeApiErrorResponse({
        message: {
          code: "PRODUCT_LOCATION_REQUIRED",
          message: "legacy reason",
          context: {
            missing_product_variant_ids: [118],
          },
        },
      })
    ).toEqual({
      code: "PRODUCT_LOCATION_REQUIRED",
      message: "legacy reason",
      context: {
        missing_product_variant_ids: [118],
      },
      requestId: undefined,
    });
  });

  it("supports FastAPI detail objects", () => {
    expect(
      normalizeApiErrorResponse({
        detail: {
          code: "SOME_CODE",
          message: "detail reason",
          context: { a: 1 },
        },
      })
    ).toEqual({
      code: "SOME_CODE",
      message: "detail reason",
      context: { a: 1 },
      requestId: undefined,
    });
  });

  it("keeps a legacy string reason", () => {
    expect(
      normalizeApiErrorResponse({
        message: "specific safe reason",
      })
    ).toEqual({
      message: "specific safe reason",
    });
  });
});

describe("apiErrorMessage", () => {
  it("uses the localized known business code", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 409,
        code: "PRODUCT_LOCATION_REQUIRED",
        serverMessage:
          "Every product must be assigned to the warehouse.",
        requestId: "req-2",
      }
    );

    expect(apiErrorMessage(error, "fallback"))
      .toContain("غير مربوط بالمستودع");
  });

  it("does not expose raw unexpected 5xx internals", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 500,
        code: "UNTRANSLATED_500",
        serverMessage:
          "database password and stack trace",
        requestId: "req-secret-test",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "req-secret-test"
    );
    expect(shown).not.toContain(
      "database password"
    );
  });

  it("keeps an unknown deterministic 4xx reason and diagnostics", () => {
    const error = Object.assign(
      new Error("transport fallback"),
      {
        status: 409,
        code: "NEW_BUSINESS_RULE",
        serverMessage:
          "Specific safe business reason.",
        requestId: "req-3",
      }
    );

    const shown = apiErrorMessage(
      error,
      "fallback"
    );
    expect(shown).toContain(
      "Specific safe business reason."
    );
    expect(shown).toContain(
      "NEW_BUSINESS_RULE"
    );
    expect(shown).toContain("req-3");
  });
});
'''

# ---------------------------------------------------------------------------
# 7) Static gate: prevents regression of the central contract.
# ---------------------------------------------------------------------------
gate_content = r'''from pathlib import Path

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
check('"request_id": request_id' in main, "request id in canonical body")
check('"code": "VALIDATION_ERROR"' in main, "validation error code")
check('"code": "RATE_LIMITED"' in main, "rate limit error code")
check('"code": "REQUEST_TOO_LARGE"' in main, "request-too-large error code")
check('"code": "INTERNAL_SERVER_ERROR"' in main, "internal error code")
check("await custom_send({" in main and '"status": 413' in main, "413 uses request-id middleware path")

check("normalizeApiErrorResponse" in fetch, "dashboard centralized response normalization")
check("normalized.context" in fetch, "dashboard preserves error context")
check("normalized.message" in fetch, "dashboard preserves safe server reason")
check('"X-Request-Id"' in fetch, "dashboard preserves response request id")

check("root.error" in api, "canonical frontend envelope")
check("root.message" in api, "legacy message frontend envelope")
check("root.detail" in api, "legacy detail frontend envelope")
check("status >= 500" in api, "5xx detail redaction")
check("serverReasonWithCodeAndReference" in api, "unknown 4xx diagnostic fallback")

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
'''

# ---------------------------------------------------------------------------
# 8) Final validation: every anchor already validated; write only after all
#    target/anchor checks have passed.
# ---------------------------------------------------------------------------
for rel, text in updated.items():
    if text == originals[rel]:
        fail(f"no change produced for expected target: {rel}")

writes = dict(updated)
writes[Path("dashboard/src/lib/apiErrors.test.ts")] = test_content
writes[Path("wa_backend/scripts/gate_error_contract.py")] = gate_content

for rel, text in writes.items():
    if not text.strip():
        fail(f"refusing empty output: {rel}")

for rel, text in writes.items():
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

print("ERROR_CONTRACT_PATCH_APPLIED_OK")
print("CHANGED_FILES=")
for rel in writes:
    print(f"  {rel}")
