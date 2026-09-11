import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Building2, KeyRound, LockKeyhole, ShieldCheck, UserRound } from "lucide-react";
import { loginPlatformAdmin } from "@/features/platform/api";
import { savePlatformSession } from "@/features/platform/session";
import { apiErrorMessage } from "@/lib/apiErrors";
import "./login.css";

export default function PlatformLogin() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("أدخل اسم مستخدم مدير المنصة وكلمة المرور.");
      return;
    }

    setError("");
    setIsSubmitting(true);
    try {
      const response = await loginPlatformAdmin(username.trim(), password);
      savePlatformSession(response.token, response.admin);
      navigate("/platform", { replace: true });
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "تعذر تسجيل الدخول إلى إدارة المنصة."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="login-shell relative min-h-screen flex items-center justify-center overflow-hidden w-full text-white" dir="rtl">
      <div className="login-background" />
      <div className="login-frame relative z-20">
        <aside className="login-context-panel">
          <div className="login-brand">
            <span>W</span>
            <div><strong>WANASAH</strong><small>Platform Administration</small></div>
          </div>
          <div className="login-context-copy">
            <p>إدارة المنصة السيادية</p>
            <h1>تأسيس الشركات وإدارة نطاقات المنصة من بوابة مستقلة.</h1>
            <span>جلسة قصيرة الصلاحية ومنفصلة بالكامل عن حسابات الشركات وبياناتها التشغيلية.</span>
          </div>
          <div className="login-trust-points">
            <div><ShieldCheck /><span><strong>وصول سيادي محمي</strong><small>توكن مستقل قصير الصلاحية</small></span></div>
            <div><Building2 /><span><strong>تأسيس مضبوط</strong><small>شركة وفرع رئيسي ومدير</small></span></div>
          </div>
        </aside>

        <div className="login-form-column">
          <div className="login-card">
            <div className="login-form-heading">
              <p>PLATFORM ADMIN</p>
              <h2>دخول إدارة المنصة</h2>
              <span>هذه البوابة مخصصة لحسابات إدارة المنصة فقط.</span>
            </div>

            <form onSubmit={handleSubmit} className="login-form text-start">
              <label className="login-field" htmlFor="platform-username">
                <span>اسم المستخدم</span>
                <div><UserRound /><input id="platform-username" value={username} onChange={(event) => setUsername(event.target.value)} disabled={isSubmitting} autoComplete="username" /></div>
              </label>

              <label className="login-field" htmlFor="platform-password">
                <span>كلمة المرور</span>
                <div><LockKeyhole /><input id="platform-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={isSubmitting} autoComplete="current-password" /></div>
              </label>

              {error && <p role="alert" className="login-error">{error}</p>}

              <button type="submit" disabled={isSubmitting} className="login-submit">
                <span>{isSubmitting ? "جارٍ التحقق..." : "دخول إدارة المنصة"}</span>
                {!isSubmitting && <ArrowLeft />}
              </button>

              <Link to="/login" className="mt-2 flex items-center justify-center gap-2 text-xs font-bold text-slate-500 hover:text-slate-800">
                <KeyRound className="h-4 w-4" />
                العودة إلى بوابة الشركات
              </Link>
            </form>
          </div>
        </div>
      </div>
    </section>
  );
}

