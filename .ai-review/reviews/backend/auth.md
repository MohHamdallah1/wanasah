# Backend Security Audit Report — Authentication & Authorization

**Audit Phase**: Phase 6.4 — Auth & Dependencies  
**Files Audited**: `wa_backend/api/auth.py`, `wa_backend/api/dependencies.py`  
**Supporting Reference**: `.ai-review/04_BUSINESS_RULES.md`  
**Audit Date**: 2026-07-24  
**Severity Scale**: Critical > High > Medium > Low  

---

## Executive Summary

The authentication module demonstrates strong security awareness with several deliberate defenses: bcrypt password hashing, timing-attack-resistant dummy-hash comparison, `asyncio.to_thread` for non-blocking bcrypt, IP-based brute-force detection, and database-level `is_active` re-verification on every authenticated request. However, the brute-force protection suffers from a **race condition** due to lack of atomicity between the check and the log write, the JWT implementation is missing critical claims (`iat`, `jti`), and there is **no token revocation mechanism** — a deactivated driver can continue using an already-issued token for up to 24 hours without re-authentication. The dependencies module correctly re-verifies `is_admin` from the database rather than trusting the JWT payload, but leaves resource-ownership enforcement entirely to individual route handlers with no centralized guard, creating a systemic IDOR risk surface across the API.

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 1 |
| Medium   | 4 |
| Low      | 4 |

---

## Detailed Findings

---

### Finding 1: Race Condition in Brute-Force Protection (TOCTOU)

- **Severity**: **High**
- **Flaw Category**: Brute-Force Bypass / Race Condition (TOCTOU)
- **Exact File & Line Number**: `wa_backend/api/auth.py`, lines 33–48 (`check_brute_force`) and lines 66–92 (`driver_login` flow)

- **Current Flawed Code**:
  ```python
  # Line 33-48
  async def check_brute_force(ip: str, db: AsyncSession):
      limit_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)
      stmt_count = select(func.count()).select_from(SystemAuditLog).where(
          SystemAuditLog.action_type == 'FAILED_LOGIN',
          SystemAuditLog.target_id == ip,
          SystemAuditLog.timestamp >= limit_time
      )
      failed_count = (await db.execute(stmt_count)).scalar() or 0
      
      if failed_count >= 5:
          raise HTTPException(status_code=429, detail="...")

  # Line 66-92 (driver_login)
  @router.post("/driver/login", response_model=LoginResponse)
  async def driver_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
      ip = get_real_ip(request)
      await check_brute_force(ip, db)        # Step A: read count
      # ... credential check ...
      if not driver or not password_match:
          await log_failed_attempt(ip, db)    # Step B: write new failure (commits)
          raise HTTPException(status_code=401, ...)
  ```

- **Impact Analysis**:
  The `check_brute_force` function (Step A) reads the current failure count, and `log_failed_attempt` (Step B) writes a new failure record — but these two operations are **not wrapped in a transaction or locked atomically**. In a concurrent attack scenario, 20 requests arriving within the same ~50ms window will all see `failed_count = 0` (before any of them have committed their own failure log), and all 20 will proceed to the bcrypt check. While bcrypt itself is computationally expensive and provides a natural throttle, the attacker can:
  1. Distribute attempts across many IPs (bypassing IP-based counting entirely — no global rate limit exists).
  2. Exploit the race window to achieve an effective rate higher than 5 attempts per 15 minutes per IP.
  3. Use the `/driver/login` and `/login` endpoints independently (they share the same `check_brute_force` but an attacker can alternate between them to double the effective attempt rate before hitting the threshold on either, since `log_failed_attempt` writes the same `FAILED_LOGIN` action_type for both).

  The absence of a **global in-memory rate limiter** (e.g., Redis-backed sliding window or token bucket) means this protection relies entirely on database I/O under concurrent load, which is inherently race-prone.

