import { useState } from "react";
import { Outlet } from "react-router-dom";
import { OperationsSidebar } from "./OperationsSidebar";
import { TopBar } from "./TopBar";

const DashboardLayout = () => {
    const [sidebarOpen, setSidebarOpen] = useState(false);

    return (
        <div className="min-h-screen mesh-gradient-bg p-3 md:p-4 flex gap-4" dir="rtl">
            {/* السايد بار له مصدر واحد وحالة واحدة هنا فقط */}
            <OperationsSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

            <main className="flex-1 flex flex-col gap-4 min-w-0">
                {/* التوب بار موحد لكل الصفحات */}
                <TopBar onMenuToggle={() => setSidebarOpen(true)} />

                {/* هنا سيتم عرض محتوى كل صفحة تلقائياً */}
                <Outlet />
            </main>
        </div>
    );
};

export default DashboardLayout;