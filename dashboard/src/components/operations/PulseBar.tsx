import { Banknote, Package, Store, Users, RefreshCw, Eye } from "lucide-react";
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
  onOpenSalesDetails?: () => void;
}

export function PulseBar({
  totalCash, cashFromSales, cashFromDebts,
  totalSoldCartons, completedVisits, totalVisits,
  activeDrivers, onBreakDrivers, onOpenSalesDetails,
}: PulseBarProps) {
  const [refreshSpin, setRefreshSpin] = useState(false);
  const completionPct = totalVisits > 0 ? Math.round((completedVisits / totalVisits) * 100) : 0;

  const handleRefresh = () => {
    setRefreshSpin(true);
    setTimeout(() => setRefreshSpin(false), 600);
  };

  // +++ المحركات اللغوية والرياضية الذكية +++
  const GLOBAL_CURRENCY = "د.أ"; 
  const formatMoney = (val: number) => parseFloat(Number(val).toFixed(2)).toLocaleString('en-US');
  
  const getCartonWord = (n: number) => {
    if (n === 1) return "كرتونة";
    if (n === 2) return "كرتونتان";
    if (n >= 3 && n <= 10) return "كراتين";
    return "كرتونة";
  };

  const getShopWord = (n: number) => {
    if (n === 1) return "محل";
    if (n === 2) return "محلان";
    if (n >= 3 && n <= 10) return "محلات";
    return "محلاً";
  };

  const cards = [
    {
      label: "الكاش الفعلي المُحصّل",
      // +++ فرمتة احترافية بدون أصفار زائدة مع عملة ديناميكية +++
      value: formatMoney(totalCash),
      unit: GLOBAL_CURRENCY,
      sub: `${formatMoney(cashFromSales)} مبيعات | ${formatMoney(cashFromDebts)} ذمم`,
      icon: Banknote,
      iconColor: "text-emerald-600",
      iconBg: "bg-emerald-100",
      delay: 0,
    },
    {
      label: "إجمالي المبيعات اللوجستية",
      value: totalSoldCartons,
      // +++ ذكاء لغوي للكراتين +++
      unit: getCartonWord(totalSoldCartons),
      sub: "تم تسليمها اليوم للمحلات",
      icon: Package,
      iconColor: "text-blue-600",
      iconBg: "bg-blue-100",
      delay: 0.1,
    },
    {
      label: "إنجاز الأسطول",
      value: completedVisits,
      // +++ ذكاء لغوي للمحلات +++
      unit: getShopWord(completedVisits),
      sub: `${completionPct}%`,
      icon: Store,
      iconColor: "text-violet-600",
      iconBg: "bg-violet-100",
      progress: completionPct,
      delay: 0.2,
    },
    {
      label: "المناديب",
      value: null,
      sub: null,
      icon: Users,
      iconBg: "bg-warning/15",
      iconColor: "text-warning",
      custom: (
        <div className="flex items-center gap-6 mt-2">
          <div className="flex flex-col">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse" />
              <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">بالشارع</span>
            </div>
            <span className="text-3xl font-black tabular-nums tracking-tighter text-slate-800 leading-none">{activeDrivers}</span>
          </div>
          <div className="w-px h-10 bg-slate-100" />
          <div className="flex flex-col">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]" />
              <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">استراحة</span>
            </div>
            <span className="text-3xl font-black tabular-nums tracking-tighter text-slate-800 leading-none">{onBreakDrivers}</span>
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
      {cards.map((card, i) => (
        <div
          key={card.label}
          // تغيير حجم البطاقات من اخر جملة 
          className="group relative overflow-hidden bg-white rounded-[24px] p-6 ring-1 ring-slate-900/5 shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-[0_20px_40px_rgb(0,0,0,0.08)] hover:-translate-y-1 transition-all duration-500 cursor-default flex flex-col justify-between h-[150px]"
        >
          {/* +++ توهج خلفي ناعم (Mesh Gradient Glow) يعكس لون الأيقونة +++ */}
          <div className={`absolute -top-20 -end-20 w-40 h-40 rounded-full blur-[50px] opacity-40 group-hover:opacity-70 transition-opacity duration-700 pointer-events-none ${card.iconBg}`} />
          
          <div className="relative z-10 flex items-start justify-between mb-4">
            <p className="text-[13px] font-extrabold text-slate-500/90 tracking-wide">{card.label}</p>
            
            <div className="flex items-center gap-2">
              {/* +++ أزرار شبحية (تظهر فقط عند مرور الماوس وتنزلق للداخل) +++ */}
              {i === 0 && (
                <button
                  onClick={handleRefresh}
                  className="w-8 h-8 rounded-full bg-slate-50/80 backdrop-blur-sm border border-slate-200/50 flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-slate-100 transition-all duration-300 shadow-sm translate-x-3 group-hover:translate-x-0"
                  title="تحديث البيانات"
                >
                  <RefreshCw
                    className={`w-4 h-4 text-slate-600 ${refreshSpin ? "animate-spin" : ""}`}
                    strokeWidth={2.5}
                  />
                </button>
              )}
              {i === 1 && onOpenSalesDetails && (
                <button
                  onClick={onOpenSalesDetails}
                  className="w-8 h-8 rounded-full bg-slate-50/80 backdrop-blur-sm border border-slate-200/50 flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-blue-50 hover:text-blue-600 hover:border-blue-200 transition-all duration-300 shadow-sm translate-x-3 group-hover:translate-x-0"
                  title="عرض تفاصيل المبيعات"
                >
                  <Eye className="w-4 h-4 text-slate-600 hover:text-blue-600" strokeWidth={2.5} />
                </button>
              )}
              
              {/* +++ أيقونة زجاجية (Frosted Glass Badge) +++ */}
              <div className={`w-10 h-10 rounded-[14px] ${card.iconBg} bg-opacity-40 backdrop-blur-md border border-white/60 shadow-sm flex items-center justify-center relative`}>
                <card.icon className={`w-5 h-5 ${card.iconColor}`} strokeWidth={2.2} />
              </div>
            </div>
          </div>

          <div className="relative z-10">
            {card.custom ? (
              card.custom
            ) : (
              <>
                <div className="flex items-baseline gap-1.5 mt-1">
                  <p className="text-4xl font-black tabular-nums tracking-tighter text-slate-800 leading-none drop-shadow-sm">
                    {card.value}
                  </p>
                  <span className="text-sm font-bold text-slate-400">{card.unit}</span>
                </div>
                
                {card.sub && !card.progress && (
                  <p className="text-[11px] font-extrabold text-slate-400/80 mt-2 truncate uppercase tracking-wider">{card.sub}</p>
                )}
                
                {card.progress !== undefined && (
                  <div className="mt-3.5 flex flex-col gap-1.5">
                    <div className="flex justify-between items-center text-[10px] font-black text-slate-400 uppercase tracking-widest">
                      <span>التقدم اللوجستي</span>
                      <span className="text-violet-600 drop-shadow-sm">{card.sub}</span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden shadow-inner">
                      <div
                        className="h-full bg-gradient-to-l from-violet-500 to-indigo-400 rounded-full transition-all duration-1000 ease-out"
                        style={{ width: `${card.progress}%` }}
                      />
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
