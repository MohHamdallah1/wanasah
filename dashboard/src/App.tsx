import { Component } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import DashboardLayout from "@/components/operations/DashboardLayout";
import OperationsDashboard from "./pages/OperationsDashboard";
import DispatchBoard from "./pages/DispatchBoard";
import MainInventory from "./pages/inventory/MainInventory";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

// H-05: Helper to check JWT expiry before trusting localStorage token
// Step 4.3c.1: Base64URL-safe and UTF-8-aware JWT decoder
const isTokenValid = (): boolean => {
  const token = localStorage.getItem('admin_token');
  if (!token) return false;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return false;
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    const payload = JSON.parse(jsonPayload);
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      localStorage.removeItem('admin_token');
      return false;
    }
    return true;
  } catch {
    localStorage.removeItem('admin_token');
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
              onClick={() => { localStorage.clear(); window.location.href = '/login'; }}
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
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <DashboardErrorBoundary>
          <Routes>
            {/* مسار الدخول محمي بـ PublicRoute */}
            <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />

            {/* لوحة التحكم الموحدة محمية بـ ProtectedRoute */}
            <Route element={<ProtectedRoute><DashboardLayout /></ProtectedRoute>}>
              <Route path="/" element={<OperationsDashboard />} />
              <Route path="/dispatch" element={<DispatchBoard />} />
              <Route path="/inventory" element={<MainInventory />} />
            </Route>

            <Route path="*" element={<NotFound />} />
          </Routes>
        </DashboardErrorBoundary>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
