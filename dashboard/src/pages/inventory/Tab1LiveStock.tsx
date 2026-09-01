import { useState, useMemo, useEffect } from "react";
import { AlertTriangle, RefreshCcw, Search, Info, FilterX } from "lucide-react";
import type { WarehouseProduct, WarehouseAlert } from "./inventoryUtils";
import { formatQty } from "./inventoryUtils";

interface Props {
  products: WarehouseProduct[];
  alerts: WarehouseAlert[];
  loading: boolean;
  onRefresh: () => void;
}

export function Tab1LiveStock({ products, alerts, loading, onRefresh }: Props) {
  // +++ الأداء الإيليت: Cache لمعرفات النواقص +++
  const alertIds = useMemo(() => new Set(alerts.map((a) => a.product_variant_id)), [alerts]);

  // +++ إضافة محرك البحث والفلترة الذكية +++
  const [search, setSearch] = useState("");
  const [showOnlyAlerts, setShowOnlyAlerts] = useState(false);

  // +++ إضافة "طابع الزمن" (Timestamp) لمنع خداع المدير ببيانات بايتة +++
  const [lastSync, setLastSync] = useState<Date>(new Date());

  useEffect(() => {
    if (!loading && products.length > 0) {
      setLastSync(new Date());
    }
  }, [products, loading]);
  // +++ درع الحماية: إنهاء حالة "الجدول الميت" تلقائياً إذا اختفت النواقص +++
  useEffect(() => {
    if (alerts.length === 0 && showOnlyAlerts) {
      setShowOnlyAlerts(false);
    }
  }, [alerts.length, showOnlyAlerts]);

  // +++ فلترة الجدول بناءً على البحث وزر النواقص +++
  const displayedProducts = useMemo(() => {
    return products.filter(p => {
      const matchesSearch = p.name.toLowerCase().includes(search.toLowerCase()) || (p.sku && p.sku.toLowerCase().includes(search.toLowerCase()));
      const matchesAlert = showOnlyAlerts ? alertIds.has(p.id) : true;
      return matchesSearch && matchesAlert;
    });
  }, [products, search, showOnlyAlerts, alertIds]);

  return (
    <div className="flex flex-col gap-4">
      {/* +++  للنواقص المخفية: جعل التنبيه Clickable لفلترة الجدول فوراً +++ */}
      {alerts.length > 0 && (
        <div
          onClick={() => setShowOnlyAlerts(!showOnlyAlerts)}
          className={`flex flex-col sm:flex-row items-start gap-3 border rounded-2xl px-4 py-3 w-full cursor-pointer transition-all shadow-sm ${showOnlyAlerts ? "bg-red-100 border-red-400" : "bg-red-50 border-red-200 hover:bg-red-100 pulse-border-red"
            }`}
          title="اضغط هنا لفلترة الجدول وعرض النواقص فقط"
        >
          <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${showOnlyAlerts ? "text-red-600" : "text-red-500"}`} />
          <div className="flex-1 min-w-0 flex justify-between items-center">
            <div>
              <p className="text-sm font-bold text-red-700">
                تحذير: {alerts.length} صنف وصل للحد الأدنى
              </p>
              <p className="text-xs text-red-500 mt-0.5">
                {showOnlyAlerts
                  ? "تمت تصفية الجدول لعرض هذه الأصناف بالأسفل ↓"
                  : `(اضغط هنا لعرضها بالجدول) منها: ${alerts.slice(0, 3).map((a) => a.product_name).join(" • ")}${alerts.length > 3 ? "..." : ""}`}
              </p>
            </div>
            {showOnlyAlerts && (
              <FilterX className="w-5 h-5 text-red-500 opacity-70" />
            )}
          </div>
        </div>
      )}

      <div className="glass-card overflow-hidden pt-0">
        {/* +++ تم إعدام الـ div الفارغ الذي كان يسبب المساحة البرتقالية العلوية +++ */}

        {/* +++ الكي الجراحي: استخدام h الثابت بدلاً من max-h لإجبار الجدول على التمدد للأسفل ليطابق القائمة الجانبية +++ */}
        <div className={`h-[82vh] overflow-y-auto overflow-x-auto custom-scrollbar transition-all duration-300 ${loading ? "opacity-50 pointer-events-none select-none grayscale-[20%]" : "opacity-100"}`}>
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur shadow-sm border-b border-slate-200 text-right">
              <tr>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 w-1/3 min-w-[250px] align-middle">
                  <div className="flex items-center gap-3">
                    <span>المنتج</span>
                    <div className="relative font-normal flex-1">
                      <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        type="search"
                        placeholder="ابحث عن صنف أو SKU..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-4 pr-9 py-2 text-xs border border-slate-200 rounded-lg outline-none focus:border-[#1e87bb] bg-white transition-all shadow-sm"
                      />
                    </div>
                  </div>
                </th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">رمز الصنف (SKU)</th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">في المستودع</th>
                
                {/* +++ تولتيب صاروخي: (hidden group-hover:block) لظهور فوري بدون أي تأخير، وتوجيه للأسفل (top-full mt-2) +++ */}
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    قيد التحويل <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      البضاعة التي تم تعديلها للمندوب وبانتظار موافقته
                    </div>
                  </div>
                </th>
                
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    إجمالي البضاعة <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      إجمالي البضاعة الحالية داخل المستودع (المتاح للبيع + السيارات)
                    </div>
                  </div>
                </th>
                
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    التوالف بالفرع <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      التوالف والمرتجعات المعزولة في المستودع بانتظار الإتلاف
                    </div>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {displayedProducts.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-center py-12 text-slate-400 text-sm">
                    {loading ? "جارٍ التحميل..." : "لا توجد بيانات مطابقة"}
                  </td>
                </tr>
              )}
              {displayedProducts.map((p) => {
                const isAlert = alertIds.has(p.id);
                return (
                  <tr
                    key={p.id}
                    /* +++ الكي الجراحي: فصل بخط slate-100/80 فائق النعومة، وإضاءة الصف تلقائياً عند مرور الماوس +++ */
                    className={`border-b border-slate-100/80 transition-all duration-200 ${isAlert
                      ? "bg-red-50/50 hover:bg-red-50/80"
                      : "bg-white hover:bg-slate-50/60"
                      }`}
                  >
                    <td className="px-4 py-3 font-semibold text-slate-800 flex items-center gap-2">
                      {isAlert && (
                        <span title="وصل للحد الأدنى">
                          <AlertTriangle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                        </span>
                      )}
                      {p.name}
                    </td>
                    <td className="px-4 py-3 text-slate-500 font-mono text-xs">{p.sku || "—"}</td>
                    <td className="px-4 py-3 text-emerald-700 font-semibold">
                      {formatQty(p.available_packs, p.packs_per_carton)}
                    </td>
                    <td className="px-4 py-3 text-violet-600 font-semibold">
                      {formatQty(p.reserved_packs, p.packs_per_carton)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">
                      {formatQty(p.total_packs, p.packs_per_carton)}
                    </td>
                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">
                      {formatQty(p.damaged_packs || 0, p.packs_per_carton)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}