import type { Driver } from "@/data/dashboard-data";

interface ActiveOperationsTableProps {
  drivers: Driver[];
  selectedId: string;
  onSelect: (id: string) => void;
  onToggleAuth: (id: string) => void;
}

const statusBadge: Record<Driver["status"], { bg: string; label: string }> = {
  "On Route": { bg: "bg-success/15 text-success", label: "On Route" },
  Returning: { bg: "bg-info/15 text-info", label: "Pending Settlement" },
  "At Depot": { bg: "bg-warning/15 text-warning", label: "On Break" },
};

export function ActiveOperationsTable({ drivers, selectedId, onSelect, onToggleAuth }: ActiveOperationsTableProps) {
  return (
    <div className="bg-card rounded-3xl shadow-card p-5 md:p-6 animate-fade-in flex flex-col gap-4">
      <h2 className="text-base font-semibold text-foreground">Active Operations</h2>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider">
              <th className="pb-3 font-medium">Driver</th>
              <th className="pb-3 font-medium">Start Time</th>
              <th className="pb-3 font-medium">Status</th>
              <th className="pb-3 font-medium text-right">Authorize Sales</th>
            </tr>
          </thead>
          <tbody>
            {drivers.map((driver) => {
              const badge = statusBadge[driver.status];
              const isSelected = driver.id === selectedId;
              return (
                <tr
                  key={driver.id}
                  onClick={() => onSelect(driver.id)}
                  className={`border-t border-border cursor-pointer transition-colors ${
                    isSelected ? "bg-primary/10" : "hover:bg-muted/50"
                  }`}
                >
                  <td className="py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-secondary flex items-center justify-center text-xs font-bold text-foreground shrink-0">
                        {driver.avatar}
                      </div>
                      <div>
                        <p className="font-semibold text-foreground">{driver.name}</p>
                        <p className="text-xs text-muted-foreground">{driver.route}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-4 text-muted-foreground">{driver.startTime}</td>
                  <td className="py-4">
                    <span className={`inline-block text-xs font-semibold rounded-full px-3 py-1 ${badge.bg}`}>
                      {badge.label}
                    </span>
                  </td>
                  <td className="py-4 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleAuth(driver.id);
                      }}
                      className={`inline-flex items-center gap-2 text-xs font-semibold rounded-full px-4 py-2 transition-colors ${
                        driver.authorized
                          ? "bg-success/15 text-success"
                          : "bg-muted text-muted-foreground hover:bg-warning/15 hover:text-warning"
                      }`}
                    >
                      <span className={`w-2 h-2 rounded-full ${driver.authorized ? "bg-success" : "bg-muted-foreground"}`} />
                      {driver.authorized ? "Authorized" : "Authorize"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden flex flex-col gap-3">
        {drivers.map((driver) => {
          const badge = statusBadge[driver.status];
          const isSelected = driver.id === selectedId;
          return (
            <div
              key={driver.id}
              onClick={() => onSelect(driver.id)}
              className={`rounded-2xl p-4 border transition-colors cursor-pointer ${
                isSelected ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full bg-secondary flex items-center justify-center text-xs font-bold text-foreground">
                    {driver.avatar}
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">{driver.name}</p>
                    <p className="text-xs text-muted-foreground">{driver.startTime} • {driver.route}</p>
                  </div>
                </div>
                <span className={`text-[11px] font-semibold rounded-full px-2.5 py-1 ${badge.bg}`}>
                  {badge.label}
                </span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onToggleAuth(driver.id);
                }}
                className={`w-full text-xs font-semibold rounded-full px-4 py-2 transition-colors ${
                  driver.authorized
                    ? "bg-success/15 text-success"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                <span className={`inline-block w-2 h-2 rounded-full mr-2 ${driver.authorized ? "bg-success" : "bg-muted-foreground"}`} />
                {driver.authorized ? "Authorized" : "Authorize Sales"}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
