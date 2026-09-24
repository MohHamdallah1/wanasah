import { currentLocale } from "@/i18n";
import { useState, useEffect, useRef } from "react";
import { Modal } from "@/components/ui/modal";
import {
  CheckCircle2,
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  Minus,
  Gift,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { QuantityInput } from "@/components/ui/quantity-input";
import { FINANCIAL_SETTLEMENT_READY_STATUS } from "@/data/operations-data";
import type { DriverData, SessionSettlementReport } from "@/data/operations-data";
import { toast } from "sonner";

interface InventoryJard {
  product_id: number;
  product_name: string;
  expected: number;
  packs_per_carton: number;
  actual_cartons: number;
  actual_loose_packs: number;
}

export interface SettlementCountInput { product_id: number; actual: number }

interface SettlementModalProps {
  isOpen: boolean;
  onClose: () => void;
  driver: DriverData | null;
  report: SessionSettlementReport | null;
  isReportLoading: boolean;
  reportError: string | null;
  onRetryReport: () => void;
  isSubmitting: boolean;
  onConfirmSettlement: (actualCash: number, inventoryJard: SettlementCountInput[], notes: string) => void;
}

export function SettlementModal({
  isOpen,
  onClose,
  driver,
  report,
  isReportLoading,
  reportError,
  onRetryReport,
  isSubmitting,
  onConfirmSettlement,
}: SettlementModalProps) {
  const [actualCash, setActualCash] = useState<string>("");
  const [jardData, setJardData] = useState<InventoryJard[]>([]);
  const [settlementNotes, setSettlementNotes] = useState<string>("");
  const initializedSessionId = useRef<number | null>(null);

  // تتم التهيئة من التقرير التفصيلي الموثوق مرة واحدة لكل جلسة مفتوحة.
  useEffect(() => {
    if (
      isOpen &&
      driver &&
      report &&
      initializedSessionId.current !== driver.session.session_id
    ) {
      setActualCash(report.financials.expected_cash_in_hand);
      setSettlementNotes("");
      setJardData(
        report.inventory.map((item) => {
          const ppc = item.packs_per_carton || 1;
          const remaining = item.remaining_quantity || 0;
          return {
            product_id: item.product_id,
            product_name: item.product_name,
            expected: remaining,
            packs_per_carton: ppc,
            actual_cartons: Math.floor(remaining / ppc),
            actual_loose_packs: remaining % ppc,
          };
        })
      );
      initializedSessionId.current = driver.session.session_id;
    } else if (!isOpen) {
      initializedSessionId.current = null;
    }
  }, [isOpen, driver, report]);

  if (!driver) return null;

  if (!report) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={`🧾 تقرير التسوية — ${driver.session.driver_name}`}
        maxWidth="max-w-2xl"
      >
        <div className="min-h-52 flex items-center justify-center" dir="rtl">
          {isReportLoading ? (
            <div className="flex flex-col items-center gap-3 text-slate-500">
              <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
              <p className="text-sm font-bold">جارٍ تحميل التقرير التفصيلي من الخادم...</p>
            </div>
          ) : (
            <div className="max-w-md text-center space-y-4">
              <AlertTriangle className="w-9 h-9 text-amber-500 mx-auto" />
              <p className="text-sm font-bold text-slate-700">
                {reportError || "تعذر تحميل تقرير التسوية التفصيلي."}
              </p>
              <button
                type="button"
                onClick={onRetryReport}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 text-white text-sm font-bold hover:bg-slate-700 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                إعادة المحاولة
              </button>
            </div>
          )}
        </div>
      </Modal>
    );
  }

  // +++ الكي الجراحي: تحويل النص القادم من السيرفر إلى رقم بشكل آمن لمنع أخطاء الرياضيات (NaN) +++
  const expected = parseFloat(report.financials.expected_cash_in_hand) || 0;
  const actual = parseFloat(actualCash) || 0;
  const diff = actual - expected;

  const handleJardChange = (productId: number, field: "actual_cartons" | "actual_loose_packs", value: number) => {
    setJardData((prev) =>
      prev.map((item) => {
        if (item.product_id === productId) {
          const updated = { ...item, [field]: value };

          // 1. الترحيل للأعلى (إذا زادت الحبات عن سعة الكرتونة)
          if (updated.actual_loose_packs >= updated.packs_per_carton) {
            updated.actual_cartons += Math.floor(updated.actual_loose_packs / updated.packs_per_carton);
            updated.actual_loose_packs = updated.actual_loose_packs % updated.packs_per_carton;
          }
          // 2. +++  (متوسط 1): الاستدانة من الكراتين (فك كرتونة) إذا نقصت الحبات عن صفر +++
          else if (updated.actual_loose_packs < 0) {
            if (updated.actual_cartons > 0) {
              updated.actual_cartons -= 1;
              updated.actual_loose_packs = updated.packs_per_carton - 1;
            } else {
              updated.actual_loose_packs = 0; // لا يمكن الاستدانة، الكراتين صفر أصلاً
            }
          }
          return updated;
        }
        return item;
      })
    );
  };

  const handleConfirm = () => {
    // +++ درع التسامح (نسف 5): إجبارية الملاحظة عند وجود عجز مالي +++
    if (diff !== 0 && settlementNotes.trim() === "") {
      toast.error(`يوجد فرق نقدي (${diff.toFixed(2)} د.أ). يجب كتابة تبرير لاعتماد التسوية.`);
      return;
    }

    const payload = jardData.map(item => ({
      product_id: item.product_id,
      actual: (item.actual_cartons * item.packs_per_carton) + item.actual_loose_packs
    }));

    onConfirmSettlement(actual, payload, settlementNotes);
  };

  const DiffBadge = () => {
    if (diff === 0) return (
      <span className="inline-flex items-center gap-1 text-emerald-600 font-bold text-sm bg-emerald-50 px-3 py-1 rounded-full">
        <Minus className="w-3.5 h-3.5" /> مطابق تماماً ✓
      </span>
    );
    if (diff > 0) return (
      <span className="inline-flex items-center gap-1 text-blue-600 font-bold text-sm bg-blue-50 px-3 py-1 rounded-full">
        <TrendingUp className="w-3.5 h-3.5" /> زيادة +{diff.toFixed(2)} د.أ
      </span>
    );
    return (
      <span className="inline-flex items-center gap-1 text-red-600 font-bold text-sm bg-red-50 px-3 py-1 rounded-full">
        <TrendingDown className="w-3.5 h-3.5" /> عجز {diff.toFixed(2)} د.أ
      </span>
    );
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`🧾 تقرير التسوية — ${report.driver_name}`}
      maxWidth="max-w-4xl"
      footer={
        <button
          onClick={handleConfirm}
          disabled={isSubmitting || report.status !== FINANCIAL_SETTLEMENT_READY_STATUS}
          className="flex items-center gap-2 px-8 py-3 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-bold rounded-xl shadow-lg transition-all active:scale-[0.98]"
        >
          {isSubmitting ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <CheckCircle2 className="w-5 h-5" />
          )}
          {isSubmitting ? "جارٍ الاعتماد..." : "تأكيد واعتماد العهدة"}
        </button>
      }
    >
      <div className="settlement-grid grid grid-cols-1 lg:grid-cols-2 gap-6" dir="rtl">

        <div className="lg:col-span-2 grid grid-cols-2 md:grid-cols-4 gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <div>
            <p className="text-[11px] font-bold text-slate-400">حالة الجلسة</p>
            <p className="text-sm font-black text-slate-700 mt-1">{report.status}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-400">تاريخ الجلسة</p>
            <p className="text-sm font-black text-slate-700 mt-1">{report.session_date || "—"}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-400">الزيارات المكتملة</p>
            <p className="text-sm font-black text-slate-700 mt-1">{report.visits.completed_total}</p>
          </div>
          <div>
            <p className="text-[11px] font-bold text-slate-400">زيارات ناجحة</p>
            <p className="text-sm font-black text-slate-700 mt-1">{report.visits.successful_sales}</p>
          </div>
        </div>

        {report.status !== FINANCIAL_SETTLEMENT_READY_STATUS && (
          <div className="lg:col-span-2 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-800">
            لا يمكن اعتماد التسوية المالية قبل اكتمال التسوية المخزنية وختم Ending Snapshot.
          </div>
        )}

        {/* ============ القسم الأيمن: الكاش ============ */}
        <div className="settlement-financial-panel space-y-5">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2">
            💰 الجرد المالي
          </h4>

          {/* الكاش المتوقع */}
          <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200">
            <p className="text-xs font-bold text-slate-500 mb-1">الكاش المتوقع من النظام</p>
            <p className="text-4xl font-extrabold tabular-nums text-slate-800">
              {expected.toLocaleString(currentLocale(), { minimumFractionDigits: 2 })}
              <span className="text-lg font-bold text-slate-400 mr-1">د.أ</span>
            </p>
            <div className="flex gap-3 mt-2 text-xs text-slate-500">
              {/* +++ الكي الجراحي: تمرير النصوص للدوال الرياضية يتطلب ParseFloat +++ */}
              <span>مبيعات: <strong>{parseFloat(report.financials.cash_from_sales || "0").toLocaleString(currentLocale())} د.أ</strong></span>
              <span className="text-slate-300">•</span>
              <span>ذمم: <strong>{parseFloat(report.financials.cash_from_debts || "0").toLocaleString(currentLocale())} د.أ</strong></span>
              <span className="text-slate-300">•</span>
              <span>فروقات مخزنية: <strong>{parseFloat(report.financials.inventory_shortage_cash || "0").toLocaleString(currentLocale())} د.أ</strong></span>
            </div>
          </div>

          {/* حقل الإدخال */}
          <div>
            <label className="block text-xs font-bold text-slate-600 mb-2">الكاش الفعلي المستلم (د.أ)</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={actualCash}
              onChange={(e) => setActualCash(e.target.value)}
              className={`w-full text-3xl font-extrabold tabular-nums text-center rounded-2xl border-2 py-4 px-4 outline-none transition-all focus:ring-4 ${diff < 0
                ? "border-red-300 bg-red-50 focus:ring-red-100 text-red-700"
                : diff > 0
                  ? "border-blue-300 bg-blue-50 focus:ring-blue-100 text-blue-700"
                  : "border-emerald-300 bg-emerald-50 focus:ring-emerald-100 text-emerald-700"
                }`}
            />
          </div>

          {/* نتيجة المقارنة */}
          <div className={`rounded-2xl p-4 flex items-center gap-3 border ${diff < 0
            ? "bg-red-50 border-red-200"
            : diff > 0
              ? "bg-blue-50 border-blue-200"
              : "bg-emerald-50 border-emerald-200"
            }`}>
            {diff < 0 && <AlertTriangle className="w-5 h-5 text-red-500 shrink-0" />}
            <div>
              <p className="text-xs font-bold text-slate-500 mb-1">نتيجة المطابقة</p>
              <DiffBadge />
            </div>
          </div>
        </div>

        {/* ============ ملاحظات التسوية ============ */}
        <div className="settlement-notes-panel space-y-5">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2">
            📝 ملاحظات التسوية
          </h4>

          {/* حقل التبرير الإجباري */}
          {diff !== 0 && (
            <div className="animate-in fade-in slide-in-from-top-2">
              <label className="block text-xs font-bold text-red-600 mb-2">تبرير العجز/الزيادة النقدي (إجباري)*</label>
              <textarea
                rows={2}
                value={settlementNotes}
                onChange={(e) => setSettlementNotes(e.target.value)}
                placeholder="اكتب سبب الفارق المالي هنا..."
                className="w-full text-sm font-bold text-slate-700 rounded-2xl border-2 border-red-300 bg-red-50 p-3 outline-none focus:ring-4 focus:ring-red-100 placeholder:text-red-300"
              />
            </div>
          )}
          {diff === 0 && (
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-2">ملاحظات إضافية (اختياري)</label>
              <input
                type="text"
                value={settlementNotes}
                onChange={(e) => setSettlementNotes(e.target.value)}
                placeholder="ملاحظات التسوية..."
                className="w-full text-sm rounded-xl border border-slate-200 bg-slate-50 py-2 px-3 outline-none focus:border-slate-400"
              />
            </div>
          )}

        </div>

        {/* ============ القسم الأيسر: الجرد المستودعي ============ */}
        <div className="settlement-inventory-panel space-y-5 max-h-[70vh] overflow-y-auto custom-scrollbar pr-2">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2">
            📦 جرد المستودع
          </h4>

          <div className="space-y-3">
            {jardData.map((item) => {
              const actualTotalPacks = (item.actual_cartons * item.packs_per_carton) + item.actual_loose_packs;
              const invDiffPacks = actualTotalPacks - item.expected;

              const diffCartons = Math.floor(Math.abs(invDiffPacks) / item.packs_per_carton);
              const diffLoose = Math.abs(invDiffPacks) % item.packs_per_carton;
              const diffStr = (invDiffPacks < 0 ? "- " : "+ ") + (diffCartons > 0 ? `${diffCartons}ك ` : "") + (diffLoose > 0 ? `${diffLoose}ح` : "");

              return (
                <div
                  key={item.product_id}
                  className={`rounded-2xl p-4 border transition-all ${invDiffPacks < 0
                    ? "bg-red-50 border-red-200"
                    : invDiffPacks > 0
                      ? "bg-amber-50 border-amber-200"
                      : "bg-slate-50 border-slate-200"
                    }`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <p className="font-bold text-slate-700 text-sm">{item.product_name}</p>
                    {invDiffPacks !== 0 && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${invDiffPacks < 0 ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-700"
                        }`} dir="ltr">
                        {diffStr}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 text-center">
                      <p className="text-[10px] text-slate-400 mb-1">المتوقع</p>
                      <p className="text-sm font-extrabold tabular-nums text-slate-600">
                        <span dir="ltr">{Math.floor(item.expected / item.packs_per_carton)}ك {item.expected % item.packs_per_carton > 0 ? `${item.expected % item.packs_per_carton}ح` : ''}</span>
                      </p>
                    </div>
                    <div className="text-slate-300 font-bold">←</div>
                    <div className="flex-[2]">
                      <p className="text-[10px] text-slate-400 mb-1 text-center">الجرد الفعلي</p>
                      <div className="flex items-center justify-center gap-2">
                        <div className="flex items-center gap-1">
                          <QuantityInput
                            value={item.actual_cartons}
                            onChange={(v) => handleJardChange(item.product_id, "actual_cartons", v)}
                            min={0}
                          />
                          <span className="text-xs font-bold text-slate-500">ك</span>
                        </div>
                        <div className="flex items-center gap-1">
                          {/* +++  (متوسط 1): السماح بالنزول لـ -1 لتفعيل الاستدانة من الكراتين +++ */}
                          <QuantityInput
                            value={item.actual_loose_packs}
                            onChange={(v) => handleJardChange(item.product_id, "actual_loose_packs", v)}
                            min={-1}
                          />
                          <span className="text-xs font-bold text-slate-500">ح</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ملخص الجرد */}
          {jardData.some((i) => ((i.actual_cartons * i.packs_per_carton) + i.actual_loose_packs) !== i.expected) && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
              <p className="text-xs font-bold text-amber-700 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                يوجد فروقات مستودعية — سيتم عزلها وتسجيلها في تقرير التسوية
              </p>
            </div>
          )}
        </div>

        <div className="lg:col-span-2 space-y-3">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2 flex items-center gap-2">
            <Gift className="w-4 h-4 text-violet-600" />
            العينات المسلّمة خلال الجلسة
          </h4>

          {report.samples_given.length === 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-center text-sm font-bold text-slate-500">
              لا توجد عينات مسلّمة في هذه الجلسة.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {report.samples_given.map((sample, index) => (
                <div
                  key={`${sample.shop_name}-${sample.product_name}-${index}`}
                  className="rounded-2xl border border-violet-100 bg-violet-50/50 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-black text-slate-800 truncate">{sample.product_name}</p>
                      <p className="text-xs font-bold text-slate-500 mt-1 truncate">{sample.shop_name}</p>
                    </div>
                    <span className="shrink-0 rounded-lg bg-white border border-violet-100 px-2.5 py-1 text-xs font-black text-violet-700">
                      {sample.sample_quantity_cartons} ك · {sample.sample_quantity_packs} ح
                    </span>
                  </div>
                  <p className="text-xs text-slate-600 mt-3">
                    <span className="font-bold">السبب:</span> {sample.reason || "بدون سبب"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </Modal>
  );
}
