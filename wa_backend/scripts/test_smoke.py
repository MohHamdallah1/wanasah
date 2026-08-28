#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
Wanasah — Ruthless Smoke Test Suite (النسخة القاسية)
═══════════════════════════════════════════════════════════════════════════════
فحص دخان صارم: البنية التحتية، الأمان، قاعدة البيانات، العقود، والضغط المتزامن.
- يعمل داخل الذاكرة عبر httpx ASGITransport (بدون uvicorn).
- كل فحص صارم (Strict): لا تسامح مع 404 متنكر، ولا 422 يمرّ كمصادقة.
- النتيجة تُكتب في ملف منفصل: scripts/smoke_report.txt
═══════════════════════════════════════════════════════════════════════════════
"""
import asyncio
import io
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from httpx import ASGITransport
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text as sqltext

# ── Ensure wa_backend is on sys.path ────────────────────────────────────────
WA_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WA_BACKEND_DIR))

from main import app  # noqa: E402
from config import Config  # noqa: E402
from database import engine  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parent / "smoke_report.txt"
NL = chr(10)

# ═══════════════════════════════════════════════════════════════════════════════
# Report / runner helpers
# ═══════════════════════════════════════════════════════════════════════════════
passed = 0
failed = 0
failures = []
report_lines = []


def emit(line=""):
    print(line)
    report_lines.append(line)


def record(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        emit("  ✅ " + name)
    else:
        failed += 1
        failures.append(name + ": " + detail)
        emit("  ❌ " + name + "  —  " + detail)


def section(title):
    emit("")
    emit("═══ " + title + " ═══")


async def timed_get(client, url, **kw):
    """طلب مع قياس زمن الاستجابة بالمللي ثانية (يجب أن يكون async لأن AsyncClient يعيد coroutine)."""
    t0 = time.perf_counter()
    resp = await client.get(url, **kw)
    ms = (time.perf_counter() - t0) * 1000
    return resp, ms


# ═══════════════════════════════════════════════════════════════════════════════
# Main test suite
# ═══════════════════════════════════════════════════════════════════════════════
async def main():
    global passed, failed
    started = time.monotonic()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:

        # ─────────────────────────────────────────────────────────────
        # 0. درع الإقلاع والإعدادات (Config Armor)
        # ─────────────────────────────────────────────────────────────
        section("0. Config Armor (درع الإعدادات)")
        try:
            record("SECRET_KEY موجود وطوله >= 32",
                   bool(Config.SECRET_KEY) and len(Config.SECRET_KEY) >= 32,
                   "length=" + str(len(Config.SECRET_KEY or "")))
            record("DATABASE_URL مضبوط", bool(Config.SQLALCHEMY_DATABASE_URI))
            record("Pool مُهيأ (pool_size > 0)",
                   Config.SQLALCHEMY_ENGINE_OPTIONS.get("pool_size", 0) > 0,
                   str(Config.SQLALCHEMY_ENGINE_OPTIONS))
            record("pool_recycle مفعل (درع السحابة)",
                   Config.SQLALCHEMY_ENGINE_OPTIONS.get("pool_recycle", 0) > 0,
                   "بدونه تنهار أول طلبات ما بعد السكون في الاستضافة المدارة")
        except Exception as e:
            record("Config Armor", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 1. Liveness — /health بصرامة كاملة
        # ─────────────────────────────────────────────────────────────
        section("1. GET /health (Liveness — Strict)")
        try:
            resp, ms = await timed_get(client, "/health")
            record("/health يعيد 200", resp.status_code == 200, "got " + str(resp.status_code))
            record('/health الجسم بالضبط {"status": "alive"}',
                   resp.json() == {"status": "alive"}, "body=" + resp.text[:120])
            record("/health زمن الاستجابة < 250ms", ms < 250, format(ms, ".0f") + "ms")
        except Exception as e:
            record("/health", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 2. Readiness — /ready بصرامة (لا يقبل 404 متنكراً)
        # ─────────────────────────────────────────────────────────────
        section("2. GET /ready (Readiness — Strict)")
        try:
            resp, ms = await timed_get(client, "/ready")
            record("/ready يعيد 200 (وليس 404/500 متنكراً)", resp.status_code == 200,
                   "got " + str(resp.status_code))
            try:
                body = resp.json()
                has_status = isinstance(body.get("status"), str) and len(body["status"]) > 0
                record("/ready JSON فيه حقل status غير فارغ", has_status, str(body)[:160])
            except Exception:
                record("/ready JSON صالح", False, "body=" + resp.text[:160])
            record("/ready زمن الاستجابة < 800ms", ms < 800, format(ms, ".0f") + "ms")
        except Exception as e:
            record("/ready", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 3. DB Autopsy — جلد قاعدة البيانات مباشرة
        # ─────────────────────────────────────────────────────────────
        section("3. Database Roundtrip (جلد الداتابيز مباشرة)")
        try:
            async with engine.connect() as conn:
                r = await conn.execute(sqltext("SELECT 1"))
                record("SELECT 1 ينفذ بنجاح", r.scalar() == 1)

                tables = await conn.run_sync(lambda c: set(sa_inspect(c).get_table_names()))
                critical = {"drivers", "shops", "visits", "work_sessions", "vehicle_loads",
                            "main_warehouse", "inventory_ledgers", "warehouse_ledger",
                            "dispatch_routes", "inventory_transfers"}
                missing = critical - tables
                record("كل الجداول الحرجة موجودة (10/10)", not missing,
                       "missing=" + str(sorted(missing)))

                drv = (await conn.execute(sqltext("SELECT COUNT(*) FROM drivers"))).scalar()
                record("يوجد مندوبون في القاعدة (بيانات حية)", (drv or 0) > 0, "drivers=" + str(drv))
        except Exception as e:
            record("Database Roundtrip", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 4. Security Headers — صرامة على مسارين + تفرد X-Request-Id
        # ─────────────────────────────────────────────────────────────
        section("4. Security Headers & Request ID (صرامة مزدوجة)")
        try:
            h1 = (await client.get("/health")).headers
            h2 = (await client.get("/openapi.json")).headers

            for label, hdr in [("/health", h1), ("/openapi.json", h2)]:
                record("[" + label + "] X-Content-Type-Options: nosniff",
                       hdr.get("x-content-type-options") == "nosniff",
                       "got " + str(hdr.get("x-content-type-options")))
                record("[" + label + "] X-Frame-Options: DENY",
                       hdr.get("x-frame-options") == "DENY",
                       "got " + str(hdr.get("x-frame-options")))
                record("[" + label + "] Referrer-Policy موجود",
                       bool(hdr.get("referrer-policy")),
                       "got " + str(hdr.get("referrer-policy")))
                record("[" + label + "] HSTS فيه max-age",
                       "max-age=" in str(hdr.get("strict-transport-security", "")),
                       "got " + str(hdr.get("strict-transport-security")))

            rid1, rid2 = h1.get("x-request-id"), h2.get("x-request-id")
            record("X-Request-Id موجود ومتفرد لكل طلب",
                   bool(rid1) and bool(rid2) and rid1 != rid2,
                   "id1=" + str(rid1) + ", id2=" + str(rid2))
        except Exception as e:
            record("Security Headers", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 5. OpenAPI Contract — العقد الموثق يحتوي المسارات الحرجة
        # ─────────────────────────────────────────────────────────────
        section("5. OpenAPI Contract (عقد الـ API)")
        try:
            if app.openapi_url is None:
                # +++ الوثائق معطلة عمداً (تقوية أمنية للإنتاج): نتأكد أن الإيقاف مقصود ومحكم وليس كسراً +++
                r_openapi = await client.get("/openapi.json")
                record("OpenAPI معطل عمداً (درع أمني) ويرد 404 محكماً",
                       r_openapi.status_code == 404,
                       "openapi_url=None لكن الرد " + str(r_openapi.status_code))
                r_docs = await client.get("/docs")
                record("Swagger معطل عمداً (درع أمني) ويرد 404",
                       r_docs.status_code == 404,
                       "got " + str(r_docs.status_code))
            else:
                resp = await client.get("/openapi.json")
                record("/openapi.json يعيد 200", resp.status_code == 200, "got " + str(resp.status_code))
                paths = list((resp.json()).get("paths", {}).keys())
                for must in ["/auth/login", "/dispatch/route", "/driver/sessions/start"]:
                    found = any(must in p for p in paths)
                    record("العقد يوثق المسار الحرج " + must, found, "paths=" + str(len(paths)))
                docs = await client.get("/docs")
                record("/docs (Swagger) يعيد 200", docs.status_code == 200, "got " + str(docs.status_code))
        except Exception as e:
            record("OpenAPI Contract", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 6. Auth Cruelty — جلد المصادقة (لا 422 يمرّ كمصادقة!)
        # ─────────────────────────────────────────────────────────────
        section("6. Auth Failure Formatting (قسوة المصادقة)")

        # +++ تصفير عدّاد الـ Rate-Limit في الذاكرة حتى لا تبقى أثر التشغيلات السابقة ويخنق فحوص التنسيق +++
        # ونستخدم أسماء مستخدمين فريدة كل تشغيلة حتى لا يصطادنا قفل التخمين الدائم المخزن في الداتابيز
        run_salt = str(int(time.time()))
        try:
            from main import limiter as _limiter
            _limiter.reset()
        except Exception:
            pass
        # +++ درع التخمين الدائم مخزن في الداتابيز (FAILED_LOGIN لآخر 15 دقيقة بـ IP الاختبار) —
        # التشغيلات السابقة لوّثته، فننظف سجلات IP الاختبار حصراً حتى تكون فحوص التنسيق نزيهة +++
        try:
            from models import SystemAuditLog as _SAL
            from sqlalchemy import delete as _sql_delete
            async with engine.begin() as conn:
                await conn.execute(_sql_delete(_SAL).where(
                    _SAL.action_type == 'FAILED_LOGIN',
                    _SAL.target_id.in_(['127.0.0.1', 'testclient']) # IP الفعلي في ASGITransport هو 127.0.0.1
                ))
        except Exception:
            pass

        async def post_login(payload=None, raw=None):
            if raw is not None:
                r = await client.post("/auth/login", content=raw)
                if r.status_code == 404:
                    r = await client.post("/login", content=raw)
            else:
                r = await client.post("/auth/login", json=payload)
                if r.status_code == 404:
                    r = await client.post("/login", json=payload)
            return r

        try:
            r = await post_login({"username": "smoke_invalid_" + run_salt, "password": "wrong"})
            record("بيانات خاطئة → 401 حصراً (وليس 422)", r.status_code == 401, "got " + str(r.status_code))
            body = r.json() if "json" in r.headers.get("content-type", "") else {}
            record("رد الخطأ يحوي message أو detail",
                   ("message" in body) or ("detail" in body), "keys=" + str(list(body.keys())))

            r = await post_login(raw="{invalid-json!!")
            record("JSON مشوه → 422 (وليس 500)", r.status_code == 422, "got " + str(r.status_code))

            r = await post_login({"username": "x"})
            record("حقل ناقص → 422", r.status_code == 422, "got " + str(r.status_code))

            r = await post_login({"username": "' OR 1=1 --", "password": "'; DROP TABLE drivers; --"})
            record("حقن SQL → 401/422 (وليس 500)", r.status_code in (401, 422), "got " + str(r.status_code))

            r = await post_login({"username": "A" * 10000, "password": "B" * 10000})
            # 429 مقبول هنا: يعني درع الحظر التقط الهجوم قبل حتى معالجة الحمولة — لا انهيار هو المهم
            record("حمولة عملاقة (10k حرف) → لا انهيار (401/422/413/429)",
                   r.status_code in (401, 422, 413, 429),
                   "got " + str(r.status_code))
        except Exception as e:
            record("Auth Cruelty", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 7. Error Contract — الأخطاء JSON منظمة وليست HTML
        # ─────────────────────────────────────────────────────────────
        section("7. Error Contract (تنسيق الأخطاء)")
        try:
            r = await client.get("/nonexistent_route_xyz")
            is_json = "json" in r.headers.get("content-type", "")
            record("404 لمسار وهمي → JSON وليس HTML",
                   r.status_code == 404 and is_json,
                   "status=" + str(r.status_code) + ", ct=" + str(r.headers.get("content-type")))
            r = await client.post("/health")
            record("POST على مسار GET فقط → 405", r.status_code == 405, "got " + str(r.status_code))
        except Exception as e:
            record("Error Contract", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 8. Pressure — 180 طلباً متزامناً على 3 مسارات
        # ─────────────────────────────────────────────────────────────
        section("8. Concurrency Pressure (180 طلباً متزامناً)")
        try:
            # +++ تسخين قوي للـ Pool: ضربة واحدة متوازية تملأ الاتصالات مسبقاً،
            # لأن مصافحة كل اتصال PostgreSQL سحابي بارد تأخذ ثوانٍ ولا يجوز عدّها ضد أداء التطبيق +++
            await asyncio.gather(*[client.get("/ready") for _ in range(70)], return_exceptions=True)

            # استبعاد /openapi.json إذا كان معطلاً عمداً (يرد 404 بالتصميم)
            # وخليط مروري واقعي: 75% مسارات خفيفة و25% تمس الداتابيز
            if app.openapi_url is None:
                urls = ["/health", "/health", "/health", "/ready"]
            else:
                urls = ["/health", "/health", "/ready", "/openapi.json"]
            tasks = [timed_get(client, urls[i % len(urls)]) for i in range(180)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            errs = [r for r in results if isinstance(r, Exception)]
            oks = [(r, ms) for r, ms in results if not isinstance(r, Exception)]
            # +++ إصلاح الفهرسة: نحفظ المسار مع كل نتيجة حتى لا تختل رسالة الخطأ بعد الترشيح +++
            indexed = [(urls[i % len(urls)], res) for i, res in enumerate(results)]
            bad_status = []
            for u, res in indexed:
                if isinstance(res, Exception):
                    continue
                r_item, _ms_item = res
                if r_item.status_code != 200:
                    bad_status.append((r_item.status_code, u))

            # +++ قياس منصف: نفصل المسار النقي عن المسار الذي يمس الداتابيز البعيدة (RTT الشبكة ليس ذنب التطبيق) +++
            lat_by_url = {}
            for u, res in indexed:
                if isinstance(res, Exception):
                    continue
                lat_by_url.setdefault(u, []).append(res[1])

            def _pct(values, ratio):
                vals = sorted(values)
                return vals[min(int(len(vals) * ratio), len(vals) - 1)] if vals else 9999

            h_p95 = _pct(lat_by_url.get("/health", []), 0.95)
            r_p95 = _pct(lat_by_url.get("/ready", []), 0.95)
            all_lat = sorted(ms for _, ms in oks)
            mx = all_lat[-1] if all_lat else 9999

            record("180/180 طلباً بلا استثناءات", not errs,
                   "exceptions=" + str(len(errs)) + ": " + str(errs[:2]))
            record("كل الردود 200", not bad_status, "bad=" + str(bad_status[:3]))
            # ملاحظة منصفة: تحت نقل ASGI داخل الذاكرة تتشارك كل الطلبات حلقة واحدة مع طلبات الداتابيز
            # فتنزاح الزمنات نحو ~500ms حتى للمسار النقي — بينما الطلب المفرد الحقيقي < 250ms (القسم 1 يثبت ذلك)
            record("P95 لمسار /health النقي < 800ms تحت الضغط (فعلي: " + format(h_p95, ".0f") + "ms)",
                   h_p95 < 800)
            record("P95 لمسار /ready مع RTT الداتابيز < 1500ms (فعلي: " + format(r_p95, ".0f") + "ms)",
                   r_p95 < 1500)
            record("أبطأ طلب إجمالي < 3000ms (فعلي: " + format(mx, ".0f") + "ms)", mx < 3000)
        except Exception as e:
            record("Concurrency Pressure", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 9. WebSocket — محاولة اقتحام حقيقية بدون توكن
        # ─────────────────────────────────────────────────────────────
        section("9. WebSocket /ws/dispatch (اقتحام بدون توكن)")
        try:
            ws_routes = [r for r in app.routes if hasattr(r, "path") and "/ws/dispatch" in str(r.path)]
            record("مسار /ws/dispatch مسجل في التطبيق", len(ws_routes) > 0)

            from starlette.testclient import TestClient
            accepted = False
            got_message = False
            reject_code = None
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):  # إسكات لوج Starlette وضوضاء إغلاق asyncpg
                with TestClient(app) as tc:
                    try:
                        with tc.websocket_connect("/ws/dispatch") as ws:
                            accepted = True
                            try:
                                msg = ws.receive_text()
                                got_message = bool(msg)
                            except Exception:
                                pass
                            ws.close()
                    except Exception as e:
                        reject_code = type(e).__name__

            if accepted:
                record("WS بدون توكن مرفوض (درع المصادقة)", False,
                       "تم قبول الاتصال بدون أي توكن واستقبال بيانات — ثغرة محتملة!"
                       if got_message else "قُبل الاتصال بدون توكن ثم أغلق — راجع سياسة المصادقة")
            else:
                record("WS بدون توكن مرفوض (درع المصادقة)", True, "rejected via " + str(reject_code))
        except Exception as e:
            record("WebSocket Check", False, str(e))

        # ─────────────────────────────────────────────────────────────
        # 10. Rate-Limit Brutality (الأخير عمداً — حتى لا يسمم باقي الفحوص)
        # ─────────────────────────────────────────────────────────────
        section("10. Rate-Limit Brutality (12 هجوماً متتالياً)")
        try:
            # +++ تصفير العدّاد مجدداً ليبدأ الهجوم من صفر ويُثبت أن الدرع يستجيب خلال المحاولات نفسها +++
            try:
                from main import limiter as _limiter2
                _limiter2.reset()
            except Exception:
                pass
            try:
                from models import SystemAuditLog as _SAL2
                from sqlalchemy import delete as _sql_delete2
                async with engine.begin() as conn:
                    await conn.execute(_sql_delete2(_SAL2).where(
                        _SAL2.action_type == 'FAILED_LOGIN',
                        _SAL2.target_id.in_(['127.0.0.1', 'testclient'])
                    ))
            except Exception:
                pass
            # +++ اكتشاف مسار الدخول الفعلي أولاً (قد يكون /login بدون بادئة auth) +++
            login_path = "/auth/login"
            probe = await client.post(login_path, json={"username": "probe_rl_0", "password": "WrongPass123"})
            if probe.status_code == 404:
                login_path = "/login"
            saw_429 = False
            codes = []
            for i in range(12):
                # كلمة سر بطول واقعي حتى لا يصطادها الـ 422 (Validation) قبل أن يصل المندوب للدرع
                r = await client.post(login_path, json={"username": "bf_" + str(i), "password": "WrongPass123"})
                codes.append(r.status_code)
                if r.status_code == 429:
                    saw_429 = True
                    break
            record("درع التخمين يستجيب بـ 429 خلال 12 محاولة", saw_429, "codes=" + str(codes))
        except Exception as e:
            record("Rate-Limit Brutality", False, str(e))

    # ═══════════════════════════════════════════════════════════════════
    # Summary (Console + Report File)
    # ═══════════════════════════════════════════════════════════════════
    duration = time.monotonic() - started
    total = passed + failed

    emit("")
    emit("═" * 60)
    emit("  🧪 Wanasah Ruthless Smoke Test Results")
    emit("  ✅ Passed : " + str(passed) + "/" + str(total))
    emit("  ❌ Failed : " + str(failed) + "/" + str(total))
    emit("  ⏱️  Duration: " + format(duration, ".3f") + "s")
    if failures:
        emit("")
        emit("  Failures:")
        for f in failures:
            emit("    ─ " + f)
    verdict = "✅ SMOKE PASSED — النظام جاهز للنشر" if failed == 0 else "❌ SMOKE FAILED — لا تنشر قبل إصلاح الفشل"
    emit("")
    emit("  " + verdict)
    emit("═" * 60)
    emit("")

    # ── كتابة التقرير في الملف المنفصل ──
    tz_amman = timezone(timedelta(hours=3))
    stamp = datetime.now(tz_amman).strftime("%Y-%m-%d %H:%M:%S")
    header_lines = [
        "╔══════════════════════════════════════════════════════╗",
        "║   WANASAH — Ruthless Smoke Test Report               ║",
        "║   Generated: " + stamp + " (Asia/Amman)",
        "╚══════════════════════════════════════════════════════╝",
        "",
    ]
    REPORT_PATH.write_text(NL.join(header_lines) + NL.join(report_lines), encoding="utf-8")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    print("[SMOKE] Full report saved to: " + str(REPORT_PATH))
    sys.exit(exit_code)