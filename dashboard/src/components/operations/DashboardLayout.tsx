import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { useState } from "react";
import { Outlet, useLocation, Navigate } from "react-router-dom";
import { OperationsSidebar } from "./OperationsSidebar";
import { TopBar } from "./TopBar";
import { Menu } from "lucide-react";
import "./dashboard.css";

const DashboardLayout = () => {
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const location = useLocation();
    const access = useInventoryAccess();
    if (access.isPending) return <div className="dashboard-access-state" dir="rtl"><span aria-hidden="true" /><p>جاري تحميل صلاحيات الحساب...</p></div>;
    if (access.isError) return <div className="dashboard-access-state dashboard-access-state--error" dir="rtl"><strong>تعذر التحقق من صلاحيات الحساب</strong><button onClick={() => void access.refetch()}>إعادة المحاولة</button></div>;
    if (!access.isCompanyAdmin && location.pathname === '/') return <Navigate to="/inventory" replace />;
    if (!access.isCompanyAdmin && location.pathname === '/dispatch' && !access.canAny('dispatch.read')) return <Navigate to="/inventory" replace />;

    return (
        // +++ الكي الجراحي 1: قفل الشاشة الإجباري (h-screen overflow-hidden) لنسف أي سكرول خارجي نهائياً +++
        <div className="dashboard-shell h-screen overflow-hidden mesh-gradient-bg p-3 md:p-4 flex gap-4" dir="rtl">
            
            {/* القائمة الجانبية ستصبح Sticky من الداخل لتبقى ملتصقة أثناء النزول */}
            <OperationsSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

            {/* +++ إزالة overflow-hidden ليأخذ المحتوى راحته الكاملة بالنزول +++ */}
            <div className="dashboard-main-stage flex-1 flex flex-col min-w-0">
                
                {/* +++ تم إعدام البار العلوي المكرر لتوفير المساحة +++ */}
                {/* زر الموبايل العائم (يظهر دائماً على الشاشات الصغيرة كبديل للبار العلوي) */}
                <button
                    onClick={() => setSidebarOpen(true)}
                    className="dashboard-mobile-menu lg:hidden fixed top-4 right-4 z-50 w-10 h-10 rounded-xl bg-white shadow-md flex items-center justify-center border border-slate-200"
                    aria-label="فتح قائمة التنقل"
                >
                    <Menu className="w-5 h-5 text-slate-700" />
                </button>

                <main className="dashboard-content flex-1 flex flex-col gap-4 mt-2 min-h-0">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};

export default DashboardLayout;
