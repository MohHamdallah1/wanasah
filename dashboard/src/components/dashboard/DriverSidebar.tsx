import { Truck, LayoutDashboard, Users, Package, FileText, X } from "lucide-react";
import type { Driver } from "@/data/dashboard-data";

interface DriverSidebarProps {
  drivers: Driver[];
  selectedId: string;
  onSelect: (id: string) => void;
  open?: boolean;
  onClose?: () => void;
}

const navLinks = [
  { label: "Dashboard", icon: LayoutDashboard, active: true },
  { label: "Drivers", icon: Users, active: false },
  { label: "Inventory", icon: Package, active: false },
  { label: "Settlements", icon: FileText, active: false },
];

const statusColor: Record<Driver["status"], string> = {
  "On Route": "bg-success text-success-foreground",
  Returning: "bg-warning text-warning-foreground",
  "At Depot": "bg-muted text-muted-foreground",
};

export function DriverSidebar({ drivers, selectedId, onSelect, open, onClose }: DriverSidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div className="fixed inset-0 z-40 bg-foreground/20 md:hidden" onClick={onClose} />
      )}

      <aside
        className={`
          fixed inset-y-0 left-0 z-50 w-80 bg-card rounded-r-3xl shadow-card p-6 flex flex-col gap-5 transition-transform duration-300
          md:static md:rounded-3xl md:translate-x-0 md:z-auto
          ${open ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        {/* Logo + close */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-primary flex items-center justify-center">
              <Truck className="w-5 h-5 text-primary-foreground" />
            </div>
            <span className="text-lg font-bold text-foreground tracking-tight">Wanasah Admin</span>
          </div>
          <button onClick={onClose} className="md:hidden w-8 h-8 rounded-full bg-muted flex items-center justify-center">
            <X className="w-4 h-4 text-muted-foreground" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex flex-col gap-1">
          {navLinks.map((link) => (
            <button
              key={link.label}
              className={`flex items-center gap-3 px-4 py-3 rounded-2xl text-sm font-medium transition-colors ${
                link.active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`}
            >
              <link.icon className="w-4 h-4" />
              {link.label}
            </button>
          ))}
        </nav>

        {/* Divider */}
        <div className="h-px bg-border" />

        {/* Section header */}
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Active Drivers</h2>
          <span className="text-xs font-medium text-muted-foreground bg-muted rounded-full px-3 py-1">
            {drivers.length}
          </span>
        </div>

        {/* Driver list */}
        <div className="flex flex-col gap-2 overflow-y-auto flex-1">
          {drivers.map((driver) => {
            const isActive = driver.id === selectedId;
            return (
              <button
                key={driver.id}
                onClick={() => {
                  onSelect(driver.id);
                  onClose?.();
                }}
                className={`w-full text-left rounded-2xl p-4 transition-all duration-200 ${
                  isActive
                    ? "bg-primary shadow-card-hover scale-[1.02]"
                    : "bg-card hover:bg-muted/60"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${
                      isActive
                        ? "bg-nav-dark text-nav-dark-foreground"
                        : "bg-secondary text-foreground"
                    }`}
                  >
                    {driver.avatar}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-semibold truncate ${isActive ? "text-primary-foreground" : "text-foreground"}`}>
                      {driver.name}
                    </p>
                    <span
                      className={`inline-block text-[11px] font-medium rounded-full px-2 py-0.5 mt-1 ${
                        isActive ? "bg-nav-dark/20 text-primary-foreground" : statusColor[driver.status]
                      }`}
                    >
                      {driver.status}
                    </span>
                  </div>
                </div>
                <p className={`text-xs mt-2 ${isActive ? "text-primary-foreground/70" : "text-muted-foreground"}`}>
                  Route: {driver.route}
                </p>
              </button>
            );
          })}
        </div>
      </aside>
    </>
  );
}
