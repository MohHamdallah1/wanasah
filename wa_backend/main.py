import os
import re
import uuid
import logging
import asyncio
import traceback
import ipaddress
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import jwt
from fastapi import FastAPI, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Step 5.2: Sentry error tracking
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

# S-02: Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# +++ استيراد المكونات الداخلية للنظام +++
from api import auth, driver, dispatch, warehouse
from config import Config
from database import engine, get_db
from ws_manager import dispatch_manager


# ═══ S-01: Hardened IP extraction (trusted proxy CIDRs) ═══
TRUSTED_PROXY_CIDRS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]

def get_real_ip(request: Request) -> str:
    """Extract real client IP, trusting only known proxy IPs."""
    client_host = request.client.host if request.client else None
    if client_host:
        try:
            client_ip = ipaddress.ip_address(client_host)
            if not any(client_ip in cidr for cidr in TRUSTED_PROXY_CIDRS):
                return str(client_ip)
        except ValueError:
            pass
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

# ═══ S-10 / Issue #13: Log sanitization ═══
def sanitize_log_input(text: str) -> str:
    """Strip newlines and carriage returns to prevent Log Forging/CRLF Injection."""
    if not text:
        return ""
    return text.replace('\n', '\\n').replace('\r', '\\r')

def sanitize_error_message(msg: str) -> str:
    """Remove database credentials and other secrets from error messages before logging."""
    msg = re.sub(
        r'(postgresql\+asyncpg://)[^@]+:[^@]+(@)',
        r'\1***REDACTED***:***REDACTED***\2',
        msg
    )
    msg = re.sub(r'SECRET_KEY[\s=:]+[^\s]+', 'SECRET_KEY=***REDACTED***', msg)
    return msg

# إعداد ملف الأخطاء (نفس نظامك الاحترافي السابق)
logger = logging.getLogger("wanasah_logger")
logger.setLevel(logging.ERROR)
handler = RotatingFileHandler('error.log', maxBytes=1024 * 1024, backupCount=5, encoding='utf-8')
# +++ ISSUE-24: إزالة %(pathname)s:%(lineno)d المضللة لأن الـ Traceback يفي بالغرض ويكون أدق +++
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

async def async_log_error(exc_str: str):
    """تنفيذ الكتابة على القرص في مسار منفصل (Thread) لكي لا يتجمد الـ FastAPI"""
    await asyncio.to_thread(logger.error, exc_str)

from contextlib import asynccontextmanager
from database import engine
import os

# +++ ISSUE-26: الإغلاق النظيف لموارد قاعدة البيانات لمنع تسريب الاتصالات (Connection Leaks) +++
@asynccontextmanager
async def lifespan(app: FastAPI):
    # بدء تشغيل السيرفر
    yield
    # إغلاق السيرفر
    await engine.dispose()

# S-05: Default to safe (production), enable docs only via explicit opt-in
ENV = os.getenv("ENVIRONMENT", "production")
ENABLE_API_DOCS = os.getenv("ENABLE_API_DOCS", "false").lower() in ("true", "1", "yes")

# Step 5.2: Initialize Sentry (no-op if SENTRY_DSN is not set in environment)
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENV,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
    )

# إنشاء تطبيق فاست إيه بي آي
app = FastAPI(
    title="Wanasah API Core", 
    version="2.0.0",
    docs_url="/docs" if ENABLE_API_DOCS else None,
    redoc_url="/redoc" if ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_API_DOCS else None,
    lifespan=lifespan
)

# S-04: Restrictive CORS configuration
_CORS_RAW = os.getenv("CORS_ALLOWED_ORIGINS", "https://dashboard.wanasah.com,https://www.wanasah.com")
ALLOWED_ORIGINS = [origin.strip() for origin in _CORS_RAW.split(",") if origin.strip()]

if ENV == "development" or os.getenv("ENABLE_CORS_WILDCARD", "false").lower() in ("true", "1", "yes"):
    DEV_ORIGINS = [
        "http://localhost:8080", "http://127.0.0.1:8080",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000"
    ]
    for origin in DEV_ORIGINS:
        if origin not in ALLOWED_ORIGINS:
            ALLOWED_ORIGINS.append(origin)

if ENV == "production" and not ALLOWED_ORIGINS:
    raise ValueError("CORS_ALLOWED_ORIGINS must be set in production environment!")

# ملاحظة: تم إزالة إضافة CORSMiddleware من هنا لنقلها للأسفل في الخطوة القادمة

# S-02: Global rate limiter (200 req/min default per IP)
# +++ تم ربط الـ Limiter بـ get_real_ip المصفحة بدلاً من الدالة الافتراضية لمنع تزوير الـ IP +++
limiter = Limiter(key_func=get_real_ip, default_limits=["200/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    status_code=429,
    content={"message": "تم تجاوز الحد المسموح من الطلبات. يرجى المحاولة لاحقاً."},
))

# +++   إضافة نقطة التفتيش (Middleware) التي كانت مفقودة لتفعيل الحارس فعلياً +++
from slowapi.middleware import SlowAPIMiddleware
app.add_middleware(SlowAPIMiddleware)

