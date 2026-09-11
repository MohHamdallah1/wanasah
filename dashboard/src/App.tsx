import { Component, lazy, Suspense } from "react";
// +++ الكي الجراحي: إزالة Toaster الميتة والإبقاء على Sonner فقط لتخفيف حجم المشروع +++
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { toast } from "sonner"; // +++  (E-11): استدعاء الـ Toast لعرض الأخطاء +++
import { readPlatformSession } from "@/features/platform/session";

// +++ الكي الجراحي: تحميل ديناميكي للصفحات لتفكيك الكتلة الضخمة في ملف index +++
const DashboardLayout = lazy(() => import("@/components/operations/DashboardLayout"));
const OperationsDashboard = lazy(() => import("./pages/OperationsDashboard"));
const DispatchBoard = lazy(() => import("./pages/DispatchBoard"));
const MainInventory = lazy(() => import("./pages/inventory/MainInventory"));
const Login = lazy(() => import("./pages/Login"));
const PlatformLogin = lazy(() => import("./pages/PlatformLogin"));
const PlatformDashboard = lazy(() => import("./pages/PlatformDashboard"));
const NotFound = lazy(() => import("./pages/NotFound"));

// +++  (E-11): إضافة Error Handling شامل للـ QueryClient +++
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
    mutations: {
      onError: (error) => {
        toast.error(
          error instanceof Error
            ? error.message
            : 'حدث خطأ غير متوقع بالاتصال'
        );
      }
    }
  },
});

// +++ الكي الجراحي: حارس ذكي يفحص الـ Payload بدون مكتبات خارجية، يمنع الوميض، ويحترم التجديد الصامت +++
const isTokenValid = (): boolean => {
  const refresh = localStorage.getItem('refresh_token');
  if (!refresh) return false; // إذا لم يوجد مفتاح تجديد، فهو مطرود قطعاً
  try {
    const parts = refresh.split('.');
    if (parts.length !== 3) return false;
    const base64Url = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64Url.padEnd(
      base64Url.length + ((4 - (base64Url.length % 4)) % 4),
      '='
    );
    const payload: unknown = JSON.parse(atob(padded));

    if (
      typeof payload !== 'object' ||
      payload === null ||
      !('type' in payload) ||
      !('exp' in payload) ||
      !('sub' in payload) ||
      !('company_id' in payload)
    ) {
      return false;
    }

    const tokenPayload = payload as {
      type: unknown;
      exp: unknown;
      sub: unknown;
      company_id: unknown;
    };

    if (
      tokenPayload.type !== 'refresh' ||
      typeof tokenPayload.exp !== 'number' ||
      tokenPayload.exp * 1000 < Date.now() ||
      !tokenPayload.sub ||
      !tokenPayload.company_id
    ) {
      return false;
    }

    return true;
  } catch {
    return false;
  }
};

// حارس: يمنع غير المسجلين من دخول اللوحة
const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  if (!isTokenValid()) return <Navigate to="/login" replace />;
  return children;
};

// حارس: يمنع المسجلين من العودة لصفحة الدخول
const PublicRoute = ({ children }: { children: JSX.Element }) => {
  if (isTokenValid()) return <Navigate to="/" replace />;
  return children;
};

const PlatformProtectedRoute = ({ children }: { children: JSX.Element }) => {
  if (!readPlatformSession()) return <Navigate to="/platform/login" replace />;
  return children;
};

const PlatformPublicRoute = ({ children }: { children: JSX.Element }) => {
  if (readPlatformSession()) return <Navigate to="/platform" replace />;
  return children;
};

// Step 4.5a: React Error Boundary to catch unhandled component crashes
interface ErrorBoundaryState { hasError: boolean; error: Error | null; }
class DashboardErrorBoundary extends Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-900" dir="rtl">
          <div className="text-center p-8 max-w-md">
            <div className="text-6xl mb-4">⚠️</div>
            <h1 className="text-2xl font-bold text-white mb-4">حدث خطأ غير متوقع</h1>
            <p className="text-slate-400 mb-6">نعتذر عن هذا الخلل. يرجى تحديث الصفحة أو التواصل مع الدعم الفني.</p>
            <button
              onClick={() => { 
                // +++ الكي الجراحي: إبلاغ السيرفر بحرق التوكن (Blacklist) حتى لو انهارت الشاشة +++
                const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
                const token = localStorage.getItem('admin_token');
                const refresh = localStorage.getItem('refresh_token');
                if (API_URL && token) {
                  fetch(`${API_URL}/logout`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}`, 'X-Refresh-Token': refresh || '' }
                  }).catch(() => {}); // Fire and forget
                }
                localStorage.clear(); 
                sessionStorage.clear();
                window.location.href = '/login'; 
              }}
              className="bg-cyan-600 hover:bg-cyan-500 text-white px-6 py-3 rounded-xl font-bold transition-all"
            >
              العودة لصفحة الدخول
            </button>
            <p className="text-slate-600 text-xs mt-4 font-mono" dir="ltr">
              {this.state.error?.message || 'Unknown error'}
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      {/* +++ الكي الجراحي: إزالة تحديد الموقع لتعود لمكانها الافتراضي مع الاحتفاظ بزر الإغلاق والثبات +++ */}
      <Sonner 
        richColors 
        closeButton 
        duration={6000} 
        pauseWhenPageIsHidden 
        expand={true} 
      />
      <BrowserRouter>
        <DashboardErrorBoundary>
          {/* +++ الكي الجراحي: إزالة الشاشة الزرقاء المزعجة وجعل التحميل صامتاً للحفاظ على إحساس السرعة اللحظية +++ */}
          <Suspense fallback={null}>
            <Routes>
              {/* مسار الدخول محمي بـ PublicRoute */}
              <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />

              {/* جلسة إدارة المنصة مستقلة عن جلسة أي شركة. */}
              <Route path="/platform/login" element={<PlatformPublicRoute><PlatformLogin /></PlatformPublicRoute>} />
              <Route path="/platform" element={<PlatformProtectedRoute><PlatformDashboard /></PlatformProtectedRoute>} />

              {/* لوحة التحكم الموحدة محمية بـ ProtectedRoute */}
              <Route element={<ProtectedRoute><DashboardLayout /></ProtectedRoute>}>
                <Route path="/" element={<OperationsDashboard />} />
                <Route path="/dispatch" element={<DispatchBoard />} />
                <Route path="/inventory" element={<MainInventory />} />
              </Route>

              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </DashboardErrorBoundary>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
