import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState('');

  // تشغيل الساعة الرقمية
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // تأثير إضاءة الماوس
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const spotlight = document.getElementById('mouse-spotlight-login');
      if (spotlight) {
        spotlight.style.background = `radial-gradient(circle 250px at ${e.clientX}px ${e.clientY}px, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 30%, transparent 80%)`;
      }
    };
    document.addEventListener('mousemove', handleMouseMove);
    return () => document.removeEventListener('mousemove', handleMouseMove);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError("الرجاء إدخال اسم المستخدم وكلمة المرور.");
      return;
    }
    setError('');
    setIsSubmitting(true);

    try {
      // 1. الاتصال الحقيقي بالسيرفر
      const response = await fetch('http://127.0.0.1:5000/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      // 2. التحقق من الرد
      if (!response.ok) {
        throw new Error(data.message || 'فشل تسجيل الدخول، تأكد من البيانات');
      }

      // 3. حماية اللوحة
      if (!data.is_admin) {
        throw new Error('عذراً، هذا الحساب غير مصرح له بالدخول للوحة التحكم');
      }

      // 4. حفظ بيانات الجلسة
      localStorage.setItem('admin_token', data.token);
      localStorage.setItem('admin_name', data.driver_name);
      localStorage.setItem('admin_id', data.driver_id);

      // 5. التوجيه
      navigate('/'); 

    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden w-full h-full text-white" dir="rtl">
      <div className="cosmic-background"></div>
      <div id="mouse-spotlight-login" className="fixed inset-0 pointer-events-none z-0 transition-all duration-300"></div>

      {currentTime && (
        <div className="absolute top-6 left-6 text-cyan-400 font-mono text-sm animate-pulse z-30 font-bold tracking-widest">
          {currentTime}
        </div>
      )}

      <div className="container mx-auto text-center relative z-20 flex flex-col items-center justify-center px-4">
        <h1 className="text-5xl sm:text-7xl font-extrabold mb-6 leading-tight relative text-shadow-glow tracking-tighter">
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-400">
            WANASAH
          </span>
        </h1>
        <p className="text-lg text-gray-300 mb-10 drop-shadow-md">
          بوابة التحكم الذكية لإدارة الأسطول والمبيعات
        </p>

        <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-xl p-8 border border-cyan-400/30 rounded-2xl shadow-[0_0_40px_rgba(0,255,255,0.1)] relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-400/70 to-transparent animate-[slideRight_10s_linear_infinite]"></div>
          <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-l from-transparent via-purple-400/70 to-transparent animate-[slideRight_10s_linear_infinite_reverse]"></div>

          <h2 className="text-2xl font-bold text-white mb-6 text-center">تسجيل الدخول</h2>
          
          <form onSubmit={handleSubmit} className="space-y-5 text-start">
            <div className="space-y-2">
              <label className="text-gray-300 text-sm font-medium">اسم المستخدم</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-slate-800/70 border border-slate-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all"
                placeholder="أدخل اسم المستخدم"
                disabled={isSubmitting}
              />
            </div>
            
            <div className="space-y-2">
              <label className="text-gray-300 text-sm font-medium">كلمة المرور</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-slate-800/70 border border-slate-600 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all"
                placeholder="أدخل كلمة المرور"
                disabled={isSubmitting}
              />
            </div>

            {error && <p className="text-red-400 text-sm text-center bg-red-900/40 py-2 rounded border border-red-700/50">{error}</p>}

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full mt-4 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white py-3 rounded-lg font-bold shadow-lg shadow-cyan-500/20 transition-all duration-300"
            >
              {isSubmitting ? 'جارٍ التحقق...' : 'دخول للغرفة'}
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}