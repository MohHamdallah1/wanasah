import { Banknote, Users, MapPin, Clock } from "lucide-react";
import { fleetStats } from "@/data/dashboard-data";

export function MetricCards() {
  const metrics = [
    {
      label: "Total Expected Cash",
      value: `${fleetStats.totalFleetCash.toFixed(0)} JOD`,
      subtitle: `across ${fleetStats.activeDrivers} active drivers`,
      icon: Banknote,
      accent: "bg-primary/20 text-primary-foreground",
    },
    {
      label: "Active Drivers",
      value: fleetStats.activeDrivers,
      subtitle: `of ${fleetStats.totalDrivers} total`,
      icon: Users,
      accent: "bg-info/10 text-info",
    },
    {
      label: "Completed Visits",
      value: fleetStats.totalCompletedVisits,
      subtitle: "visits done today",
      icon: MapPin,
      accent: "bg-success/10 text-success",
    },
    {
      label: "Pending Visits",
      value: fleetStats.totalPendingVisits,
      subtitle: "remaining today",
      icon: Clock,
      accent: "bg-warning/10 text-warning",
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 animate-fade-in">
      {metrics.map((m) => (
        <div
          key={m.label}
          className="bg-card rounded-3xl shadow-card p-5 md:p-6 flex flex-col gap-4 hover:shadow-card-hover transition-shadow duration-300"
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">{m.label}</span>
            <div className={`w-9 h-9 rounded-2xl flex items-center justify-center shrink-0 ${m.accent}`}>
              <m.icon className="w-4 h-4" />
            </div>
          </div>
          <div>
            <p className="text-2xl md:text-3xl font-bold text-foreground">{m.value}</p>
            <p className="text-xs text-muted-foreground mt-1">{m.subtitle}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