# S-03: Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response: Response = await call_next(request)
        except RuntimeError as e:
            # +++ الدرع المعماري: التقاط هرب العميل (Client Disconnect) لمنع كراش الـ No response returned +++
            if str(e) == "No response returned." and await request.is_disconnected():
                return Response(status_code=499) # 499: Client Closed Request
            raise
            
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        # +++ الكي الجراحي: إضافة ws: و wss: لمنع الـ CSP من خنق اتصالات غرفة العمليات +++
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self ws: wss: http: https:'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# S-06: Body size limit middleware (10 MB)
MAX_BODY_SIZE = 10 * 1024 * 1024

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return JSONResponse(status_code=413, content={"message": "حجم الطلب يتجاوز الحد المسموح (10MB)."})
        
        try:
            return await call_next(request)
        except RuntimeError as e:
            # +++ الدرع المعماري: إخماد كراش الـ Starlette عند انقطاع الاتصال +++
            if str(e) == "No response returned." and await request.is_disconnected():
                return Response(status_code=499)
            raise

app.add_middleware(BodySizeLimitMiddleware)

# S-12: Request ID middleware for incident response correlation
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        except RuntimeError as e:
            # +++ الدرع المعماري الشامل: حماية نقطة تتبع الأخطاء من الانهيار +++
            if str(e) == "No response returned." and await request.is_disconnected():
                return Response(status_code=499)
            raise

app.add_middleware(RequestIDMiddleware)

# +++ الكي الجراحي: إضافة CORSMiddleware كآخر طبقة (Outermost Layer) لضمان إرسال هيدرات الـ CORS دائماً، حتى لو قام الـ Limiter أو Security برفض الطلب +++
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)

# +++ ISSUE-19: نقاط الفحص السحابية (Liveness & Readiness) للـ Docker/K8s +++
@app.get("/health", tags=["DevOps"])
async def health_check():
    """Liveness Probe: السيرفر يعمل"""
    return {"status": "alive"}

@app.get("/ready", tags=["DevOps"])
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness Probe: الاتصال بقاعدة البيانات سليم"""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database connection failed")

# +++ المترجم العسكري: تحويل detail الخاصة بـ FastAPI إلى message مع الحفاظ على الترويسات +++
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

# +++ المعالج الشامل للأخطاء (Global Exception Handler) +++
# S-01/S-10/Issue#13/S-12: Hardened IP extraction, log sanitization, request ID
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # S-01: Use hardened IP extraction
    client_ip = sanitize_log_input(get_real_ip(request))
    # Issue #13: Sanitize method and path against CRLF injection
    safe_method = sanitize_log_input(request.method)
    safe_path = sanitize_log_input(request.url.path)
    # S-12: Correlation ID for incident response
    request_id = getattr(request.state, 'request_id', 'N/A')
    
    # +++  للقائد: تنظيف رسالة الخطأ نفسها لمنع Log Forging +++
    safe_exc = sanitize_log_input(str(exc))
    raw_error = f"[req_id={request_id}] [{client_ip}] {safe_method} {safe_path} | حدث خطأ غير متوقع: {safe_exc}\n{traceback.format_exc()}"
    # S-10: Sanitize DB credentials from error messages
    error_msg = sanitize_error_message(raw_error)
    
    # +++ إرسال اللوج لـ Thread خارجي لمنع الاختناق (Blocking IO) وشلل الـ Event Loop +++
    await async_log_error(error_msg)
    
    return JSONResponse(
        status_code=500,
        content={
            "message": "خطأ داخلي في الخادم. يرجى مراجعة سجلات النظام.",
            "request_id": request_id
        },
    )

# +++ تفعيل الروترز لتتطابق مع طلبات React و Flutter الحقيقية +++
app.include_router(auth.router, tags=["Authentication"])
app.include_router(driver.router, tags=["Driver Operations"])
app.include_router(dispatch.router, tags=["Dispatch & Routing"])
app.include_router(warehouse.router, tags=["Warehouse & Inventory"])

# Step 5.7a: WebSocket endpoint for real-time dispatch dashboard updates
@app.websocket("/ws/dispatch")
async def websocket_dispatch_endpoint(websocket: WebSocket):
    # +++ الدرع الفولاذي: إجبار التحقق من التوكن لمنع تجسس الغرباء +++
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp"]})
        if not payload.get("is_admin"):
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    # فحص حالة الدرع الأمني قبل الدخول بالـ Loop
    is_connected = await dispatch_manager.connect(websocket)
    if not is_connected:
        return # إنهاء فوري بدون كراش إذا تم رفض الاتصال بسبب الـ DDoS Limit

    try:
        while True:
            # إبقاء الاتصال حياً
            await websocket.receive_text()
    except Exception as e:
        # +++ الكي الجراحي: اصطياد كافة الأخطاء (انقطاع مفاجئ، نوم متصفح، فصل شبكة) بصمت +++
        pass
    finally:
        # +++ التنظيف الإجباري (Graceful Disconnect): يضمن مسح الاتصال الميت من الذاكرة 100% مهما كانت طريقة خروج المستخدم +++
        dispatch_manager.disconnect(websocket)

@app.get("/")
async def root():
    return {"message": "Wanasah FastAPI Server is Running at Light Speed"}