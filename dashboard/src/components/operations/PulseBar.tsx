import { Banknote, Package, Store, Users, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";

interface PulseBarProps {
  totalCash: number;
  cashFromSales: number;
  cashFromDebts: number;
  totalSoldCartons: number;
  completedVisits: number;
  totalVisits: number;
  activeDrivers: number;
  onBreakDrivers: number;
}

export function PulseBar({
  totalCash, cashFromSales, cashFromDebts,
  totalSoldCartons, completedVisits, totalVisits,
  activeDrivers, onBreakDrivers,
}: PulseBarProps) {
  const [refreshSpin, setRefreshSpin] = useState(false);
  const completionPct = totalVisits > 0 ? Math.round((completedVisits / totalVisits) * 100) : 0;

  const handleRefresh = () => {
    setRefreshSpin(true);
    setTimeout(() => setRefreshSpin(false), 600);
  };

  const cards = [
    {
      label: "الكاش الفعلي المُحصّل",
      value: totalCash.toLocaleString("ar-JO", { minimumFractionDigits: 0 }),
      unit: "د.أ",
      sub: `${cashFromSales.toLocaleString("ar-JO")} مبيعات + ${cashFromDebts.toLocaleString("ar-JO")} ذمم`,
      icon: Banknote,
      iconBg: "bg-primary/15",
      iconColor: "text-primary-foreground",
    },
    {
      label: "إجمالي المبيعات",
      value: totalSoldCartons.toLocaleString("ar-JO"),
      unit: "كرتونة",
      sub: null,
      icon: Package,
      iconBg: "bg-info/15",
      iconColor: "text-info",
    },
    {
      label: "إنجاز الأسطول",
      value: `${completedVisits}/${totalVisits}`,
      unit: "محل",
      sub: `${completionPct}%`,
      icon: Store,
      iconBg: "bg-success/15",
      iconColor: "text-success",
      progress: completionPct,
    },
    {
      label: "المناديب",
      value: null,
      sub: null,
      icon: Users,
      iconBg: "bg-warning/15",
      iconColor: "text-warning",
      custom: (
        <div className="flex items-center gap-4 mt-1">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-success animate-pulse" />
            <span className="text-2xl font-extrabold tabular-nums tracking-tight text-foreground">{activeDrivers}</span>
            <span className="text-xs text-muted-foreground">بالشارع</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-warning" />
            <span className="text-2xl font-extrabold tabular-nums tracking-tight text-foreground">{onBreakDrivers}</span>
            <span className="text-xs text-muted-foreground">استراحة</span>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card, i) => (
        <motion.div
          key={card.label}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.08, duration: 0.4 }}
          className="glass-card glass-card-hover rounded-2xl p-5 hover:scale-[1.02] transition-transform cursor-default"
        >
          <div className="flex items-start justify-between mb-3">
            <p className="text-xs font-medium text-muted-foreground">{card.label}</p>
            <div className="flex items-center gap-1.5">
              {i === 0 && (
                <button
                  onClick={handleRefresh}
                  className="w-7 h-7 rounded-lg bg-muted/60 flex items-center justify-center hover:bg-muted transition-colors"
                >
                  <RefreshCw
                    className={`w-3.5 h-3.5 text-muted-foreground transition-transform duration-500 ${refreshSpin ? "rotate-180" : ""}`}
                    strokeWidth={1.5}
                  />
                </button>
              )}
              <div className={`w-9 h-9 rounded-xl ${card.iconBg} flex items-center justify-center`}>
                <card.icon className={`w-[18px] h-[18px] ${card.iconColor}`} strokeWidth={1.5} />
              </div>
            </div>
          </div>
          {card.custom ? (
            card.custom
          ) : (
            <>
              <p className="text-3xl font-extrabold tabular-nums tracking-tight text-foreground">
                {card.value} <span className="text-sm font-bold text-muted-foreground">{card.unit}</span>
              </p>
              {card.sub && !card.progress && (
                <p className="text-xs text-muted-foreground mt-1">{card.sub}</p>
              )}
              {card.progress !== undefined && (
                <div className="mt-3">
                  <div className="w-full h-2 bg-primary/10 rounded-full overflow-hidden">
                    <motion.div
                      className="h-full bg-gradient-to-l from-primary to-warning rounded-full"
                      initial={{ width: 0 }}
                      animate={{ width: `${card.progress}%` }}
                      transition={{ duration: 1, ease: "easeOut" }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{card.sub} مكتمل</p>
                </div>
              )}
            </>
          )}
        </motion.div>
      ))}
    </div>
  );
}
