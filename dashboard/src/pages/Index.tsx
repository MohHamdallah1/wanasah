import { useState } from "react";
import { drivers as initialDrivers } from "@/data/dashboard-data";
import type { Driver } from "@/data/dashboard-data";
import { DriverSidebar } from "@/components/dashboard/DriverSidebar";
import { TopNav } from "@/components/dashboard/TopNav";
import { HeroSettlement } from "@/components/dashboard/HeroSettlement";
import { MetricCards } from "@/components/dashboard/MetricCards";
import { ActiveOperationsTable } from "@/components/dashboard/ActiveOperationsTable";

const Index = () => {
  const [selectedDriverId, setSelectedDriverId] = useState(initialDrivers[0].id);
  const [activeTab, setActiveTab] = useState("Dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [driverList, setDriverList] = useState<Driver[]>(initialDrivers);

  const selectedDriver = driverList.find((d) => d.id === selectedDriverId) ?? driverList[0];

  const handleToggleAuth = (id: string) => {
    setDriverList((prev) =>
      prev.map((d) => (d.id === id ? { ...d, authorized: !d.authorized } : d))
    );
  };

  return (
    <div className="min-h-screen bg-background p-3 md:p-4 flex gap-4">
      <DriverSidebar
        drivers={driverList}
        selectedId={selectedDriverId}
        onSelect={setSelectedDriverId}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <main className="flex-1 flex flex-col gap-5 min-w-0">
        <TopNav
          activeTab={activeTab}
          onTabChange={setActiveTab}
          onMenuToggle={() => setSidebarOpen(true)}
        />
        <MetricCards />

        {/* Section B + C */}
        <div className="flex flex-col lg:flex-row gap-5">
          <div className="lg:flex-[2] min-w-0">
            <ActiveOperationsTable
              drivers={driverList}
              selectedId={selectedDriverId}
              onSelect={setSelectedDriverId}
              onToggleAuth={handleToggleAuth}
            />
          </div>
          <div className="lg:flex-1 min-w-0">
            <HeroSettlement driver={selectedDriver} />
          </div>
        </div>
      </main>
    </div>
  );
};

export default Index;
