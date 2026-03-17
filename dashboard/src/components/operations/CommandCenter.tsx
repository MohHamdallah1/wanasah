import { Radar, StopCircle, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { DriverData } from "@/data/operations-data";

interface CommandCenterProps {
  driver: DriverData | null;
  onApproveSettlement: () => void;
}

export function CommandCenter({ driver, onApproveSettlement }: CommandCenterProps) {
  const canApprove = driver?.settlement.status === "مغلقة بانتظار التسوية";

  return (
    <div className="relative bg-gradient-to-br from-[hsl(43,100%,50%)] to-[hsl(30,100%,50%)] text-foreground rounded-3xl p-6 md:p-8 shadow-command overflow-hidden flex flex-col gap-5 min-h-[420px] command-glossy">

      <AnimatePresence mode="wait">
        {!driver ? (
          /* Empty state */
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex-1 flex flex-col items-center justify-center gap-4 relative z-10"
          >
            <Radar className="w-16 h-16 text-foreground/40 animate-pulse" strokeWidth={1} />
            <p className="text-base font-bold text-foreground/60 text-center">اختر مندوباً لعرض التفاصيل</p>
          </motion.div>
        ) : (
          <motion.div
            key={driver.session.session_id}
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.3 }}
            className="flex flex-col gap-5 relative z-10 flex-1"
          >
            {/* Header */}
            <div className="flex items-center gap-3">
              <div className="w-14 h-14 rounded-full bg-nav-dark text-nav-dark-foreground flex items-center justify-center font-extrabold text-2xl shadow-lg">
                {driver.session.driver_name ? driver.session.driver_name.charAt(0) : "م"}
              </div>
              <div>
                <p className="text-lg font-extrabold">{driver.session.driver_name}</p>
                <span className={`inline-block text-xs font-bold rounded-full px-3 py-1 mt-0.5 ${driver.settlement.status === "مغلقة بانتظار التسوية"
                    ? "bg-info/20 text-info"
                    : driver.settlement.status === "استراحة"
                      ? "bg-warning/30 text-foreground"
                      : "bg-success/20 text-success"
                  }`}>
                  {driver.settlement.status}
                </span>
              </div>
            </div>

            {/* Financials */}
            <div className="flex flex-col gap-1">
              <p className="text-xs font-bold text-foreground/50 uppercase tracking-wider">الإجمالي المطلوب تسليمه</p>
              <p className="text-5xl font-extrabold tabular-nums tracking-tight leading-none">
                {driver.settlement.financials.expected_cash_in_hand.toLocaleString("ar-JO", { minimumFractionDigits: 2 })}
                <span className="text-xl font-bold ms-2">د.أ</span>
              </p>
              <div className="flex gap-4 mt-2 text-sm">
                <span className="text-foreground/70">
                  مبيعات: <span className="font-bold tabular-nums">{driver.settlement.financials.cash_from_sales.toLocaleString("ar-JO")}</span>
                </span>
                <span className="text-foreground/70">
                  ذمم: <span className="font-bold tabular-nums">{driver.settlement.financials.cash_from_debts.toLocaleString("ar-JO")}</span>
                </span>
              </div>
            </div>

            {/* Inventory */}
            <div className="bg-white/20 backdrop-blur-sm rounded-xl p-4">
              <p className="text-xs font-bold text-foreground/60 mb-2">المخزون</p>
              <div className="flex flex-col gap-1.5">
                {driver.settlement.inventory.map((item) => (
                  <div key={item.product_id} className="flex items-center justify-between text-xs border-b border-white/10 pb-1.5 last:border-0">
                    <span className="font-medium">{item.product_name}</span>
                    <span className="tabular-nums font-bold text-foreground/70">
                      {item.starting_quantity} ← {item.sold_quantity} بيع ← <span className="text-foreground font-extrabold">{item.remaining_quantity} متبقي</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Visits */}
            <div className="flex gap-3 text-xs">
              <span className="bg-white/20 backdrop-blur-sm rounded-lg px-3 py-2 font-bold tabular-nums">
                ✅ {driver.settlement.visits.completed_total} زيارة مكتملة
              </span>
              <span className="bg-white/20 backdrop-blur-sm rounded-lg px-3 py-2 font-bold tabular-nums">
                ⏳ {driver.settlement.visits.pending_remaining} متبقية
              </span>
            </div>

            {/* Actions */}
            <div className="mt-auto flex flex-col gap-2">
              <button
                onClick={onApproveSettlement}
                disabled={!canApprove}
                className={`flex items-center justify-center gap-2 w-full bg-nav-dark text-nav-dark-foreground rounded-xl h-14 text-sm font-bold transition-all ${canApprove
                    ? "hover:opacity-90 cursor-pointer shadow-lg"
                    : "opacity-50 cursor-not-allowed grayscale pointer-events-none"
                  }`}
              >
                <CheckCircle2 className="w-5 h-5" strokeWidth={1.5} />
                اعتماد التسوية وإغلاق العهدة
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