- **Recommended Surgical Fix**:
  Replace the two-step check-then-log pattern with an **atomic insert-then-count** approach using a database-level lock or a single upsert+count operation:

  ```python
  # Replace check_brute_force and log_failed_attempt with a single atomic function
  from sqlalchemy import insert, text

  async def record_and_check_brute_force(ip: str, db: AsyncSession) -> None:
      """Atomically insert a failed attempt AND check threshold in one round-trip."""
      limit_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)

      # 1. Insert the failure record FIRST (atomic write)
      try:
          audit = SystemAuditLog(
              admin_id=None,
              target_id=ip,
              action_type='FAILED_LOGIN',
              old_value='Brute Force Attempt',
              new_value='Failed',
              timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
          )
          db.add(audit)
          await db.flush()  # flush but don't commit yet — keep inside request tx
      except Exception:
          await db.rollback()
          raise HTTPException(status_code=500, detail="Internal error")

      # 2. Now count WITHIN THE SAME TRANSACTION (includes the row we just flushed)
      stmt_count = select(func.count()).select_from(SystemAuditLog).where(
          SystemAuditLog.action_type == 'FAILED_LOGIN',
          SystemAuditLog.target_id == ip,
          SystemAuditLog.timestamp >= limit_time
      )
      failed_count = (await db.execute(stmt_count)).scalar() or 0

      if failed_count > 5:  # > 5 because the current attempt is already counted
          await db.rollback()
          raise HTTPException(status_code=429, detail="تم حظر عنوان IP مؤقتاً بسبب محاولات اختراق متكررة.")

      # 3. Commit only if under threshold
      await db.commit()
  ```

  Then update both login endpoints to call `record_and_check_brute_force` in the failure branch instead of the separate `check_brute_force` + `log_failed_attempt`:

  ```python
  # In driver_login (line 81-83):
  if not driver or not password_match:
      await record_and_check_brute_force(ip, db)
      raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")
  ```

  **Additionally**, add a lightweight in-memory rate limiter (e.g., `slowapi` or a Redis-backed sliding window) **before** any database interaction to absorb volumetric attacks without touching the database at all:

  ```python
  # At module level (before route definitions)
  from slowapi import Limiter
  from slowapi.util import get_remote_address

  limiter = Limiter(key_func=get_real_ip)

  @router.post("/driver/login", response_model=LoginResponse)
  @limiter.limit("10/minute")  # Hard cap before any DB work
  async def driver_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
      ...
  ```

---

### Finding 2: JWT Missing Critical Claims — `iat`, `jti`, and Token Type

- **Severity**: **Medium**
- **Flaw Category**: JWT Token Misconfiguration / Missing Security Claims
- **Exact File & Line Number**: `wa_backend/api/auth.py`, lines 27–31 (`create_access_token`)

- **Current Flawed Code**:
  ```python
  def create_access_token(data: dict):
      to_encode = data.copy()
      expire = datetime.now(timezone.utc) + timedelta(seconds=86400)
      to_encode.update({"exp": expire})
      return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")
  ```

- **Impact Analysis**:
  1. **No `iat` (Issued At) claim**: Without `iat`, the token's age cannot be verified independently of `exp`. If clock skew exists between the issuing server and a verifying service, the `exp` check alone may be unreliable. More critically, `iat` enables token-age-based policies (e.g., "force re-login for tokens older than 1 hour").
  2. **No `jti` (JWT ID) claim**: Without a unique token identifier, individual tokens cannot be revoked. If a token is compromised, the only mitigation is rotating the global `SECRET_KEY`, which invalidates **all** users' sessions simultaneously — an operationally unacceptable response to a single compromised token.
  3. **No `type` claim**: The token does not declare itself as an `"access"` token. If refresh tokens, email-verification tokens, or password-reset tokens are ever introduced (all signed with the same `SECRET_KEY`), an attacker could reuse a token issued for one purpose to authenticate API requests, since `get_current_driver` in `dependencies.py` does not verify token type.

- **Recommended Surgical Fix**:
  ```python
  import uuid

  def create_access_token(data: dict):
      to_encode = data.copy()
      now = datetime.now(timezone.utc)
      expire = now + timedelta(seconds=86400)
      to_encode.update({
          "iat": now,
          "exp": expire,
          "jti": str(uuid.uuid4()),
          "type": "access"
      })
      return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")
  ```

  Update `dependencies.py` to validate these claims:

  ```python
  # In get_current_driver, after line 15 (jwt.decode):
  payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"],
                       options={"require": ["exp", "iat", "jti", "type", "sub"]})
  if payload.get("type") != "access":
      raise HTTPException(status_code=401, detail="Invalid token type")
  ```

