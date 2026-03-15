import { useState, useEffect } from "react";
import { getFleetStats } from "@/data/operations-data";
import type { DriverData } from "@/data/operations-data";
import { OperationsSidebar } from "@/components/operations/OperationsSidebar";
import { TopBar } from "@/components/operations/TopBar";
import { PulseBar } from "@/components/operations/PulseBar";
import { FleetRadar } from "@/components/operations/FleetRadar";
import { CommandCenter } from "@/components/operations/CommandCenter";

const Index = () => {
  const [drivers, setDrivers] = useState<DriverData[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchLiveOperations = async () => {
    try {
      const token = localStorage.getItem('admin_token');
      const response = await fetch('http://127.0.0.1:5000/admin/sessions/today', {
        method: 'GET',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}` // تمرير المفتاح هنا
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
    const driver = drivers.find((d) => d.session.session_id === id);
    if (!driver) return;
    const newAuthStatus = !driver.session.is_authorized_to_sell;
    
    setDrivers((prev) => prev.map((d) => d.session.session_id === id ? { ...d, session: { ...d.session, is_authorized_to_sell: newAuthStatus } } : d));

    try {
      const token = localStorage.getItem('admin_token');
      const response = await fetch(`http://127.0.0.1:5000/admin/sessions/${id}/authorize`, {
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

  // دالة زر اعتماد التسوية
  const handleApproveSettlement = async () => {
    if (!selectedDriver || selectedDriver.settlement.status !== "مغلقة بانتظار التسوية") return;
    
    try {
      const token = localStorage.getItem('admin_token');
      const response = await fetch(`http://127.0.0.1:5000/admin/sessions/${selectedDriver.session.session_id}/settle`, {
        method: 'PUT',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}` // تمرير المفتاح هنا
        }
      });
      
      if (!response.ok) {
         const errorData = await response.json();
         throw new Error(errorData.message || 'فشل الاعتماد');
      }
      
      alert(`تم اعتماد تسوية ${selectedDriver.session.driver_name} وإغلاق العهدة بنجاح!`);
      fetchLiveOperations(); 
      
    } catch (error: any) {
      alert(error.message);
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
              onApproveSettlement={handleApproveSettlement}
            />
          </div>
        </div>
      </main>
    </div>
  );
};

export default Index;