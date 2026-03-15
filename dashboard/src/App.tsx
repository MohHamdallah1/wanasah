import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import OperationsDashboard from "./pages/OperationsDashboard";
import DispatchBoard from "./pages/DispatchBoard";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

// حارس: يمنع غير المسجلين من دخول اللوحة
const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const token = localStorage.getItem('admin_token');
  if (!token) return <Navigate to="/login" replace />;
  return children;
};

// حارس: يمنع المسجلين من العودة لصفحة الدخول
const PublicRoute = ({ children }: { children: JSX.Element }) => {
  const token = localStorage.getItem('admin_token');
  if (token) return <Navigate to="/" replace />;
  return children;
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Routes>
          {/* مسار الدخول محمي بـ PublicRoute */}
          <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
          
          {/* لوحة التحكم محمية بـ ProtectedRoute */}
          <Route path="/" element={<ProtectedRoute><OperationsDashboard /></ProtectedRoute>} />
          <Route path="/dispatch" element={<ProtectedRoute><DispatchBoard /></ProtectedRoute>} />
          
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;