import { Search, Satellite } from "lucide-react";
import { motion } from "framer-motion";
import type { DriverData } from "@/data/operations-data";

interface FleetRadarProps {
  drivers: DriverData[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onToggleAuth: (id: number) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
}

export function FleetRadar({ drivers, selectedId, onSelect, onToggleAuth, searchQuery, onSearchChange }: FleetRadarProps) {
  const filtered = drivers.filter((d) =>
    d.session.driver_name.includes(searchQuery)
  );

  return (
    <div className="glass-card rounded-2xl p-5 md:p-6 flex flex-col gap-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Satellite className="w-5 h-5 text-primary-foreground" strokeWidth={1.5} />
          <h2 className="text-base font-extrabold text-foreground">رادار الأسطول</h2>
        </div>
        <div className="relative flex-1 max-w-[220px]">
          <Search className="absolute top-1/2 -translate-y-1/2 end-3 w-4 h-4 text-muted-foreground" strokeWidth={1.5} />
          <input
            type="text"
            placeholder="بحث..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full bg-white/50 border border-white/60 rounded-full pe-9 ps-4 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 backdrop-blur-md"
          />
        </div>
      </div>

      {/* Driver rows */}
      <div className="flex flex-col gap-3 overflow-y-auto flex-1">
        {filtered.map((driver, i) => {
          const s = driver.session;
          const f = driver.settlement.financials;
          const isSelected = s.session_id === selectedId;

          return (
            <motion.div
              key={s.session_id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.06, duration: 0.35 }}
              onClick={() => onSelect(s.session_id)}
              className={`
                rounded-xl p-4 cursor-pointer transition-all duration-300
                ${isSelected
                  ? "bg-primary/15 border border-primary/30 shadow-sm -translate-y-0.5"
                  : "glass-row rounded-xl"
                }
              `}
            >
              <div className="flex items-center justify-between gap-3">
                {/* Avatar + Name + Status */}
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div className={`w-11 h-11 rounded-full flex items-center justify-center text-xl font-extrabold shrink-0 ${isSelected ? "bg-gradient-to-br from-primary to-warning text-primary-foreground shadow-command" : "bg-secondary text-foreground"
                    }`}>
                    {s.driver_name ? s.driver_name.charAt(0) : "م"}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-foreground truncate">{s.driver_name}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={`w-2 h-2 rounded-full ${driver.settlement.status === "في الطريق" ? "bg-success animate-pulse" :
                          driver.settlement.status === "استراحة" ? "bg-warning" :
                            driver.settlement.status === "مغلقة بانتظار التسوية" ? "bg-muted" :
                              "bg-destructive"
                        }`} />
                      <span className="text-[11px] text-muted-foreground">
                        {driver.settlement.status} {s.start_time ? `• ${new Date(s.start_time).toLocaleTimeString('ar-JO', { hour: '2-digit', minute: '2-digit' })}` : ""}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Cash badge */}
                <span className="bg-primary/15 text-primary-foreground text-xs font-bold tabular-nums rounded-full px-3 py-1 shrink-0">
                  {f.expected_cash_in_hand.toLocaleString("ar-JO")} د.أ
                </span>

                {/* Auth toggle */}
                <div className="flex flex-col items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => onToggleAuth(s.session_id)}
                    className={`relative w-11 h-6 rounded-full transition-colors duration-300 ${s.is_authorized_to_sell ? "bg-success" : "bg-muted"
                      }`}
                  >
                    <span
                      className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-md transition-all duration-300 ${s.is_authorized_to_sell ? "start-0.5" : "end-0.5"
                        }`}
                    />
                  </button>
                  <span className="text-[10px] text-muted-foreground">الضوء الأخضر</span>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
