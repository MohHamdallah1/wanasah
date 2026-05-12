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
      {/* +++ النسف المعماري للنواقص المخفية: جعل التنبيه Clickable لفلترة الجدول فوراً +++ */}
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

      <div className="glass-card overflow-hidden">
        {/* +++ إضافة شريط الأدوات (محرك البحث + وقت التحديث) +++ */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 px-5 py-4 border-b border-white/40 bg-slate-50/50">
          <div className="flex flex-col gap-1 w-full sm:w-auto">
            <h3 className="text-sm font-bold text-slate-700">الرصيد الحي ({displayedProducts.length} صنف)</h3>
            <span className="text-[10px] font-semibold text-slate-400">
              آخر تحديث: {lastSync.toLocaleTimeString("ar-EG")}
            </span>
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div className="relative flex-1 sm:w-64">
              <Search className="absolute end-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" strokeWidth={1.5} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ابحث عن صنف أو SKU..."
                className="w-full rounded-xl border border-slate-200 bg-white ps-3 pe-9 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-200"
              />
            </div>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-2 bg-white border border-slate-200 text-xs font-bold text-slate-600 rounded-xl hover:bg-slate-50 transition-colors shadow-sm disabled:opacity-50"
            >
              <RefreshCcw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              تحديث
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-100/50 border-b border-slate-200 text-right">
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المنتج</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500" title="الباركود أو المعرف الفريد للمنتج">رمز الصنف (SKU)</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">في المستودع</th>
                {/* +++ Tooltips لشرح المصطلحات للموظف +++ */}
                <th className="px-4 py-3 text-xs font-bold text-slate-500 cursor-help" title="البضاعة التي تم تعديلها للمندوب وبانتظار موافقته (تتصفر فور القبول وتنتقل لعهدته)">
                  <span className="flex items-center gap-1 border-b border-dashed border-slate-400 w-max">
                    قيد التحويل (بانتظار الموافقة) <Info className="w-3 h-3" />
                  </span>
                </th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500 cursor-help" title="إجمالي البضاعة الحالية داخل المستودع (المتاح للبيع + السيارات)">
                  <span className="flex items-center gap-1 border-b border-dashed border-slate-400 w-max">
                    إجمالي البضاعة (السيارات+المستودع) <Info className="w-3 h-3" />
                  </span>
                </th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500 cursor-help" title="التوالف والمرتجعات المعزولة في المستودع بانتظار الإتلاف">
                  <span className="flex items-center gap-1 border-b border-dashed border-slate-400 w-max">
                    التوالف بالفرع <Info className="w-3 h-3" />
                  </span>
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
                    className={`border-b border-slate-50 transition-colors ${isAlert
                      ? "bg-red-50/60 hover:bg-red-50"
                      : "hover:bg-white/80"
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