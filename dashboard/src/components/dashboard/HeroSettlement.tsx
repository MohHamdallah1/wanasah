import { CheckCircle } from "lucide-react";
// تم إزالة الاستيراد القديم لـ DriverData لأنه لا يحتوي على الحقول الجديدة من السيرفر

interface HeroSettlementProps {
  driver: any | null; // +++ درع التجاوز: السماح باستقبال كائن السيرفر الديناميكي (ActiveSessionResponse) بالكامل +++
}

export function HeroSettlement({ driver }: HeroSettlementProps) {
  if (!driver) return null;

  const GLOBAL_CURRENCY = "د.أ";
  const formatMoney = (val: number) => parseFloat(Number(val).toFixed(2)).toLocaleString('en-US');

  const s = driver.session;
  const f = driver.financials;
  const inventory = driver.settlement?.inventory || [];

  return (
    <div className="bg-white rounded-3xl shadow-xl border border-slate-100 p-6 md:p-8 flex flex-col gap-6 animate-in zoom-in-95 duration-300">
      
      {/* Driver info (Clean Header) */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full bg-slate-50 border border-slate-200 text-slate-700 flex items-center justify-center font-black text-lg shadow-sm">
          {s.driver_name.substring(0, 2).toUpperCase()}
        </div>
        <div>
          <p className="text-lg font-black text-slate-800">{s.driver_name}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">{s.vehicle_label}</span>
            <span className="text-xs font-bold text-emerald-600 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-md">{driver.settlement.status}</span>
          </div>
        </div>
      </div>

      {/* Financial breakdown (Modern Layout) */}
      <div className="bg-slate-50 rounded-2xl p-5 border border-slate-100 flex flex-col gap-3">
        <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1">الخلاصة المالية</p>
        <div className="flex justify-between items-center text-sm">
          <span className="text-slate-600 font-semibold">مبيعات نقدية</span>
          <span className="font-bold text-slate-800">{formatMoney(f.cash_from_sales)} {GLOBAL_CURRENCY}</span>
        </div>
        <div className="flex justify-between items-center text-sm">
          <span className="text-slate-600 font-semibold">تحصيل ذمم</span>
          <span className="font-bold text-slate-800">{formatMoney(f.cash_from_debts)} {GLOBAL_CURRENCY}</span>
        </div>
        <div className="h-px bg-slate-200 my-2" />
        <div className="flex justify-between items-end">
          <p className="text-xs font-bold text-slate-500">إجمالي النقد المتوقع</p>
          <p className="text-3xl md:text-4xl font-black text-emerald-600 tracking-tight">
            {formatMoney(f.expected_cash_in_hand)} <span className="text-base font-bold text-emerald-700">{GLOBAL_CURRENCY}</span>
          </p>
        </div>
      </div>

      {/* Smart Inventory Section (Cartons + Loose) */}
      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">تفاصيل المخزون (كرتونة وفرط)</p>
        
        {inventory.length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-4 bg-slate-50 rounded-xl border border-slate-100 font-medium">لا يوجد بضاعة محملة</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[220px] overflow-y-auto custom-scrollbar pr-2">
            {inventory.map((item: any, idx: number) => {
              const ppc = item.packs_per_carton || 1;
              const soldCartons = Math.floor((item.sold_quantity || 0) / ppc);
              const soldLoose = (item.sold_quantity || 0) % ppc;
              const remainCartons = Math.floor((item.current_quantity || 0) / ppc);
              const remainLoose = (item.current_quantity || 0) % ppc;
              
              return (
                <div key={idx} className="bg-white border border-slate-200 hover:border-blue-300 transition-colors rounded-xl p-3 flex flex-col gap-2 shadow-sm">
                  <p className="text-sm font-bold text-slate-700 truncate" title={item.product_name}>{item.product_name}</p>
                  <div className="flex gap-2">
                    <div className="flex-1 bg-slate-50 rounded-lg p-2 flex flex-col items-center border border-slate-100">
                      <span className="text-[10px] text-slate-400 font-bold mb-1">المبيع</span>
                      <span className="text-xs font-black text-slate-700">{soldCartons}ك {soldLoose > 0 ? `+ ${soldLoose}ح` : ''}</span>
                    </div>
                    <div className="flex-1 bg-blue-50/50 rounded-lg p-2 flex flex-col items-center border border-blue-100">
                      <span className="text-[10px] text-blue-400 font-bold mb-1">الباقي</span>
                      <span className="text-xs font-black text-blue-700">{remainCartons}ك {remainLoose > 0 ? `+ ${remainLoose}ح` : ''}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}