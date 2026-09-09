from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "dashboard" / "src" / "App.tsx"
LOGIN = ROOT / "dashboard" / "src" / "pages" / "Login.tsx"
TYPES = ROOT / "dashboard" / "src" / "types" / "dispatch.ts"

APP_OLD1 = "    mutations: {\n      onError: (error: any) => {\n        toast.error(error?.message || 'حدث خطأ غير متوقع بالاتصال');\n      }\n    }\n"
APP_NEW1 = "    mutations: {\n      onError: (error) => {\n        toast.error(\n          error instanceof Error\n            ? error.message\n            : 'حدث خطأ غير متوقع بالاتصال'\n        );\n      }\n    }\n"
APP_OLD2 = "    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));\n    // فحص انتهاء مفتاح التجديد (30 يوم)\n    if (payload.exp && payload.exp * 1000 < Date.now()) {\n      localStorage.clear();\n      return false;\n    }\n    return true;\n"
APP_NEW2 = "    const base64Url = parts[1].replace(/-/g, '+').replace(/_/g, '/');\n    const padded = base64Url.padEnd(\n      base64Url.length + ((4 - (base64Url.length % 4)) % 4),\n      '='\n    );\n    const payload: unknown = JSON.parse(atob(padded));\n\n    if (\n      typeof payload !== 'object' ||\n      payload === null ||\n      !('type' in payload) ||\n      !('exp' in payload) ||\n      !('sub' in payload) ||\n      !('company_id' in payload)\n    ) {\n      return false;\n    }\n\n    const tokenPayload = payload as {\n      type: unknown;\n      exp: unknown;\n      sub: unknown;\n      company_id: unknown;\n    };\n\n    if (\n      tokenPayload.type !== 'refresh' ||\n      typeof tokenPayload.exp !== 'number' ||\n      tokenPayload.exp * 1000 < Date.now() ||\n      !tokenPayload.sub ||\n      !tokenPayload.company_id\n    ) {\n      return false;\n    }\n\n    return true;\n"
LOGIN_BLOCK = "const TENANT_SCOPED_STORAGE_KEYS = [\n  'activeTab',\n  'wanasah_selected_zone',\n  'wanasah_route_zone',\n  'wanasah_route_driver',\n  'wanasah_route_vehicle',\n  'shop_import_draft',\n] as const;\n\ninterface LoginResponsePayload {\n  token: string;\n  refresh_token: string;\n  driver_name: string;\n  is_admin: boolean;\n  company_id: number;\n  company_code: string;\n}\n\n"
LOGIN_OLD_PAYLOAD = '      const data = await response.json();\n'
LOGIN_NEW_PAYLOAD = '      const data = await response.json() as Partial<LoginResponsePayload>;\n'
LOGIN_OLD_CONTRACT = "      // 3. حماية اللوحة\n      if (!data.is_admin) {\n        throw new Error('عذراً، هذا الحساب غير مصرح له بالدخول للوحة التحكم');\n      }\n\n      // 4. حفظ بيانات الجلسة (شاملة هوية الشركة)\n      localStorage.setItem('admin_token', data.token);\n      localStorage.setItem('refresh_token', data.refresh_token);\n      if (data.company_id) localStorage.setItem('company_id', data.company_id.toString());\n      if (data.company_code) localStorage.setItem('company_code', data.company_code);\n      if (data.driver_name) {\n        localStorage.setItem('admin_name', data.driver_name);\n      }\n"
LOGIN_NEW_CONTRACT = "      // 3. حماية اللوحة + التحقق من عقد الاستجابة\n      if (!data.is_admin) {\n        throw new Error('عذراً، هذا الحساب غير مصرح له بالدخول للوحة التحكم');\n      }\n      if (\n        !data.token ||\n        !data.refresh_token ||\n        !data.company_id ||\n        !data.company_code ||\n        !data.driver_name\n      ) {\n        throw new Error('استجابة تسجيل الدخول غير مكتملة من السيرفر');\n      }\n\n      // 4. عزل حالة الواجهة بين الشركات على نفس المتصفح\n      const previousCompanyId = localStorage.getItem('company_id');\n      const nextCompanyId = String(data.company_id);\n      if (previousCompanyId && previousCompanyId !== nextCompanyId) {\n        TENANT_SCOPED_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));\n      }\n\n      // 5. حفظ بيانات الجلسة\n      localStorage.setItem('admin_token', data.token);\n      localStorage.setItem('refresh_token', data.refresh_token);\n      localStorage.setItem('company_id', nextCompanyId);\n      localStorage.setItem('company_code', data.company_code);\n      localStorage.setItem('admin_name', data.driver_name);\n"
LOGIN_OLD_CATCH = "      // 5. التوجيه\n      navigate('/'); \n\n    } catch (err: any) {\n      setError(err.message);\n"
LOGIN_NEW_CATCH = "      // 6. التوجيه\n      navigate('/'); \n\n    } catch (err: unknown) {\n      setError(\n        err instanceof Error\n          ? err.message\n          : 'حدث خطأ غير متوقع أثناء تسجيل الدخول'\n      );\n"
TYPES_OLD1 = '  startDate: string;\n  shopsCount?: number;\n'
TYPES_NEW1 = '  startDate: string;\n  intervalDays: number | null;\n  shopsCount?: number;\n'
TYPES_OLD2 = '  status: "pending" | "accepted" | "rejected";\n  created_at: string;\n  batch_id: string;\n'
TYPES_NEW2 = '  status: "pending" | "accepted" | "rejected" | "cancelled";\n  created_at: string | null;\n  batch_id: string;\n'


