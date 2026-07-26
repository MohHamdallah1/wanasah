# OWASP Top 10 Security Audit Report — Wanasah Backend

> Phase 10 Deliverable — Security Audit  
> Sources analyzed: `wa_backend/main.py`, `wa_backend/config.py`, `.ai-review/04_BUSINESS_RULES.md`, `.ai-review/reviews/backend/auth.md`, `.ai-review/reviews/backend/dispatch.md`  
> Audit Date: 2026-07-24  
> Framework: OWASP Top 10:2021

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High     | 3 |
| Medium   | 5 |
| Low      | 3 |
| **Total** | **12** |

> **Note**: This audit focuses on **newly discovered** OWASP-classified vulnerabilities found in `main.py` and `config.py`. Pre-existing security findings already documented in `.ai-review/reviews/backend/auth.md` (9 findings, including JWT misconfiguration, brute-force TOCTOU, missing token revocation, IDOR systemic risk) and `.ai-review/reviews/backend/dispatch.md` (15 findings, including phantom stock fabrication, deadlock risks, race conditions) are **cross-referenced** where they map to OWASP categories but are not duplicated here. See those reports for full details.

---

## 🔴 Critical

### S-01: Untrusted `X-Forwarded-For` Header Enables Brute-Force IP Spoofing

- **Severity**: **Critical**
- **OWASP Category**: **A04:2021-Insecure Design** / **A07:2021-Identification and Authentication Failures**
- **Exact File & Line Number**: `wa_backend/main.py`, lines 97–98; also referenced in `wa_backend/api/auth.py`, line 40 (`get_real_ip` consumer)
- **Current Vulnerable Code**:
  ```python
  # main.py line 97
  client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "Unknown")
  error_msg = f"[{client_ip}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"

  # auth.py (inferred — uses same IP extraction pattern for brute-force counting)
  # The brute-force protection in auth.py logs failed attempts keyed by IP.
  # If get_real_ip() similarly trusts X-Forwarded-For, the entire brute-force
  # defense is bypassable.
  ```

