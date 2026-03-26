import { useState, useEffect } from "react";
import { getFleetStats } from "@/data/operations-data";
import type { DriverData } from "@/data/operations-data";
import { OperationsSidebar } from "@/components/operations/OperationsSidebar";
import { TopBar } from "@/components/operations/TopBar";
import { PulseBar } from "@/components/operations/PulseBar";
import { toast } from "sonner";
import { FleetRadar } from "@/components/operations/FleetRadar";
import { CommandCenter } from "@/components/operations/CommandCenter";
import { SettlementModal } from "@/components/operations/SettlementModal";

import { AlertTriangle, RotateCcw } from "lucide-react";

const Index = () => {
  const [drivers, setDrivers] = useState<DriverData[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSettlementModalOpen, setIsSettlementModalOpen] = useState(false);
  const [undoSessionId, setUndoSessionId] = useState<number | null>(null);

  const fetchLiveOperations = async () => {
    try {
      const token = localStorage.getItem('admin_token') || localStorage.getItem('token');
      const response = await fetch(`${import.meta.env.VITE_API_URL}/admin/sessions/today`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        }
      });
      if (response.ok) {
        const data = await response.json();
        setDrivers(data);
      }
    } catch (error) {
      console.error("فشل الاتصال بالسيرفر:", error);
    }
  };

  useEffect(() => {
    fetchLiveOperations();
    const interval = setInterval(fetchLiveOperations, 10000);
    return () => clearInterval(interval);
  }, []);

  const stats = getFleetStats(drivers);
  const selectedDriver = drivers.find((d) => d.session.session_id === selectedId) ?? null;

  // دالة زر الضوء الأخضر
  const handleToggleAuth = async (id: number) => {
    if (id < 0) {
      toast.error("لا يمكن إعطاء صلاحية البيع لمندوب لم يبدأ دوامه الفعلي من التطبيق.");
      return;
    }
    const driver = drivers.find((d) => d.session.session_id === id);
    if (!driver) return;
    const newAuthStatus = !driver.session.is_authorized_to_sell;

    setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: newAuthStatus } } : d));

    try {
      const token = localStorage.getItem('admin_token');
      const response = await fetch(`${import.meta.env.VITE_API_URL}/admin/sessions/${id}/authorize`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}` // تمرير المفتاح هنا
        },
        body: JSON.stringify({ is_authorized: newAuthStatus, inventory: [] })
      });
      if (!response.ok) throw new Error('فشل في تحديث الصلاحية');
    } catch (error) {
      setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: !newAuthStatus } } : d));
    }
  };

  // دالة تأكيد التسوية وإرسال الفروقات للخادم
  const handleConfirmSettlement = async (actualCash: number, inventoryJard: any[]) => {
    if (!selectedDriver) return;
    try {
      const token = localStorage.getItem('admin_token');
      const response = await fetch(`${import.meta.env.VITE_API_URL}/admin/sessions/${selectedDriver.session.session_id}/settle`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ actual_cash: actualCash, inventory_jard: inventoryJard })
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.message || 'فشل الاعتماد');
      }

      toast.success(`تم اعتماد تسوية ${selectedDriver.session.driver_name} وإغلاق العهدة بنجاح!`);
      setIsSettlementModalOpen(false);
      fetchLiveOperations();

    } catch (error: any) {
      toast.error(error.message);
    }
  };

  // دالة التراجع عن إنهاء العمل (تُستدعى بعد تأكيد المودال)
  const handleUndoEndWork = async () => {
    if (!undoSessionId) return;
    try {
      const token = localStorage.getItem('admin_token') || localStorage.getItem('token');
      const res = await fetch(`${import.meta.env.VITE_API_URL}/dispatch/session/${undoSessionId}/undo_end_work`, {
        method: "PUT",
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (res.ok) {
        toast.success("تم التراجع بنجاح. يمكن للمندوب متابعة عمله.");
        fetchLiveOperations();
      } else {
        const err = await res.json().catch(() => ({}));
        toast.error(err.message || "حدث خطأ أثناء التراجع.");
      }
    } catch {
      toast.error("خطأ في الاتصال بالسيرفر");
    } finally {
      setUndoSessionId(null);
    }
  };

  return (
    <div className="min-h-screen mesh-gradient-bg p-3 md:p-4 flex gap-4" dir="rtl">
      <OperationsSidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="flex-1 flex flex-col gap-4 min-w-0">

        <TopBar onMenuToggle={() => setSidebarOpen(true)} />

        <PulseBar
          totalCash={stats.totalCash}
          cashFromSales={stats.cashFromSales}
          cashFromDebts={stats.cashFromDebts}
          totalSoldCartons={stats.totalSoldCartons}
          completedVisits={stats.completedVisits}
          totalVisits={stats.totalVisits}
          activeDrivers={stats.activeDrivers}
          onBreakDrivers={stats.onBreakDrivers}
        />

        <div className="flex flex-col lg:flex-row gap-4 flex-1">
          <div className="lg:flex-[65] min-w-0">
            <FleetRadar
              drivers={drivers}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onToggleAuth={handleToggleAuth}
              searchQuery={searchQuery}
              onSearchChange={setSearchQuery}
            />
          </div>
          <div className="lg:flex-[35] min-w-0">
            <CommandCenter
              driver={selectedDriver}
              onApproveSettlement={() => setIsSettlementModalOpen(true)}
              onUndoEndWork={() => {
                if (!selectedDriver) return;
                setUndoSessionId(selectedDriver.session.session_id);
              }}
            />
          </div>
        </div>
      </main>

      <SettlementModal
        isOpen={isSettlementModalOpen}
        onClose={() => setIsSettlementModalOpen(false)}
        driver={selectedDriver}
        onConfirmSettlement={handleConfirmSettlement}
      />

      {/* ═══ Custom Undo Confirmation Modal ═══ */}
      {undoSessionId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
            onClick={() => setUndoSessionId(null)}
          />
          {/* Dialog */}
          <div className="relative z-10 w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            {/* Header */}
            <div className="flex items-center gap-3 px-6 pt-6 pb-4 border-b border-slate-100">
              <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-800">تأكيد إعادة فتح الجلسة</h2>
                <p className="text-xs text-slate-400 mt-0.5">هذا الإجراء يتطلب موافقة إدارية</p>
              </div>
            </div>
            {/* Body */}
            <div className="px-6 py-5">
              <p className="text-sm text-slate-600 leading-relaxed">
                هل أنت متأكد من <span className="font-bold text-amber-700">إعادة فتح الجلسة المالية</span> وإعادة المندوب لحالة نشط؟
              </p>
              <p className="text-xs text-red-500 mt-3 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                ⚠️ سيتمكن المندوب من مواصلة تسجيل المبيعات بعد هذا الإجراء.
              </p>
            </div>
            {/* Footer */}
            <div className="flex items-center gap-3 px-6 pb-6">
              <button
                onClick={() => setUndoSessionId(null)}
                className="flex-1 py-2.5 rounded-xl border border-slate-200 text-slate-600 text-sm font-bold hover:bg-slate-50 transition-all"
              >
                إلغاء
              </button>
              <button
                onClick={handleUndoEndWork}
                className="flex-1 py-2.5 rounded-xl bg-amber-500 text-white text-sm font-bold hover:bg-amber-600 transition-all shadow-lg shadow-amber-500/25 flex items-center justify-center gap-2"
              >
                <RotateCcw className="w-4 h-4" />
                نعم، إعادة الفتح
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Index;