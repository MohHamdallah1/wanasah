import { useState, useEffect } from "react";
import { AlertTriangle, RefreshCcw, Search, Info, FilterX, ChevronRight, ChevronLeft } from "lucide-react";
import type { WarehouseProduct } from "./liveStock/contracts";
import { compareQuantity, formatCommercialQuantity } from "./quantity";
import { useTranslation } from "react-i18next";

interface Props {
  locationId: number;
  products: WarehouseProduct[];
  loading: boolean;
  alertCount: number;
  alertSamples: string[];
  matchingTotal: number | null;
  pageNumber: number;
  hasMore: boolean;
  hasPrevious: boolean;
  onlyAlerts: boolean;
  lastSync: Date | null;
  onSearchChange: (search: string) => void;
  onOnlyAlertsChange: (onlyAlerts: boolean) => void;
  onNext: () => void;
  onPrevious: () => void;
  onRefresh: () => void;
}

export function Tab1LiveStock({
  locationId,
  products,
  loading,
  alertCount,
  alertSamples,
  matchingTotal,
  pageNumber,
  hasMore,
  hasPrevious,
  onlyAlerts,
  lastSync,
  onSearchChange,
  onOnlyAlertsChange,
  onNext,
  onPrevious,
  onRefresh,
}: Props) {
  const { t, i18n } = useTranslation();
  const [searchInput, setSearchInput] = useState("");

  const formatMoney = (value: string, currency: string) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return value;
    try {
      return new Intl.NumberFormat(
        i18n.language.startsWith("ar") ? "ar-JO" : "en-US",
        {
          style: "currency",
          currency,
          minimumFractionDigits: 3,
          maximumFractionDigits: 6,
        },
      ).format(numeric);
    } catch {
      return value;
    }
  };

  useEffect(() => {
    setSearchInput("");
  }, [locationId]);

  useEffect(() => {
    const handler = window.setTimeout(() => {
      const clean = searchInput.trim();
      onSearchChange(clean.length >= 2 ? clean : "");
    }, 300);
    return () => window.clearTimeout(handler);
  }, [searchInput, onSearchChange]);

  useEffect(() => {
    if (alertCount === 0 && onlyAlerts) {
      onOnlyAlertsChange(false);
    }
  }, [alertCount, onlyAlerts, onOnlyAlertsChange]);

  return (
    <div className="inventory-view inventory-live-stock flex flex-col gap-3 h-full flex-1 min-h-0">
      {alertCount > 0 && (
        <div
          onClick={() => onOnlyAlertsChange(!onlyAlerts)}
          className={`flex flex-col sm:flex-row items-start gap-3 border rounded-2xl px-4 py-3 w-full cursor-pointer transition-all shadow-sm ${
            onlyAlerts
              ? "bg-red-100 border-red-400"
              : "bg-red-50 border-red-200 hover:bg-red-100 pulse-border-red"
          }`}
          title="اضغط هنا لفلترة الجدول وعرض النواقص فقط"
        >
          <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${onlyAlerts ? "text-red-600" : "text-red-500"}`} />
          <div className="flex-1 min-w-0 flex justify-between items-center">
            <div>
              <p className="text-sm font-bold text-red-700">
                تحذير: {alertCount} صنف وصل للحد الأدنى
              </p>
              <p className="text-xs text-red-500 mt-0.5">
                {onlyAlerts
                  ? "تمت تصفية الجدول لعرض هذه الأصناف بالأسفل ↓"
                  : `(اضغط هنا لعرضها بالجدول) منها: ${alertSamples.join(" • ")}${alertCount > alertSamples.length ? "..." : ""}`}
              </p>
            </div>
            {onlyAlerts && <FilterX className="w-5 h-5 text-red-500 opacity-70" />}
          </div>
        </div>
      )}

      <div className="glass-card inventory-data-panel overflow-hidden pt-0 flex flex-col flex-1 min-h-0">
        <div className="inventory-panel-toolbar flex items-center justify-between px-4 py-2 border-b border-slate-100 bg-white/70">
          <div className="text-[11px] font-bold text-slate-400">
            {matchingTotal !== null ? `النتائج: ${matchingTotal}` : `صفحة ${pageNumber}`}
            <span className="mx-2">•</span>
            آخر تحديث: {lastSync ? lastSync.toLocaleTimeString("ar-EG") : "—"}
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-500 hover:text-[#1e87bb] disabled:opacity-40"
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            تحديث
          </button>
        </div>

        <div className={`flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar transition-all duration-300 ${
          loading ? "opacity-50 pointer-events-none select-none grayscale-[20%]" : "opacity-100"
        }`}>
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
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        maxLength={100}
                        className="w-full pl-4 pr-9 py-2 text-xs border border-slate-200 rounded-lg outline-none focus:border-[#1e87bb] bg-white transition-all shadow-sm"
                      />
                    </div>
                  </div>
                </th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">رمز الصنف (SKU)</th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">{t("inventoryLive.inWarehouse")}</th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    قيد التحويل <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      البضاعة المحجوزة داخل الرصيد الفيزيائي وغير المتاحة حالياً للصرف
                    </div>
                  </div>
                </th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    إجمالي البضاعة <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[200px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      الرصيد الفيزيائي في المستودع والسيارات المرتبطة بهذا المستودع
                    </div>
                  </div>
                </th>
                <th className="px-4 pt-3.5 pb-2 text-xs font-bold text-slate-500 align-middle">
                  <div className="relative group flex items-center gap-1 border-b border-dashed border-slate-400 w-max cursor-help">
                    {t("inventoryLive.averageCost")} <Info className="w-3 h-3" />
                    <div className="absolute top-full right-1/2 translate-x-1/2 mt-2 w-max max-w-[240px] text-center bg-slate-800 text-white text-[10px] px-2 py-1.5 rounded-lg hidden group-hover:block z-50 whitespace-normal shadow-xl">
                      {t("inventoryLive.averageCostHint")}
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
              {products.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-400 text-sm">
                    {loading ? "جارٍ التحميل..." : "لا توجد بيانات مطابقة"}
                  </td>
                </tr>
              )}

              {products.map((p) => {
                const isAlert = compareQuantity(p.minimum_quantity, "0") > 0 && compareQuantity(p.available_quantity, p.minimum_quantity) <= 0;
                const displayName = t(`uom.${p.display_uom_code}`, {
                  defaultValue: t("inventoryCommon.unit"),
                });
                const baseName = t(`uom.${p.base_uom_code}`, {
                  defaultValue: t("inventoryCommon.unit"),
                });
                const renderQuantity = (value: typeof p.available_quantity) =>
                  formatCommercialQuantity(
                    value,
                    displayName,
                    baseName,
                    p.display_factor_to_base,
                  );
                return (
                  <tr
                    key={p.id}
                    className={`border-b border-slate-100/80 transition-all duration-200 ${
                      isAlert ? "bg-red-50/50 hover:bg-red-50/80" : "bg-white hover:bg-slate-50/60"
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
                      <div>{renderQuantity(p.available_quantity).primary}</div>
                      {renderQuantity(p.available_quantity).secondary && (
                        <div className="mt-0.5 text-[10px] text-slate-400">
                          {renderQuantity(p.available_quantity).secondary}
                        </div>
                      )}
                      {compareQuantity(p.blocked_quantity, "0") > 0 && (
                        <div className="text-[10px] font-bold text-amber-600 mt-0.5">
                          {t("inventoryLive.blocked")}: {renderQuantity(p.blocked_quantity).primary}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-violet-600 font-semibold">
                      {renderQuantity(p.reserved_quantity).primary}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-bold border-l border-slate-100">
                      {renderQuantity(p.total_quantity).primary}
                    </td>
                    <td className="px-4 py-3 text-slate-700 font-black tabular-nums">
                      {p.average_cost_display
                        ? `${formatMoney(p.average_cost_display, p.currency_code)} / ${displayName}`
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-red-600 font-bold bg-red-50/30">
                      {renderQuantity(p.damaged_quantity).primary}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {(hasPrevious || hasMore) && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50">
            <span className="text-xs font-bold text-slate-500">صفحة {pageNumber}</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onPrevious}
                disabled={!hasPrevious || loading}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
                title="الصفحة السابقة"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={onNext}
                disabled={!hasMore || loading}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
                title="الصفحة التالية"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