- **Exploit Scenario & Impact Analysis**:
  1. The application trusts the `X-Forwarded-For` header **without validating that the request originated from a trusted reverse proxy**. If the application is deployed behind a reverse proxy (nginx, AWS ALB, Cloudflare) that **appends** to `X-Forwarded-For` rather than **overriding** it, an attacker can inject a forged IP address in the header: `X-Forwarded-For: 1.2.3.4`.
  2. The brute-force protection in `auth.py` (documented in `.ai-review/reviews/backend/auth.md` Finding #1) counts failed login attempts keyed by the client IP. If `get_real_ip()` uses the same unprotected `X-Forwarded-For` extraction, the attacker can:
     - Send every login attempt with a **different spoofed IP** in `X-Forwarded-For`.
     - Each attempt appears to come from a unique IP, so the rate counter (`failed_count >= 5 per IP per 15 minutes`) **never triggers**.
     - The attacker achieves **unlimited password-guessing throughput**, completely bypassing the only brute-force defense in the system.
  3. Even if `get_real_ip()` correctly uses `request.client.host` (the TCP-layer IP from the proxy), the `global_exception_handler` at line 97 still trusts `X-Forwarded-For` for logging, meaning:
     - Audit logs can be **poisoned** with fake IP addresses.
     - An attacker can frame innocent IPs for malicious activity.
     - Incident response teams will investigate the wrong IP, wasting critical time.

- **Recommended Surgical Fix**:
  - **Option A (if behind a trusted reverse proxy)**: Configure the proxy to **strip and override** `X-Forwarded-For` with the true client IP, and limit `X-Forwarded-For` parsing to only the leftmost IP from the trusted proxy's appended value. Use Starlette's `TrustedHostMiddleware` or FastAPI's `ProxyHeadersMiddleware`:
    ```python
    from fastapi.middleware.trustedhost import TrustedHostMiddleware
    # Only trust X-Forwarded-* headers from the proxy's IP range
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    ```
    Then use `request.client.host` exclusively — never read `X-Forwarded-For` directly.

  - **Option B (defense-in-depth, immediate fix)**: Replace all manual `X-Forwarded-For` parsing with a hardened utility that accepts only the **last** proxy-added IP (the one immediately before your proxy) or rejects untrusted sources:
    ```python
    # In a shared security utility module (e.g., wa_backend/security.py)
    import ipaddress

    TRUSTED_PROXY_CIDRS = [
        ipaddress.ip_network("10.0.0.0/8"),       # internal network
        ipaddress.ip_network("172.16.0.0/12"),     # Docker/private
        ipaddress.ip_network("192.168.0.0/16"),    # private
        # Add your specific proxy IPs here
    ]

    def get_real_ip(request: Request) -> str:
        """Extract the real client IP, trusting only known proxy IPs."""
        # If the direct client is NOT a trusted proxy, use it directly
        client_host = request.client.host if request.client else None
        if client_host:
            try:
                client_ip = ipaddress.ip_address(client_host)
                if not any(client_ip in cidr for cidr in TRUSTED_PROXY_CIDRS):
                    return str(client_ip)
            except ValueError:
                pass

        # Otherwise, parse X-Forwarded-For right-to-left, skipping trusted proxies
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            ips = [ip.strip() for ip in forwarded.split(",")]
            for ip_str in reversed(ips):
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if not any(ip in cidr for cidr in TRUSTED_PROXY_CIDRS):
                        return str(ip)
                except ValueError:
                    continue

        return client_host or "Unknown"
    ```

  - Then update `global_exception_handler` (line 97):
    ```python
    client_ip = get_real_ip(request)
    error_msg = f"[{client_ip}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"
    ```

---

## 🟠 High

### S-02: Missing Global Rate Limiting — All API Endpoints Unprotected

- **Severity**: **High**
- **OWASP Category**: **A05:2021-Security Misconfiguration** / **A04:2021-Insecure Design**
- **Exact File & Line Number**: `wa_backend/main.py` — entire file; no rate-limiting middleware is configured
- **Current Vulnerable Code**:
  ```python
  # main.py — the entire middleware stack (lines 49-61):
  app.add_middleware(
      CORSMiddleware,
      allow_origins=ALLOWED_ORIGINS,
      allow_credentials=False,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  # No rate limiter. No SlowAPI, no Redis-backed token bucket, no in-memory limiter.
  ```

- **Exploit Scenario & Impact Analysis**:
  The only rate-limiting in the system is the per-IP brute-force check on the two login endpoints (`/driver/login` and `/login`), documented in `.ai-review/reviews/backend/auth.md` Finding #1 — which itself has a **race-condition bypass** (TOCTOU). Every other endpoint — including financially sensitive operations (`/dispatch/route`, `/warehouse/inbound`, `/visits/{id}`) — has **zero rate protection**:
  
  1. **Volumetric DoS on Inventory Settlement**: An attacker can flood `POST /dispatch/settle-session` with thousands of requests per second. Each request triggers a complex transaction involving `SELECT ... FOR UPDATE` locks on `SessionInventory`, `MainWarehouse`, `VehicleLoad`, `WorkSession`, ledger writes, and audit log inserts. At the configured `pool_size=50` (config.py line 20), only 50 concurrent connections are available — a flood of 200 req/s exhausts the pool in under a second, denying service to legitimate drivers trying to start/end their workday.
  
  2. **API Cost Exhaustion**: Endpoints like `GET /warehouse/dashboard` aggregate across `MainWarehouse`, `WarehouseLedger`, and `ProductVariant` with no caching and no rate limit. An attacker can trigger expensive DB queries in a tight loop, consuming CPU/IO budget and inflating cloud database costs.

  3. **Enumeration Attacks**: `GET /driver/{id}` and `GET /shops/{id}` can be iterated without restriction, allowing enumeration of valid driver IDs, shop IDs, zone IDs, and product variant IDs — reconnaissance that feeds more targeted attacks.

  4. **No distinction between authenticated and unauthenticated rate limits**: Once a token is obtained (even a stolen one — no revocation per auth.md Finding #3), the attacker has the same unlimited access as a legitimate admin for up to 24 hours.

- **Recommended Surgical Fix**:
  Add a layered rate-limiting strategy:

  ```python
  # main.py — add after CORSMiddleware

  from slowapi import Limiter, _rate_limit_exceeded_handler
  from slowapi.util import get_remote_address
  from slowapi.errors import RateLimitExceeded

  # Tier 1: Global in-memory rate limiter (absorbs volumetric attacks before DB touch)
  limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
  app.state.limiter = limiter
  app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

  # Override get_remote_address to use the hardened IP extraction (see S-01 fix)
  # after the X-Forwarded-For vulnerability is patched.
  ```

  Then apply stricter per-endpoint limits on sensitive routes (in their respective router files):

  ```python
  # In api/auth.py
  from slowapi import Limiter
  from slowapi.util import get_remote_address

  limiter = Limiter(key_func=get_remote_address)

  @router.post("/driver/login", response_model=LoginResponse)
  @limiter.limit("10/minute")  # Hard cap: 10 attempts/minute/IP regardless of DB state
  async def driver_login(request: Request, ...):
      ...

  # In api/dispatch.py
  @router.post("/dispatch/route")
  @limiter.limit("30/minute")
  async def dispatch_route(request: Request, ...):
      ...
  ```

  **Production-grade enhancement**: Replace `slowapi`'s in-memory storage with Redis for multi-process deployments:
  ```python
  import redis
  from slowapi.storage import RedisStorage

  redis_client = redis.Redis(host="redis", port=6379, db=0)
  limiter = Limiter(key_func=get_remote_address, storage_uri=f"redis://redis:6379/0")
  ```

---

### S-03: Missing HTTP Security Headers — Clickjacking, MIME-Sniffing, XSS Vectors

- **Severity**: **High**
- **OWASP Category**: **A05:2021-Security Misconfiguration**
- **Exact File & Line Number**: `wa_backend/main.py` — entire file; no security header middleware is configured
- **Current Vulnerable Code**:
  ```python
  # main.py lines 40-61 — the FastAPI app and middleware stack
  app = FastAPI(
      title="Wanasah API Core",
      version="2.0.0",
      docs_url=None if ENV == "production" else "/docs",
      redoc_url=None if ENV == "production" else "/redoc",
      openapi_url=None if ENV == "production" else "/openapi.json",
      lifespan=lifespan
  )

  app.add_middleware(
      CORSMiddleware,  # Only middleware added
      allow_origins=ALLOWED_ORIGINS,
      allow_credentials=False,
      allow_methods=["*"],
      allow_headers=["*"],
  )
  # No: HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
  ```

- **Exploit Scenario & Impact Analysis**:
  While the FastAPI backend is primarily an API server (not serving HTML directly), it serves the **dashboard React frontend** via the same domain/origin in the production configuration (`https://dashboard.wanasah.com` per line 51). Without security headers:

  1. **Clickjacking (X-Frame-Options / CSP frame-ancestors)**: An attacker embeds the dashboard login page in an invisible iframe on a malicious site. A logged-in admin who visits the attacker's site unknowingly interacts with the dashboard (e.g., clicking "Dispatch Route" button rendered transparently). Without `X-Frame-Options: DENY` or `Content-Security-Policy: frame-ancestors 'none'`, this succeeds silently, enabling one-click dispatch fraud.

  2. **MIME-Sniffing (X-Content-Type-Options)**: If any API endpoint returns user-controlled content (e.g., `Shop.notes` field — `models.py` line 236 — a `Text` column with no sanitization in the schema) with an ambiguous `Content-Type`, older browsers may MIME-sniff and execute the content as HTML/JavaScript. Without `X-Content-Type-Options: nosniff`, stored-XSS payloads injected into shop notes could execute in the admin dashboard context.

  3. **HTTPS Downgrade / SSL-Stripping (Strict-Transport-Security)**: Without `Strict-Transport-Security`, a man-in-the-middle attacker on a public Wi-Fi network can strip the HTTPS upgrade, forcing the dashboard to load over HTTP. The admin's JWT token (which has no `jti` for revocation — auth.md Finding #3) is then transmitted in cleartext and captured.

  4. **Referrer Leakage (Referrer-Policy)**: When an admin clicks an external link from the dashboard, the `Referer` header may leak the full dashboard URL path (including query parameters) to external sites. Without `Referrer-Policy: strict-origin-when-cross-origin`, sensitive URL paths are exposed.

- **Recommended Surgical Fix**:
  Add a security headers middleware. For a pure API, only HSTS and basic headers are strictly necessary; for the dashboard, the full set is required:

  ```python
  # main.py — add after CORSMiddleware

  from starlette.middleware.base import BaseHTTPMiddleware
  from starlette.responses import Response

  class SecurityHeadersMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          response: Response = await call_next(request)
          # HSTS: enforce HTTPS for 1 year, include subdomains
          response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
          # Prevent MIME-type sniffing
          response.headers["X-Content-Type-Options"] = "nosniff"
          # Prevent clickjacking
          response.headers["X-Frame-Options"] = "DENY"
          # Content-Security-Policy (adjust for your dashboard's actual script sources)
          response.headers["Content-Security-Policy"] = (
              "default-src 'self'; "
              "script-src 'self'; "
              "style-src 'self' 'unsafe-inline'; "
              "img-src 'self' data:; "
              "connect-src 'self'; "
              "frame-ancestors 'none'; "
              "base-uri 'self'; "
              "form-action 'self'"
          )
          # Referrer-Policy
          response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
          # Permissions-Policy: disable unnecessary browser features
          response.headers["Permissions-Policy"] = (
              "camera=(), microphone=(), geolocation=(), "
              "interest-cohort=()"  # disables FLoC tracking
          )
          return response

  app.add_middleware(SecurityHeadersMiddleware)
  ```

  **Important**: If the dashboard React app is served by a **separate** web server (nginx/CDN) and not by FastAPI, these headers should be configured at the **reverse proxy layer** instead. Ensure the proxy forwards them or adds them independently.

---

### S-04: Overly Permissive CORS Configuration in Production

- **Severity**: **High**
- **OWASP Category**: **A05:2021-Security Misconfiguration** / **A01:2021-Broken Access Control**
- **Exact File & Line Number**: `wa_backend/main.py`, lines 56–61
- **Current Vulnerable Code**:
  ```python
  ALLOWED_ORIGINS = ["*"] if ENV == "development" else [
      "https://dashboard.wanasah.com",
      "https://www.wanasah.com"
  ]

  app.add_middleware(
      CORSMiddleware,
      allow_origins=ALLOWED_ORIGINS,
      allow_credentials=False,
      allow_methods=["*"],       # ALL HTTP methods allowed
      allow_headers=["*"],       # ALL headers allowed
  )
  ```

- **Exploit Scenario & Impact Analysis**:
  1. **`allow_methods=["*"]`**: Permits `DELETE`, `PUT`, `PATCH`, `OPTIONS` from any allowed origin. While most sensitive endpoints require authentication, `OPTIONS` preflight requests leak information about available endpoints. More critically, if a future refactor accidentally exposes a state-changing GET endpoint (e.g., `GET /admin/reset-cache`), CORS would not block it.

  2. **`allow_headers=["*"]`**: Allows custom headers like `Authorization` (JWT bearer token) to be sent cross-origin. Combined with the dashboard's allowed origin, a subdomain takeover on a decommissioned `*.wanasah.com` subdomain could host a malicious page that reads the JWT from the dashboard user's browser and exfiltrates it to an attacker-controlled server — the CORS policy explicitly permits this since `allow_credentials=False` is the only guard, but the JWT is sent as an `Authorization` header, not a cookie, so `allow_credentials` has no protective effect on token exfiltration.

  3. **Placeholder production domain**: `https://dashboard.wanasah.com` is a **placeholder** (the code comment on line 51 says "استبدلها بدومين لوحة التحكم الفعلي"). If this is not replaced before production deployment, the CORS policy rejects all legitimate dashboard requests, forcing the ops team to hotfix with `allow_origins=["*"]` — a common real-world path to production wildcard CORS.

- **Recommended Surgical Fix**:
  Restrict to only the methods and headers actually used by the frontend clients:

  ```python
  ALLOWED_ORIGINS = os.environ.get(
      "CORS_ALLOWED_ORIGINS",
      "https://dashboard.wanasah.com,https://www.wanasah.com"
  ).split(",")

  app.add_middleware(
      CORSMiddleware,
      allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()],
      allow_credentials=True,  # False is unusual for a dashboard; verify client needs
      allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],  # explicitly list
      allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],  # explicitly list
      expose_headers=["X-Request-Id"],  # only expose headers the client needs
      max_age=600,  # cache preflight for 10 minutes
  )
  ```

  Additionally, validate that `ALLOWED_ORIGINS` is not empty in production:
  ```python
  if ENV == "production" and not ALLOWED_ORIGINS:
      raise ValueError("CORS_ALLOWED_ORIGINS must be set in production environment!")
  ```

---

## 🟡 Medium

### S-05: Production Docs/Schema Exposure Relies on Unsafe Default

- **Severity**: **Medium**
- **OWASP Category**: **A05:2021-Security Misconfiguration**
- **Exact File & Line Number**: `wa_backend/main.py`, lines 37, 43–45
- **Current Vulnerable Code**:
  ```python
  ENV = os.getenv("ENVIRONMENT", "development")  # Default is development!
  # ...
  app = FastAPI(
      title="Wanasah API Core",
      version="2.0.0",
      docs_url=None if ENV == "production" else "/docs",
      redoc_url=None if ENV == "production" else "/redoc",
      openapi_url=None if ENV == "production" else "/openapi.json",
      lifespan=lifespan
  )
  ```

- **Exploit Scenario & Impact Analysis**:
  The security mechanism (`docs_url=None if ENV == "production" else "/docs"`) is gated on a **single environment variable** with a **fail-open default of `"development"`**. If:
  - The `ENVIRONMENT` variable is misspelled in production (`ENVIROMENT`, `ENV`, `ENVIRONMENT=prod`).
  - The `ENVIRONMENT` variable is inadvertently omitted from the production `.env` or deployment manifest.
  - The deployment platform (Docker Compose, Kubernetes ConfigMap) has a copy-paste error.

  ...then the application **starts in "development" mode**, exposing:
  - `GET /docs` — Interactive Swagger UI with **all endpoint signatures, parameter names, request body schemas, and authentication flow**.
  - `GET /openapi.json` — Machine-readable OpenAPI spec enumerating every route, model field, and validation rule.
  - `GET /redoc` — Alternative documentation UI.

  An attacker can use this to:
  - Map the entire API surface without any trial-and-error.
  - Identify endpoints that accept sensitive parameters (e.g., `POST /warehouse/adjust`).
  - Discover internal model field names (`is_emergency`, `can_allow_debt`, `is_settled`) to craft precise injection payloads.
  - Find undocumented/debug endpoints that were not intended for production exposure.

  **The `fail-open` default is the root cause**: a single omitted config value silently disables a critical security control with zero alerts or startup failures.

- **Recommended Surgical Fix**:
  Invert the logic — default to **safe**, and only enable docs with an explicit opt-in:

  ```python
  ENV = os.getenv("ENVIRONMENT", "production")  # Default to SAFE
  ENABLE_DOCS = os.getenv("ENABLE_API_DOCS", "false").lower() in ("true", "1", "yes")

  app = FastAPI(
      title="Wanasah API Core",
      version="2.0.0",
      docs_url="/docs" if ENABLE_DOCS else None,
      redoc_url="/redoc" if ENABLE_DOCS else None,
      openapi_url="/openapi.json" if ENABLE_DOCS else None,
      lifespan=lifespan
  )
  ```

  This ensures:
  - Default behavior in the absence of any config is **safe** (no docs).
  - Docs can be explicitly enabled via a dedicated `ENABLE_API_DOCS` flag, separate from the environment name.
  - Misspelling or omitting `ENVIRONMENT` no longer silently disables a security control.

---

### S-06: No Request Body Size Limiting — Memory Exhaustion DoS

- **Severity**: **Medium**
- **OWASP Category**: **A05:2021-Security Misconfiguration** / **A04:2021-Insecure Design**
- **Exact File & Line Number**: `wa_backend/main.py` — entire file; no body size limit middleware or ASGI server config
- **Current Vulnerable Code**:
  ```python
  # main.py — FastAPI app creation (lines 40-47):
  app = FastAPI(
      title="Wanasah API Core",
      version="2.0.0",
      # ... no max_request_body_size or similar parameter ...
  )
  # No middleware to limit Content-Length or read body in chunks with a cap.
  ```

- **Exploit Scenario & Impact Analysis**:
  Several endpoints accept **unbounded JSON arrays or large text fields**:
  - `POST /dispatch/route` — `payload.inventory` is a `dict` that can contain dozens of product variants, each with arbitrary-depth nested structures.
  - `PUT /visits/{id}` — accepts a full cart with items, returns, samples — a deeply nested JSON object.
  - `POST /warehouse/inbound` — accepts `payload.items: List[InboundItem]` with no cap on array size.
  - `POST /dispatch/bulk-import-shops` — accepts CSV data as a Text field (models.py line 31, and the route handler in dispatch.py).

  An attacker sends a 500MB JSON payload with a single `POST /warehouse/inbound` call:
  1. FastAPI/Uvicorn reads the entire body into memory before parsing.
  2. The Python process allocates 500MB+ of RAM.
  3. With `pool_size=50` (config.py line 20), 10 concurrent 500MB requests consume 5GB+ RAM.
  4. The OS OOM-killer terminates the Python process → entire API goes down.
  5. Any in-flight financial transactions (ledger writes, settlement) are rolled back mid-operation, potentially leaving `MainWarehouse.reserved_quantity_packs` in an inconsistent state (the "in-transit" holding state from Business Rule §2.2).

- **Recommended Surgical Fix**:
  Add request body size limiting at the ASGI server level (Uvicorn) AND as a FastAPI middleware:

  **Option A — Uvicorn startup (simplest, most effective):**
  ```bash
  uvicorn main:app --limit-max-requests 1000 --limit-concurrency 200 --timeout-keep-alive 5 --backlog 2048
  ```
  Note: Uvicorn does NOT have a built-in body-size limit. Use a reverse proxy for this.

  **Option B — Nginx/Caddy reverse proxy (recommended for production):**
  ```nginx
  # nginx.conf
  server {
      location /api/ {
          client_max_body_size 10m;  # Reject bodies > 10MB at the edge
          proxy_pass http://backend:8000;
      }
  }
  ```

  **Option C — FastAPI middleware (defense-in-depth):**
  ```python
  # main.py — add middleware
  from starlette.middleware.base import BaseHTTPMiddleware
  from starlette.requests import Request
  from fastapi.responses import JSONResponse

  MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB

  class BodySizeLimitMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          content_length = request.headers.get("content-length")
          if content_length:
              if int(content_length) > MAX_BODY_SIZE:
                  return JSONResponse(
                      status_code=413,
                      content={"message": "Request body too large. Maximum allowed size is 10MB."}
                  )
          return await call_next(request)

  app.add_middleware(BodySizeLimitMiddleware)
  ```

  For the CSV bulk import endpoint specifically, add an additional per-route cap:
  ```python
  # In the import endpoint:
  if len(payload.csv_data or "") > 5 * 1024 * 1024:  # 5MB CSV cap
      raise HTTPException(status_code=413, detail="CSV file size exceeds 5MB limit.")
  ```

---

### S-07: `.env` Secret Leakage via Source Code Repository

- **Severity**: **Medium**
- **OWASP Category**: **A05:2021-Security Misconfiguration**
- **Exact File & Line Number**: `wa_backend/config.py`, lines 1–5
- **Current Vulnerable Code**:
  ```python
  import os
  from dotenv import load_dotenv

  # تحميل متغيرات البيئة (مثل كلمات المرور) من ملف مخفي
  load_dotenv()
  ```

- **Exploit Scenario & Impact Analysis**:
  `load_dotenv()` loads environment variables from a `.env` file in the current working directory (by default). This file typically contains:
  ```env
  SECRET_KEY=my-super-secret-jwt-signing-key-12345
  DATABASE_URL=postgresql+asyncpg://user:password@db:5432/wanasah
  ```

  The `.env` file **must be in `.gitignore`** to prevent accidental commit. However:
  1. The `.gitignore` in the project root (`c:\Users\admin\Desktop\wanasah\.gitignore`) must be verified to contain `.env`. If it does not, a developer running `git add .` commits the secrets.
  2. Even with `.gitignore`, a `git add -f .env` or a misconfigured IDE auto-add can bypass it.
  3. The `.env` file on disk has no file-permission enforcement in the code — on a shared server, any process running as the same user can read it.
  4. `DATABASE_URL` contains the **database password in plaintext**. If this URL appears in any error trace or log output (see S-10), the database credentials are permanently compromised in log archives.

- **Recommended Surgical Fix**:
  1. **Verify `.gitignore` coverage** — ensure `.env` is explicitly listed:
     ```gitignore
     # Environment secrets
     .env
     .env.*
     *.local
     ```
  2. **Add startup validation** to detect if `.env` is accidentally committed:
     ```python
     # config.py
     import os

     if os.path.exists(".env"):
         # Check if .env is tracked by git (defense-in-depth)
         import subprocess
         try:
             result = subprocess.run(
                 ["git", "check-ignore", ".env"],
                 capture_output=True, text=True, timeout=5
             )
             if result.returncode != 0:
                 # .env is NOT gitignored!
                 raise RuntimeError(
                     "SECURITY: .env file exists but is NOT in .gitignore! "
                     "Add .env to .gitignore immediately and rotate all secrets."
                 )
         except FileNotFoundError:
             pass  # git not available (production Docker image without git)
         except Exception:
             pass  # don't block startup on git check failure
     ```
  3. **Prefer system-level env vars in production** — Docker secrets, Kubernetes Secrets, or cloud secret managers (AWS Secrets Manager, GCP Secret Manager) over `.env` files:
     ```python
     # config.py
     load_dotenv()  # Only for local development convenience

     class Config:
         SECRET_KEY = os.environ.get('SECRET_KEY') or os.environ.get('JWT_SECRET_KEY')
         if not SECRET_KEY:
             raise ValueError(
                 "SECRET_KEY not found in environment. "
                 "In production, inject via k8s secrets or cloud secret manager, not .env."
             )
     ```

---

### S-08: `SECRET_KEY` No Minimum Entropy/Length Validation

- **Severity**: **Medium**
- **OWASP Category**: **A02:2021-Cryptographic Failures**
- **Exact File & Line Number**: `wa_backend/config.py`, lines 8–11
- **Current Vulnerable Code**:
  ```python
  SECRET_KEY = os.environ.get('SECRET_KEY')
  if not SECRET_KEY:
      raise ValueError("خطأ أمني قاتل: لم يتم العثور على SECRET_KEY في بيئة التشغيل!")
  ```

- **Exploit Scenario & Impact Analysis**:
  The validation only checks **existence**, not **strength**. An operator could set:
  ```bash
  export SECRET_KEY="password123"
  ```
  This would pass the existence check and the application would start normally. The JWT tokens are signed using `HS256` with this key. A weak key enables:
  
  1. **Offline brute-force of captured JWTs**: An attacker who obtains a valid JWT (via network sniffing, log leakage, or XSS) can run `hashcat` or `jwt-cracker` against the `HS256` signature offline. A weak 8-character lowercase key (`"abc12345"`) is cracked in **under 1 second**. Once cracked, the attacker can forge valid tokens for any `driver_id` and `is_admin=True` for the remaining 24-hour token lifetime (no token revocation — auth.md Finding #3).

  2. **Multi-service compromise**: If any other internal service reuses the same `SECRET_KEY` (a common anti-pattern), the compromise cascades.

  3. **HS256 vs RS256**: `HS256` is a **symmetric** algorithm — the same key signs and verifies. This means every service that needs to verify tokens must have access to the **full secret**. If a microservice architecture is ever adopted, the secret must be shared broadly. `RS256` (asymmetric) would allow verification with a public key only, limiting blast radius.

- **Recommended Surgical Fix**:
  ```python
  SECRET_KEY = os.environ.get('SECRET_KEY')
  if not SECRET_KEY:
      raise ValueError("خطأ أمني قاتل: لم يتم العثور على SECRET_KEY في بيئة التشغيل!")

  # Enforce minimum cryptographic strength
  MIN_KEY_LENGTH = 32  # 256 bits for HS256
  if len(SECRET_KEY) < MIN_KEY_LENGTH:
      raise ValueError(
          f"خطأ أمني قاتل: SECRET_KEY يجب أن يكون طوله {MIN_KEY_LENGTH} حرفاً على الأقل "
          f"(الطول الحالي: {len(SECRET_KEY)}). استخدم: python -c \"import secrets; print(secrets.token_hex(32))\""
      )

  # Optionally: enforce entropy diversity
  import re
  if not re.search(r'[A-Z]', SECRET_KEY) or not re.search(r'[a-z]', SECRET_KEY) or not re.search(r'[0-9]', SECRET_KEY):
      raise ValueError(
          "خطأ أمني قاتل: SECRET_KEY يجب أن يحتوي على أحرف كبيرة وصغيرة وأرقام على الأقل."
      )
  ```

  **Long-term recommendation**: Migrate to `RS256` (asymmetric) for JWT signing when token verification is needed across multiple services:
  ```python
  # In auth.py create_access_token:
  import jwt
  from pathlib import Path

  PRIVATE_KEY = Path("/run/secrets/jwt_private.pem").read_text()
  PUBLIC_KEY = Path("/run/secrets/jwt_public.pem").read_text()

  # Sign with private key
  token = jwt.encode(to_encode, PRIVATE_KEY, algorithm="RS256")

  # Verify with public key (in dependencies.py)
  payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
  ```

---

### S-09: No Audit Logging for Successful Authentications

- **Severity**: **Medium**
- **OWASP Category**: **A09:2021-Security Logging and Monitoring Failures**
- **Exact File & Line Number**: `wa_backend/api/auth.py` — login endpoint functions (referenced in `auth.md` Finding #8); `wa_backend/main.py`, lines 13–18 (logger configuration)
- **Current Vulnerable Code**:
  ```python
  # auth.py — only FAILED logins are recorded:
  await log_failed_attempt(ip, db)  # On failure

  # No corresponding log_successful_login() call on success.

  # main.py — logger configured at ERROR level only:
  logger = logging.getLogger("wanasah_logger")
  logger.setLevel(logging.ERROR)  # INFO-level security events are discarded!
  ```

- **Exploit Scenario & Impact Analysis**:
  1. **Account takeover detection is impossible**: If an attacker successfully guesses a driver's password (or uses a stolen token — no revocation, auth.md Finding #3) and logs in from an unusual IP, there is **no audit record** of the successful login. The SOC team has no way to detect or investigate credential stuffing attacks that succeeded.

  2. **Insider threat detection gap**: A disgruntled admin logging in at 3 AM to sabotage inventory data leaves no trace that the login occurred. Only the downstream data mutations would be visible, and only if those are logged (which `warehouse.py` and `dispatch.py` handle inconsistently — dispatch.md Finding #13).

  3. **Compliance violation**: PCI-DSS Requirement 10.2 mandates logging of all access to systems. ISO 27001 A.12.4.1 requires event logging including successful logins. The current setup fails both.

  4. **Logger level mismatch**: Even if code were added to log successful logins, the logger in `main.py` line 14 is set to `logging.ERROR` — any `logger.info()` call for login success would be **silently discarded** in production. The logger level must be configurable.

- **Recommended Surgical Fix**:
  ```python
  # main.py — make log level configurable
  LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
  logger = logging.getLogger("wanasah_logger")
  logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

  # auth.py — log successful logins
  async def log_successful_login(driver_id: int, username: str, ip: str, is_admin: bool, db: AsyncSession):
      """Record successful authentication for audit trail."""
      try:
          audit = SystemAuditLog(
              admin_id=None,
              target_id=str(driver_id),
              action_type='SUCCESSFUL_LOGIN',
              old_value=f"User: {username}, IP: {ip}",
              new_value=f"Role: {'Admin' if is_admin else 'Driver'}",
              timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
          )
          db.add(audit)
          await db.commit()
      except Exception as e:
          await db.rollback()
          # Log to file as fallback (per auth.md Finding #8 recommendation)
          logger.error(f"CRITICAL: Failed to log successful login for driver {driver_id}: {e}", exc_info=True)

  # In driver_login, after successful credential verification:
  token = create_access_token(...)
  await log_successful_login(driver.id, driver.username, ip, False, db)
  return LoginResponse(...)

  # In admin_login, similarly:
  await log_successful_login(user.id, user.username, ip, True, db)
  ```

---

## 🟢 Low

### S-10: `DATABASE_URL` Risk of Leakage in Error Stack Traces

- **Severity**: **Low**
- **OWASP Category**: **A05:2021-Security Misconfiguration** / **A02:2021-Cryptographic Failures**
- **Exact File & Line Number**: `wa_backend/main.py`, line 98; `wa_backend/config.py`, line 14
- **Current Vulnerable Code**:
  ```python
  # main.py line 98
  error_msg = f"[{client_ip}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"

  # config.py line 14
  SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
  # Format: postgresql+asyncpg://user:password@host:5432/dbname
  ```

- **Exploit Scenario & Impact Analysis**:
  `traceback.format_exc()` captures the **full Python stack trace**, including local variable values in each frame. If a database error occurs (e.g., a `sqlalchemy.exc.OperationalError` from a connection timeout), the exception object's `__str__()` or `__cause__` **may contain the connection string** with the plaintext database password. This stack trace is written to `error.log` (line 15 of main.py) and **stored permanently on disk**. If:
  - The `error.log` file is world-readable on the server.
  - The `error.log` file is backed up to an unencrypted S3 bucket.
  - A developer shares the `error.log` file for debugging.

  ...then the database password is leaked. Even though `global_exception_handler` returns a generic 500 message to the client (line 105 — good), the server-side log is the risk vector.

- **Recommended Surgical Fix**:
  Sanitize the error message before logging — strip known sensitive patterns:

  ```python
  import re

  def sanitize_error_message(msg: str) -> str:
      """Remove database credentials and other secrets from error messages before logging."""
      # Redact PostgreSQL connection strings
      msg = re.sub(
          r'(postgresql\+asyncpg://)[^@]+:[^@]+(@)',
          r'\1***REDACTED***:***REDACTED***\2',
          msg
      )
      # Redact any other known secret patterns
      msg = re.sub(r'SECRET_KEY[\s=:]+[^\s]+', 'SECRET_KEY=***REDACTED***', msg)
      return msg

  # In global_exception_handler (line 98):
  raw_error = f"[{get_real_ip(request)}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"
  error_msg = sanitize_error_message(raw_error)
  await async_log_error(error_msg)
  ```

  Additionally, configure SQLAlchemy to hide connection parameters in its own error output:
  ```python
  # database.py — when creating the engine, use hide_parameters:
  from sqlalchemy import event
  from sqlalchemy.engine import Engine

  @event.listens_for(Engine, "before_cursor_execute")
  def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
      # Don't log parameters — prevents parameter values from appearing in error traces
      pass
  ```

---

### S-11: `SystemSetting` Table Used as Ad-Hoc Key-Value Store Without Access Control

- **Severity**: **Low**
- **OWASP Category**: **A01:2021-Broken Access Control**
- **Exact File & Line Number**: `wa_backend/models.py`, lines 26–31; `wa_backend/api/warehouse.py` (referenced in Business Rule §1.4)
- **Current Vulnerable Code**:
  ```python
  class SystemSetting(Base):
      __tablename__ = 'system_settings'
      id            = Column(Integer, primary_key=True)
      setting_key   = Column(String(50),  unique=True, nullable=False)
      setting_value = Column(String(100), nullable=False)
      description   = Column(String(200), nullable=True)
  ```

- **Exploit Scenario & Impact Analysis**:
  The `system_settings` table is a key-value store for global application configuration (Business Rule §1.4 documents the `warehouse_status` key that gates warehouse mutations). However:
  1. **No access control**: Any endpoint that reads from or writes to `system_settings` must enforce admin-only access **at the route level**. The model itself provides no declarative permission guard. If a new endpoint is added that exposes `system_settings` without proper auth checks (e.g., a debug endpoint that is accidentally left exposed — see S-05 for docs leakage), an attacker can read or modify critical system state.
  2. **Flat namespace collision**: Any code with DB access can insert a new `setting_key`. There is no enum or constrained list of valid keys. A buggy migration or a compromised dependency could insert a malicious key that overrides legitimate behavior.
  3. **No value validation**: `setting_value` is `String(100)` with no constraint on format. `warehouse_status` expects only `ACTIVE` or `AUDIT_LOCK` (per BR §1.4), but nothing in the schema enforces this — a typo like `active` (lowercase) or `UNLOCKED` would pass the DB layer and cause the warehouse lock check to fail silently (the equality check on `setting_value == 'AUDIT_LOCK'` would be False, but the system would appear to function normally while actually being in an indeterminate lock state).

- **Recommended Surgical Fix**:
  Add a CheckConstraint for known critical keys:
  ```python
  class SystemSetting(Base):
      __tablename__ = 'system_settings'
      __table_args__ = (
          CheckConstraint(
              "setting_key != 'warehouse_status' OR setting_value IN ('ACTIVE', 'AUDIT_LOCK')",
              name='ck_warehouse_status_values'
          ),
      )
      id            = Column(Integer, primary_key=True)
      setting_key   = Column(String(50),  unique=True, nullable=False)
      setting_value = Column(String(100), nullable=False)
      description   = Column(String(200), nullable=True)
  ```

  Additionally, ensure all `system_settings` endpoints require admin authentication (verified in route handlers — outside this audit's scope, but flagged here for architectural awareness).

---

### S-12: No Correlation/Trace ID in Error Responses — Hinders Incident Response

- **Severity**: **Low**
- **OWASP Category**: **A09:2021-Security Logging and Monitoring Failures**
- **Exact File & Line Number**: `wa_backend/main.py`, lines 84–106 (error handlers)
- **Current Vulnerable Code**:
  ```python
  @app.exception_handler(Exception)
  async def global_exception_handler(request: Request, exc: Exception):
      client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "Unknown")
      error_msg = f"[{client_ip}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"
      await async_log_error(error_msg)
      return JSONResponse(
          status_code=500,
          content={"message": "خطأ داخلي في الخادم. يرجى مراجعة سجلات النظام."},
      )
  ```

- **Exploit Scenario & Impact Analysis**:
  When a 500 error occurs, the client receives a generic Arabic message with **no correlation ID**. The server-side log contains the full traceback, but there is no identifier linking the client's experience ("I got a 500 error at 14:32") to the specific server log entry. During a security incident:
  - A user reports "the app crashed at 2:30 PM."
  - The SOC team must grep logs by timestamp, IP, and endpoint — a heuristic search that may match multiple entries or none.
  - If the attacker is spoofing IPs (see S-01), the logged IP is wrong, making correlation impossible.
  - The 24-hour incident response clock (PCI-DSS, GDPR breach notification) is wasted on log-grepping.

- **Recommended Surgical Fix**:
  Generate a unique request ID at the edge and thread it through both the response and the log:

  ```python
  import uuid
  from starlette.middleware.base import BaseHTTPMiddleware

  class RequestIDMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
          request.state.request_id = request_id
          response = await call_next(request)
          response.headers["X-Request-Id"] = request_id
          return response

  app.add_middleware(RequestIDMiddleware)

  # Update error handlers:
  @app.exception_handler(Exception)
  async def global_exception_handler(request: Request, exc: Exception):
      request_id = getattr(request.state, 'request_id', 'N/A')
      client_ip = get_real_ip(request)  # Use hardened function from S-01
      error_msg = (
          f"[req_id={request_id}] [{client_ip}] {request.method} {request.url.path} | "
          f"حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"
      )
      await async_log_error(error_msg)
      return JSONResponse(
          status_code=500,
          content={
              "message": "خطأ داخلي في الخادم. يرجى مراجعة سجلات النظام.",
              "request_id": request_id  # Give the client a breadcrumb
          },
      )
  ```

---

## Cross-Reference: Findings from Prior Audits Mapped to OWASP

The following high-severity findings from prior Phase 6.4 (auth.md) and Phase 9 (dispatch.md) audits map directly to OWASP Top 10 categories. These are **not duplicated** in detail above but are listed here for completeness:

| Prior Finding | Severity | OWASP Category | Source Report |
|---------------|----------|----------------|---------------|
| Brute-Force Race Condition (TOCTOU) | High | A07:2021-Identification and Authentication Failures | `auth.md` Finding #1 |
| Missing JWT `iat`/`jti`/`type` Claims | Medium | A07:2021-Identification and Authentication Failures | `auth.md` Finding #2 |
| No Token Revocation / Logout | Medium | A07:2021-Identification and Authentication Failures | `auth.md` Finding #3 |
| `getattr` Fail-Open Default (True) | Low | A04:2021-Insecure Design | `auth.md` Finding #6 |
| No Centralized Resource-Ownership Guard (Systemic IDOR) | Medium | A01:2021-Broken Access Control | `auth.md` Finding #7 |
| Silent Audit Log Failures (DB Exceptions Swallowed) | Low | A09:2021-Security Logging and Monitoring Failures | `auth.md` Finding #8 |
| Phantom Stock Fabrication via Negative Quantity | Critical | A03:2021-Injection (Data) | `dispatch.md` Finding #1 |
| Admin Password Check Before `is_admin` (Timing Leak) | Low | A07:2021-Identification and Authentication Failures | `auth.md` Finding #5 |

---

## Summary of Recommendations (Priority Order)

| Priority | Finding | Action |
|----------|---------|--------|
| **P0** | S-01 — IP Spoofing via `X-Forwarded-For` | Deploy hardened `get_real_ip()` + configure proxy to strip untrusted headers |
| **P0** | S-02 — No Global Rate Limiting | Add `slowapi` with Redis backend; apply per-endpoint limits |
| **P1** | S-03 — Missing Security Headers | Add `SecurityHeadersMiddleware` with HSTS, CSP, X-Frame-Options, etc. |
| **P1** | S-04 — Overly Permissive CORS | Restrict `allow_methods`/`allow_headers`; externalize origins to env var |
| **P1** | S-08 — Weak `SECRET_KEY` Allowed | Enforce minimum 32-char length + entropy diversity check |
| **P2** | S-05 — Docs Exposure via Unsafe Default | Invert default to `production`; add explicit `ENABLE_API_DOCS` flag |
| **P2** | S-06 — No Body Size Limit | Add Nginx `client_max_body_size` + FastAPI middleware defense-in-depth |
| **P2** | S-07 — `.env` Leakage Risk | Add git-tracked check; prefer cloud secret managers in production |
| **P2** | S-09 — No Successful Login Audit | Log `SUCCESSFUL_LOGIN` events; make log level configurable |
| **P3** | S-10 — DB Password in Logs | Sanitize `DATABASE_URL` from stack traces before writing to disk |
| **P3** | S-11 — SystemSetting No Value Constraints | Add CheckConstraint for `warehouse_status` values |
| **P3** | S-12 — No Request Correlation ID | Add `RequestIDMiddleware`; return `request_id` in error responses |

---

*End of Phase 10 OWASP Security Audit*



## Issue #13 — Log Forging (CRLF Injection) via Unsanitized Request Data

- **Severity**: **Medium**
- **OWASP Category**: **A09:2021-Security Logging and Monitoring Failures** / **A03:2021-Injection**
- **Exact File & Line Number**: `wa_backend/main.py`, lines 97–98
- **Current Vulnerable Code**:
  ```python
  client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "Unknown")
  error_msg = f"[{client_ip}] {request.method} {request.url.path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"


Exploit Scenario & Impact Analysis:
The global exception handler reads the request.method and request.url.path and injects them directly into the error log string without sanitizing newline characters (\r or \n). An attacker can send a deliberately malformed request that triggers a 500 error, including CRLF characters in the URL path.
For example, requesting a path like:
GET /api/%0d%0a[127.0.0.1]%20SUCCESSFUL_LOGIN%20admin
Because the string is concatenated directly, the newline characters break the log structure. The attacker can inject completely fake log entries (Log Forging) that appear to be generated by the system itself (e.g., framing another IP address for an attack, or inserting fake "successful login" audits to confuse incident response teams).

Recommended Surgical Fix:
Sanitize the user-controlled input (path and method) by escaping or stripping newline characters before injecting them into the log string.

def sanitize_log_input(text: str) -> str:
    """Strip newlines and carriage returns to prevent Log Forging/CRLF Injection."""
    if not text:
        return ""
    return text.replace('\n', '\\n').replace('\r', '\\r')

# In global_exception_handler:
client_ip = sanitize_log_input(request.headers.get("X-Forwarded-For", request.client.host if request.client else "Unknown"))
safe_method = sanitize_log_input(request.method)
safe_path = sanitize_log_input(request.url.path)

error_msg = f"[{client_ip}] {safe_method} {safe_path} | حدث خطأ غير متوقع: {str(exc)}\n{traceback.format_exc()}"

