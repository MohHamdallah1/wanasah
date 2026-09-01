import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { OperationsSidebar } from "./OperationsSidebar";
import { TopBar } from "./TopBar";
import { Menu } from "lucide-react";

const DashboardLayout = () => {
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const location = useLocation();

    return (
        // +++ الكي الجراحي 1: قفل الشاشة الإجباري (h-screen overflow-hidden) لنسف أي سكرول خارجي نهائياً +++
        <div className="h-screen overflow-hidden mesh-gradient-bg p-3 md:p-4 flex gap-4" dir="rtl">
            
            {/* القائمة الجانبية ستصبح Sticky من الداخل لتبقى ملتصقة أثناء النزول */}
            <OperationsSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

            {/* +++ إزالة overflow-hidden ليأخذ المحتوى راحته الكاملة بالنزول +++ */}
            <div className="flex-1 flex flex-col min-w-0">
                
                {/* +++ تم إعدام البار العلوي المكرر لتوفير المساحة +++ */}
                {/* زر الموبايل العائم (يظهر دائماً على الشاشات الصغيرة كبديل للبار العلوي) */}
                <button
                    onClick={() => setSidebarOpen(true)}
                    className="lg:hidden fixed top-4 right-4 z-50 w-10 h-10 rounded-xl bg-white shadow-md flex items-center justify-center border border-slate-200"
                >
                    <Menu className="w-5 h-5 text-slate-700" />
                </button>

                <main className="flex-1 flex flex-col gap-4 mt-2 min-h-0">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};

export default DashboardLayout;