---

### Finding 3: No Token Revocation / Logout Mechanism

- **Severity**: **Medium**
- **Flaw Category**: JWT Lifecycle Management / Missing Revocation
- **Exact File & Line Number**: `wa_backend/api/auth.py`, lines 27–31 (`create_access_token`) and `wa_backend/api/dependencies.py`, lines 11–35 (`get_current_driver`)

- **Current Flawed Code**:
  ```python
  # auth.py line 27-31
  def create_access_token(data: dict):
      to_encode = data.copy()
      expire = datetime.now(timezone.utc) + timedelta(seconds=86400)
      to_encode.update({"exp": expire})
      return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")

  # dependencies.py line 11-35
  async def get_current_driver(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
      token = credentials.credentials
      payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
      # ... only checks is_active via DB query — no token blacklist check
  ```

- **Impact Analysis**:
  Once a JWT is issued, it remains valid for 24 hours with no server-side mechanism to revoke it before natural expiry. The `is_active` check in `get_current_driver` (line 32 of `dependencies.py`) provides a **delayed** kill-switch: if a driver's account is deactivated, subsequent requests are rejected. However:
  1. An attacker who steals a valid token can use it until the account is manually deactivated — there is no "logout" that invalidates a specific token.
  2. A driver who logs out on one device cannot invalidate tokens issued to other devices.
  3. An admin cannot force-terminate a specific session — they must deactivate the entire driver account.
  4. If `is_active` is toggled off and then back on, all previously-issued tokens become valid again (since there's no blacklist), creating a window for token reuse.

  Combined with Finding #2 (no `jti`), there is no infrastructure to support token-specific revocation even if the will existed.

- **Recommended Surgical Fix**:
  Implement a token blacklist using a Redis set or a database table (`TokenBlacklist`) with TTL-based automatic cleanup. Add a middleware or check in `get_current_driver`:

  ```python
  # In dependencies.py — add token blacklist check before DB query
  async def get_current_driver(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
      token = credentials.credentials
      try:
          payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
      except jwt.ExpiredSignatureError:
          raise HTTPException(status_code=401, detail="Token is invalid or expired")
      except jwt.PyJWTError:
          raise HTTPException(status_code=401, detail="Token processing error")

      # +++ NEW: Check token blacklist +++
      jti = payload.get("jti")
      if jti:
          stmt = select(TokenBlacklist).where(TokenBlacklist.jti == jti)
          blacklisted = (await db.execute(stmt)).scalar_one_or_none()
          if blacklisted:
              raise HTTPException(status_code=401, detail="Token has been revoked")

      # ... rest of existing logic ...
  ```

  Add a logout endpoint:

  ```python
  # In auth.py
  @router.post("/logout")
  async def logout(
      credentials: HTTPAuthorizationCredentials = Depends(security),
      db: AsyncSession = Depends(get_db)
  ):
      token = credentials.credentials
      try:
          payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"],
                               options={"verify_exp": False})  # allow expired tokens to be blacklisted
      except jwt.PyJWTError:
          raise HTTPException(status_code=401, detail="Invalid token")

      jti = payload.get("jti")
      exp = payload.get("exp")
      if jti and exp:
          blacklist_entry = TokenBlacklist(
              jti=jti,
              expires_at=datetime.fromtimestamp(exp, tz=timezone.utc)
          )
          db.add(blacklist_entry)
          await db.commit()

      return {"message": "Logged out successfully"}
  ```

---

### Finding 4: In-Memory Dummy Password Hash Computed at Module Import

- **Severity**: **Low**
- **Flaw Category**: Startup Performance / Predictable Dummy Hash
- **Exact File & Line Number**: `wa_backend/api/auth.py`, line 18

- **Current Flawed Code**:
  ```python
  DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"dummy_password", bcrypt.gensalt()).decode('utf-8')
  ```

- **Impact Analysis**:
  The dummy hash is computed once at module import time. While this is intentional for performance (avoiding re-computation on every failed login), two minor issues exist:
  1. **Startup delay**: `bcrypt.gensalt()` and `bcrypt.hashpw()` are intentionally slow (~200-300ms on modern hardware). This adds a fixed cost at application startup. If the application is deployed in a serverless/containerized environment where cold starts are frequent, this contributes to latency.
  2. **Predictable salt**: The salt is generated once at process start and persists for the lifetime of the process. While this doesn't weaken the timing-attack defense (the hash is never compared against a real password), it means an attacker with access to process memory could identify the dummy hash value and use it to fingerprint the application version. This is extremely low-risk.

- **Recommended Surgical Fix**:
  Pre-compute the hash at build/deploy time and load it from an environment variable, or use a fixed known bcrypt hash with a known cost factor:

  ```python
  # Replace line 18 with:
  # Pre-computed bcrypt hash of "dummy_password" with cost factor 12
  # Generated once via: bcrypt.hashpw(b"dummy_password", bcrypt.gensalt(rounds=12))
  DUMMY_PASSWORD_HASH = os.environ.get(
      "DUMMY_PASSWORD_HASH",
      "$2b$12$LJ3m4ys3GZfnYMz8kVsKaOmGJpFrV7Z0vGQo1xUBSJxvPQrDfZhXO"  # fallback for dev
  )
  ```

  If environment-variable injection is not desired, at minimum add a comment documenting the expected startup cost and move the computation inside a lazy initializer:

  ```python
  _DUMMY_HASH_CACHE: str | None = None

  def get_dummy_hash() -> str:
      global _DUMMY_HASH_CACHE
      if _DUMMY_HASH_CACHE is None:
          _DUMMY_HASH_CACHE = bcrypt.hashpw(b"dummy_password", bcrypt.gensalt()).decode('utf-8')
      return _DUMMY_HASH_CACHE
  ```

---

### Finding 5: Admin Login Endpoint Verifies Password Before Checking `is_admin` Flag

- **Severity**: **Low**
- **Flaw Category**: Information Leakage via Timing / Wasted Computation
- **Exact File & Line Number**: `wa_backend/api/auth.py`, lines 94–115 (`admin_login`)

- **Current Flawed Code**:
  ```python
  @router.post("/login", response_model=LoginResponse)
  async def admin_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
      # ... brute force check ...
      stmt = select(Driver).filter_by(username=payload.username, is_active=True)
      admin = (await db.execute(stmt)).scalar_one_or_none()

      # BCRYPT CHECK HAPPENS HERE — before is_admin verification
      hash_to_check = admin.password_hash if admin else DUMMY_PASSWORD_HASH
      pwd_bytes = payload.password.encode('utf-8')
      hash_bytes = hash_to_check.encode('utf-8')
      password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

      if not admin or not password_match:
          await log_failed_attempt(ip, db)
          raise HTTPException(status_code=401, detail="...")

      # is_admin CHECK HAPPENS HERE — AFTER bcrypt
      if not admin.is_admin:
          await log_failed_attempt(ip, db)
          raise HTTPException(status_code=403, detail="...")
  ```

- **Impact Analysis**:
  A valid non-admin driver submitting correct credentials to the `/login` (admin) endpoint will:
  1. Pass the bcrypt check using their **real** password hash (expensive computation, ~200-300ms).
  2. Then be rejected at line 113 with a 403 because `is_admin = False`.

  This wastes server CPU on bcrypt for requests that can never succeed (non-admin users at the admin endpoint). More subtly, the timing difference between:
  - "User doesn't exist" → dummy hash checked → 401
  - "User exists + wrong password" → real hash checked → 401
  - "User exists + correct password + not admin" → real hash checked → 403

  leaks information: an attacker can measure response times to determine whether a username exists and whether they guessed the correct password (because a correct-password response will take longer due to the extra DB commit in `log_failed_attempt` + the `create_access_token` call that follows in the success path, but the 403 path also does a `log_failed_attempt` commit). While the timing-attack surface is small due to network jitter, it is a known anti-pattern to perform expensive credential verification for principals that are categorically ineligible.

- **Recommended Surgical Fix**:
  Check `is_admin` eligibility **before** the bcrypt comparison. Use the dummy hash for non-admin users to maintain timing-attack resistance:

  ```python
  @router.post("/login", response_model=LoginResponse)
  async def admin_login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)):
      ip = get_real_ip(request)
      await check_brute_force(ip, db)

      stmt = select(Driver).filter_by(username=payload.username, is_active=True)
      user = (await db.execute(stmt)).scalar_one_or_none()

      # +++ FIX: Check is_admin eligibility BEFORE bcrypt +++
      if user is None or not user.is_admin:
          # Non-existent user OR non-admin user: use dummy hash for timing safety
          hash_to_check = DUMMY_PASSWORD_HASH
      else:
          hash_to_check = user.password_hash

      pwd_bytes = payload.password.encode('utf-8')
      hash_bytes = hash_to_check.encode('utf-8')
      password_match = await asyncio.to_thread(bcrypt.checkpw, pwd_bytes, hash_bytes)

      if user is None or not user.is_admin or not password_match:
          await log_failed_attempt(ip, db)
          raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")

      # At this point, user.is_admin is guaranteed True
      token = create_access_token({"sub": str(user.id), "is_admin": user.is_admin, "username": user.username})
      return {
          "message": "Admin Login Successful!",
          "token": token,
          "driver_id": user.id,
          "driver_name": user.full_name,
          "is_admin": user.is_admin
      }
  ```

  This eliminates both the wasted bcrypt computation for non-admin users AND the distinguishability of the 403 vs 401 response for correct-credential non-admin attempts (both now return 401 uniformly).

---

### Finding 6: `get_current_driver` Uses `getattr` with Unsafe Default `True`

- **Severity**: **Low**
- **Flaw Category**: Defensive Coding — Fail-Open Default
- **Exact File & Line Number**: `wa_backend/api/dependencies.py`, line 32

- **Current Flawed Code**:
  ```python
  driver = await db.get(Driver, driver_id_int)
  if not driver or not getattr(driver, 'is_active', True):
      raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم إيقاف حسابك ...")
  ```

- **Impact Analysis**:
  The `getattr(driver, 'is_active', True)` expression defaults to `True` if the `is_active` attribute is missing from the model. This is a **fail-open** default: if a future code change accidentally removes or renames the `is_active` column, the dependency will treat **all** drivers as active rather than rejecting the request. The security principle of "fail-closed" dictates that unknown states should be treated as unauthorized.

  Given that `Driver.is_active` is a well-established column (line 90 of `models.py`), this is unlikely to occur accidentally, but the defensive posture is inverted.

- **Recommended Surgical Fix**:
  ```python
  driver = await db.get(Driver, driver_id_int)
  if not driver or not getattr(driver, 'is_active', False):  # Default to False = fail-closed
      raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم إيقاف حسابك أو طردك من النظام. التوكن ملغي.")
  ```

  Better yet, rely on explicit attribute access (which will raise `AttributeError` if the column is missing, making the problem immediately visible):

  ```python
  driver = await db.get(Driver, driver_id_int)
  if not driver or not driver.is_active:
      raise HTTPException(status_code=403, detail="مرفوض أمنياً: تم إيقاف حسابك أو طردك من النظام. التوكن ملغي.")
  ```

---

### Finding 7: No Centralized Resource-Ownership Guard (Systemic IDOR Risk)

- **Severity**: **Medium**
- **Flaw Category**: IDOR / Missing Authorization Layer
- **Exact File & Line Number**: `wa_backend/api/dependencies.py`, lines 11–35 (`get_current_driver`)

- **Current Flawed Code**:
  ```python
  async def get_current_driver(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
      # ... JWT decode and DB verification ...
      driver = await db.get(Driver, driver_id_int)
      if not driver or not getattr(driver, 'is_active', True):
          raise HTTPException(status_code=403, ...)
      return driver
  ```

- **Impact Analysis**:
  `get_current_driver` authenticates the caller but performs **no authorization** beyond verifying the account is active. It returns the `Driver` object, and it is each route handler's responsibility to verify that the authenticated driver is accessing their own resources. For example, in `wa_backend/api/driver.py`, routes like:

  ```python
  @router.put("/driver/{driver_id}/sessions/break")
  async def toggle_break(driver_id: int, current_driver: Driver = Depends(get_current_driver), ...):
  ```

  must manually check that `current_driver.id == driver_id`. If any route handler **omits** this check, an authenticated driver can access or modify another driver's sessions, visits, or inventory. This is a **systemic architectural risk** — the dependency does not provide a pattern or helper to enforce ownership, leaving the entire API surface vulnerable to IDOR if any single route handler neglects the check.

  The `get_current_admin` dependency (line 38–42) correctly allows admins to act on any resource, but for driver-scoped endpoints, there is no equivalent `get_current_driver_for_resource(driver_id)` that validates ownership inline.

- **Recommended Surgical Fix**:
  Add a parameterized dependency that validates ownership:

  ```python
  # In dependencies.py
  async def get_current_driver_owned(
      driver_id: int,  # from path parameter
      current_driver: Driver = Depends(get_current_driver)
  ) -> Driver:
      """Authenticate AND authorize: ensures the driver is accessing their own resource."""
      if current_driver.is_admin:
          # Admins can act on behalf of any driver — fetch the target driver
          # (requires db session — this is a simplified illustration)
          return current_driver  # or fetch the target driver if needed
      if current_driver.id != driver_id:
          raise HTTPException(
              status_code=403,
              detail="مرفوض أمنياً: لا يمكنك الوصول إلى موارد مندوب آخر."
          )
      return current_driver
  ```

  Then refactor driver-scoped routes to use this dependency:

  ```python
  # Before (vulnerable to IDOR if check is forgotten):
  @router.put("/driver/{driver_id}/sessions/break")
  async def toggle_break(driver_id: int, current_driver: Driver = Depends(get_current_driver), ...):

  # After (ownership enforced by dependency):
  @router.put("/driver/{driver_id}/sessions/break")
  async def toggle_break(driver_id: int, current_driver: Driver = Depends(get_current_driver_owned), ...):
  ```

  **Alternatively**, if refactoring all routes is impractical, add a reusable helper and document that every driver-scoped route MUST call it:

  ```python
  def enforce_ownership(current_driver: Driver, resource_driver_id: int) -> None:
      if not current_driver.is_admin and current_driver.id != resource_driver_id:
          raise HTTPException(status_code=403, detail="مرفوض أمنياً: لا يمكنك الوصول إلى موارد مندوب آخر.")
  ```

---

### Finding 8: `log_failed_attempt` Silently Swallows Database Exceptions

- **Severity**: **Low**
- **Flaw Category**: Audit Trail Integrity / Silent Failure
- **Exact File & Line Number**: `wa_backend/api/auth.py`, lines 50–64 (`log_failed_attempt`)

- **Current Flawed Code**:
  ```python
  async def log_failed_attempt(ip: str, db: AsyncSession):
      try:
          audit = SystemAuditLog(...)
          db.add(audit)
          await db.commit()
      except Exception:
          await db.rollback()
  ```

- **Impact Analysis**:
  If the database is temporarily unavailable (connection pool exhausted, network blip, deadlock), the failed attempt is silently not logged. An attacker who can trigger database errors (e.g., by exhausting connection pools via parallel requests) could suppress audit logging of their own brute-force attempts. While the brute-force check in `check_brute_force` would also fail (raising an unhandled exception and potentially crashing the request), the silent exception swallowing means:
  1. There is no alert or log output when audit logging fails — operations teams have no visibility into audit trail gaps.
  2. If only the `commit()` fails but the `check_brute_force` query succeeds (e.g., read-only replica available but write master down), the brute-force count never increments, and the attacker can continue indefinitely.

- **Recommended Surgical Fix**:
  At minimum, log the exception to stderr or a logging framework:

  ```python
  import logging
  logger = logging.getLogger(__name__)

  async def log_failed_attempt(ip: str, db: AsyncSession):
      try:
          audit = SystemAuditLog(
              admin_id=None,
              target_id=ip,
              action_type='FAILED_LOGIN',
              old_value='Brute Force Attempt',
              new_value='Failed'
          )
          db.add(audit)
          await db.commit()
      except Exception as e:
          await db.rollback()
          logger.error(f"CRITICAL: Failed to log brute-force attempt for IP {ip}: {e}", exc_info=True)
  ```

  Better yet, write to a separate append-only audit log file as a fallback when the database write fails:

  ```python
  except Exception as e:
      await db.rollback()
      logger.error(f"CRITICAL: Failed to log brute-force attempt for IP {ip}: {e}", exc_info=True)
      # Fallback: append to a flat audit file so the attempt is never completely lost
      try:
          with open("/var/log/wanasah/auth_fallback.log", "a") as f:
              f.write(f"{datetime.now(timezone.utc).isoformat()} | FAILED_LOGIN | {ip} | DB_WRITE_FAILED\n")
      except Exception:
          pass  # absolute last resort — stderr already logged above
  ```

---

### Finding 9: Hardcoded Token Expiry Duration

- **Severity**: **Low**
- **Flaw Category**: Configuration Hardcoding
- **Exact File & Line Number**: `wa_backend/api/auth.py`, line 29

- **Current Flawed Code**:
  ```python
  expire = datetime.now(timezone.utc) + timedelta(seconds=86400) # 24 ساعة كما في منطقك
  ```

- **Impact Analysis**:
  The 24-hour token lifetime is hardcoded. In production, different deployments may require different expiry policies (e.g., 8 hours for a single-shift operation, 1 hour for PCI-DSS compliance, or 72 hours for remote field operations with intermittent connectivity). Hardcoding forces code changes and redeployment for what should be a configuration toggle.

- **Recommended Surgical Fix**:
  ```python
  TOKEN_EXPIRY_SECONDS = int(os.environ.get("JWT_EXPIRY_SECONDS", 86400))

  def create_access_token(data: dict):
      to_encode = data.copy()
      now = datetime.now(timezone.utc)
      expire = now + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
      to_encode.update({
          "iat": now,
          "exp": expire,
          "jti": str(uuid.uuid4()),
          "type": "access"
      })
      return jwt.encode(to_encode, Config.SECRET_KEY, algorithm="HS256")
  ```

---

## Cross-Reference: Business Rules Compliance

| Business Rule (from `04_BUSINESS_RULES.md`) | Auth Module Compliance |
|---------------------------------------------|----------------------|
| §2.4 — Admin forbidden from self-authorizing own session | Not enforced in auth/dependencies layer; enforced in `authorize_session` route — **in scope for route audit, not auth module**. |
| §6.3 — 401/403 halts sync loop (token expiry handled gracefully by mobile) | `dependencies.py` correctly returns 401 for expired/invalid tokens and 403 for deactivated accounts — mobile sync logic in `syncUp()` will halt on these as specified. |
| §4.2 — `can_allow_debt` is a per-driver permission | Not checked in auth/dependencies — this is a business-logic permission checked in the sales/visit route handlers, **not an auth concern**. |

**Conclusion**: The auth module does not violate any business rules documented in `04_BUSINESS_RULES.md`. The business rules that touch authentication (session authorization, debt permissions) are enforced in the route handlers, not in the auth/dependencies layer — this is the correct separation of concerns.

---

## Summary of Recommended Actions (Priority Order)

| Priority | Finding | Action |
|----------|---------|--------|
| **P0** | #1 — Race condition in brute-force protection | Implement atomic insert-then-count + add in-memory rate limiter |
| **P1** | #2 — Missing JWT claims (`iat`, `jti`, `type`) | Add claims to `create_access_token` and validate in `get_current_driver` |
| **P1** | #3 — No token revocation mechanism | Implement JWT blacklist + logout endpoint |
| **P1** | #7 — No centralized resource-ownership guard | Add `get_current_driver_owned` dependency or `enforce_ownership` helper |
| **P2** | #5 — Admin login verifies password before `is_admin` | Reorder to check `is_admin` eligibility first |
| **P2** | #8 — Silent audit log failures | Add error logging + file-based fallback |
| **P3** | #4 — Dummy hash computed at import | Move to lazy initialization or env-var configuration |
| **P3** | #6 — `getattr` fail-open default | Change default to `False` or use direct attribute access |
| **P3** | #9 — Hardcoded token expiry | Externalize to environment variable |

---

*End of Audit Report — Phase 6.4*