def fail(msg: str) -> None:
    raise SystemExit(f"PATCH_ABORTED: {msg}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"ALREADY_PATCHED={path.relative_to(ROOT)}:{label}")
        return
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected 1 match in {path.relative_to(ROOT)}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED={path.relative_to(ROOT)}:{label}")


for path in (APP, LOGIN, TYPES):
    if not path.exists():
        fail(f"Missing file: {path.relative_to(ROOT)}")


replace_once(APP, APP_OLD1, APP_NEW1, "query_mutation_unknown_error")
replace_once(APP, APP_OLD2, APP_NEW2, "refresh_guard_contract")

login_text = LOGIN.read_text(encoding="utf-8")
if "TENANT_SCOPED_STORAGE_KEYS" not in login_text:
    anchor_crlf = "import { useNavigate } from 'react-router-dom';\r\n\r\n"
    anchor_lf = "import { useNavigate } from 'react-router-dom';\n\n"
    if anchor_crlf in login_text:
        login_text = login_text.replace(anchor_crlf, anchor_crlf + LOGIN_BLOCK.replace("\n", "\r\n"), 1)
    elif anchor_lf in login_text:
        login_text = login_text.replace(anchor_lf, anchor_lf + LOGIN_BLOCK, 1)
    else:
        fail("Login.tsx import anchor not found.")
    LOGIN.write_text(login_text, encoding="utf-8")
    print("PATCHED=dashboard/src/pages/Login.tsx:tenant_storage_contract")
else:
    print("ALREADY_PATCHED=dashboard/src/pages/Login.tsx:tenant_storage_contract")

replace_once(LOGIN, LOGIN_OLD_PAYLOAD, LOGIN_NEW_PAYLOAD, "typed_login_payload")
replace_once(LOGIN, LOGIN_OLD_CONTRACT, LOGIN_NEW_CONTRACT, "login_tenant_isolation")
replace_once(LOGIN, LOGIN_OLD_CATCH, LOGIN_NEW_CATCH, "typed_login_catch")

replace_once(TYPES, TYPES_OLD1, TYPES_NEW1, "zone_interval_days_contract")
replace_once(TYPES, TYPES_OLD2, TYPES_NEW2, "route_transfer_contract")

app_text = APP.read_text(encoding="utf-8")
login_text = LOGIN.read_text(encoding="utf-8")
types_text = TYPES.read_text(encoding="utf-8")

checks = {
    "APP_NO_EXPLICIT_ANY": "error: any" not in app_text,
    "APP_REFRESH_TYPE_GUARD": "tokenPayload.type !== 'refresh'" in app_text,
    "LOGIN_NO_EXPLICIT_ANY": "catch (err: any)" not in login_text,
    "LOGIN_RESPONSE_TYPED": "Partial<LoginResponsePayload>" in login_text,
    "LOGIN_TENANT_STATE_CLEAR": "TENANT_SCOPED_STORAGE_KEYS.forEach" in login_text,
    "ZONE_INTERVAL_DAYS": "intervalDays: number | null;" in types_text,
    "TRANSFER_CANCELLED": '"cancelled"' in types_text,
    "TRANSFER_CREATED_NULLABLE": "created_at: string | null;" in types_text,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    fail(f"Static verification failed: {failed}")

print("APP_AUTH_GUARD_ALIGNMENT=OK")
print("LOGIN_RESPONSE_CONTRACT=OK")
print("LOGIN_TENANT_UI_ISOLATION=OK")
print("DISPATCH_TYPES_BACKEND_ALIGNMENT=OK")
print("DASHBOARD_AUTH_CONTRACTS_V1=OK")
