import { currentLocale } from "@/i18n";
import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Building2, LockKeyhole, ShieldCheck, UserRound } from 'lucide-react';
import './login.css';

const TENANT_SCOPED_STORAGE_KEYS = [
  'activeTab',
  'wanasah_selected_zone',
  'wanasah_route_zone',
  'wanasah_route_driver',
  'wanasah_route_vehicle',
  'shop_import_draft',
] as const;

interface LoginResponsePayload {
  token: string;
  refresh_token: string;
  driver_name: string;
  is_admin: boolean;
  dashboard_access: boolean;
  driver_id: number;
  company_id: number;
  company_code: string;
  message?: string;
}

export default function Login() {
  const navigate = useNavigate();
  // +++ حقن رمز الشركة الافتراضي في بيئة التطوير فقط (Dev Environment) +++
  const [companyCode, setCompanyCode] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState('');
  // +++  (E-10): استخدام useRef لمنع البحث في شجرة الـ DOM مع كل حركة ماوس +++
  const spotlightRef = useRef<HTMLDivElement>(null);

  // تشغيل الساعة الرقمية
  useEffect(() => {
    // +++  (E-09): إزالة الثواني وتحديث الشاشة كل 10 ثوانٍ فقط لمنع الـ Re-render المفرط +++
    const updateTime = () => setCurrentTime(new Date().toLocaleTimeString(currentLocale(), { hour12: false, hour: '2-digit', minute: '2-digit' }));
    updateTime();
    const timer = setInterval(updateTime, 10000);
    return () => clearInterval(timer);
  }, []);

  // تأثير إضاءة الماوس
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (spotlightRef.current) {
        spotlightRef.current.style.background = `radial-gradient(circle 250px at ${e.clientX}px ${e.clientY}px, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 30%, transparent 80%)`;
      }
    };
    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!companyCode || !username || !password) {
      setError("الرجاء إدخال رمز الشركة واسم المستخدم وكلمة المرور.");
      return;
    }
    setError('');
    setIsSubmitting(true);

    try {
      // 1. الاتصال الحقيقي بالسيرفر
      // Fix: dashboard.md C-01 / CS-06 — Use environment-configured API base URL
      const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
      if (!API) {
        throw new Error("VITE_API_URL is not configured. The login page cannot connect to the server.");
      }
      const response = await fetch(`${API}/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        // +++ إرسال الرمز الديناميكي بدلاً من الـ Hardcoded +++
        body: JSON.stringify({ company_code: companyCode.trim(), username: username.trim(), password }),
      });

      const data = await response.json() as Partial<LoginResponsePayload>;

      // 2. التحقق من الرد
      if (!response.ok) {
        throw new Error(data.message || 'فشل تسجيل الدخول، تأكد من البيانات');
      }

      // 3. حماية اللوحة + التحقق من عقد الاستجابة
      if (!data.is_admin && data.dashboard_access !== true) {
        throw new Error('عذراً، هذا الحساب غير مصرح له بالدخول للوحة التحكم');
      }
      if (
        !data.token ||
        !data.refresh_token ||
        !data.company_id ||
        !data.company_code ||
        !data.driver_name ||
        !Number.isSafeInteger(data.driver_id) || Number(data.driver_id) <= 0
      ) {
        throw new Error('استجابة تسجيل الدخول غير مكتملة من السيرفر');
      }

      // 4. عزل حالة الواجهة بين الشركات على نفس المتصفح
      const previousCompanyId = localStorage.getItem('company_id');
      const nextCompanyId = String(data.company_id);
      if (previousCompanyId && previousCompanyId !== nextCompanyId) {
        TENANT_SCOPED_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key));
      }

      // 5. حفظ بيانات الجلسة
      localStorage.setItem('admin_token', data.token);
      localStorage.setItem('refresh_token', data.refresh_token);
      localStorage.setItem('company_id', nextCompanyId);
      localStorage.setItem('driver_id', String(data.driver_id));
      localStorage.setItem('company_code', data.company_code);
      localStorage.setItem('admin_name', data.driver_name);

      // 6. التوجيه
      navigate(data.is_admin ? '/' : '/inventory');

    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : 'حدث خطأ غير متوقع أثناء تسجيل الدخول'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="login-shell relative min-h-screen flex items-center justify-center overflow-hidden w-full text-white" dir="rtl">
      <div className="login-background cosmic-background" />
      <div ref={spotlightRef} id="mouse-spotlight-login" className="fixed inset-0 pointer-events-none z-0 transition-all duration-300" />

      {currentTime && (
        <div className="login-clock absolute top-5 left-5 z-30">
          <span>توقيت النظام</span><strong>{currentTime}</strong>
        </div>
      )}

      <div className="login-frame relative z-20">
        <aside className="login-context-panel">
          <div className="login-brand">
            <span>W</span>
            <div><strong>WANASAH</strong><small>Distribution Operations</small></div>
          </div>
          <div className="login-context-copy">
            <p>منصة العمليات الموحدة</p>
            <h1>تحكم واضح في التوزيع والمخزون من نقطة واحدة.</h1>
            <span>وصول مؤسسي مع عزل كامل بين الشركات ونطاقات تشغيل محددة لكل مستخدم.</span>
          </div>
          <div className="login-trust-points">
            <div><ShieldCheck /><span><strong>صلاحيات دقيقة</strong><small>الوصول حسب الشركة والموقع</small></span></div>
            <div><Building2 /><span><strong>تشغيل متعدد الشركات</strong><small>بيانات كل شركة معزولة</small></span></div>
          </div>
        </aside>

        <div className="login-form-column">
          <div className="login-card">
            <div className="login-form-heading">
              <p>بوابة الإدارة</p>
              <h2>تسجيل الدخول</h2>
              <span>أدخل بيانات حسابك المعتمدة للمتابعة.</span>
            </div>

          <form onSubmit={handleSubmit} className="login-form text-start">
            {/* +++ حقل إدخال رمز الشركة +++ */}
            <label className="login-field" htmlFor="company-code">
              <span>رمز الشركة</span>
              <div><Building2 /><input id="company-code" type="text" value={companyCode} onChange={(e) => setCompanyCode(e.target.value)} placeholder="مثال: WNS-01" disabled={isSubmitting} autoComplete="organization" /></div>
            </label>

            <label className="login-field" htmlFor="username">
              <span>اسم المستخدم</span>
              <div><UserRound /><input id="username" type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="أدخل اسم المستخدم" disabled={isSubmitting} autoComplete="username" /></div>
            </label>

            <label className="login-field" htmlFor="password">
              <span>كلمة المرور</span>
              <div><LockKeyhole /><input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="أدخل كلمة المرور" disabled={isSubmitting} autoComplete="current-password" /></div>
            </label>

            {error && <p role="alert" className="login-error">{error}</p>}

            <button
              type="submit"
              disabled={isSubmitting}
              className="login-submit"
            >
              <span>{isSubmitting ? 'جارٍ التحقق...' : 'دخول إلى لوحة التحكم'}</span>
              {!isSubmitting && <ArrowLeft />}
            </button>

            <Link to="/platform/login" className="mt-2 flex items-center justify-center gap-2 text-xs font-bold text-slate-500 hover:text-slate-800">
              <ShieldCheck className="h-4 w-4" />
              بوابة إدارة المنصة
            </Link>
          </form>
          </div>
        </div>
      </div>
    </section>
  );
}
