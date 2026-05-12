import { useState, useEffect, useRef } from "react";
import { Modal } from "@/components/ui/modal";
import { CheckCircle2, AlertTriangle, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { QuantityInput } from "@/components/ui/quantity-input";
import { DriverData } from "@/data/operations-data";
import { toast } from "sonner";

interface InventoryJard {
  product_id: number;
  product_name: string;
  expected: number;
  packs_per_carton: number;
  actual_cartons: number;
  actual_loose_packs: number;
}

interface SettlementModalProps {
  isOpen: boolean;
  onClose: () => void;
  driver: DriverData | null;
  onConfirmSettlement: (actualCash: number, inventoryJard: any[], notes: string) => void;
}

export function SettlementModal({ isOpen, onClose, driver, onConfirmSettlement }: SettlementModalProps) {
  const [actualCash, setActualCash] = useState<string>("");
  const [jardData, setJardData] = useState<InventoryJard[]>([]);
  const [settlementNotes, setSettlementNotes] = useState<string>("");
  const isInitialized = useRef(false);

  // +++ النسف المعماري لقنبلة الـ Reset: التهيئة تتم مرة واحدة فقط عند فتح المودال +++
  useEffect(() => {
    if (isOpen && driver && !isInitialized.current) {
      setActualCash(String(driver.settlement.financials.expected_cash_in_hand));
      setSettlementNotes("");
      setJardData(
        driver.settlement.inventory.map((item: any) => {
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
      isInitialized.current = true;
    } else if (!isOpen) {
      isInitialized.current = false;
    }
  }, [isOpen, driver]);

  if (!driver) return null;

  const expected = driver.settlement.financials.expected_cash_in_hand;
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
          // 2. +++ النسف المعماري (متوسط 1): الاستدانة من الكراتين (فك كرتونة) إذا نقصت الحبات عن صفر +++
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
      title={`🧾 جرد التسوية — ${driver.session.driver_name}`}
      maxWidth="max-w-4xl"
      footer={
        <button
          onClick={handleConfirm}
          className="flex items-center gap-2 px-8 py-3 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-xl shadow-lg transition-all active:scale-[0.98]"
        >
          <CheckCircle2 className="w-5 h-5" />
          تأكيد واعتماد العهدة
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-6" dir="rtl">

        {/* ============ القسم الأيمن: الكاش ============ */}
        <div className="space-y-5">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2">
            💰 الجرد المالي
          </h4>

          {/* الكاش المتوقع */}
          <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200">
            <p className="text-xs font-bold text-slate-500 mb-1">الكاش المتوقع من النظام</p>
            <p className="text-4xl font-extrabold tabular-nums text-slate-800">
              {expected.toLocaleString("ar-JO", { minimumFractionDigits: 2 })}
              <span className="text-lg font-bold text-slate-400 mr-1">د.أ</span>
            </p>
            <div className="flex gap-3 mt-2 text-xs text-slate-500">
              <span>مبيعات: <strong>{driver.settlement.financials.cash_from_sales.toLocaleString("ar-JO")} د.أ</strong></span>
              <span className="text-slate-300">•</span>
              <span>ذمم: <strong>{driver.settlement.financials.cash_from_debts.toLocaleString("ar-JO")} د.أ</strong></span>
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

        {/* ============ القسم الأيسر: الجرد المستودعي ============ */}
        <div className="space-y-5">
          <h4 className="font-extrabold text-slate-700 text-sm uppercase tracking-wide border-b border-slate-100 pb-2">
            📦 جرد المستودع
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
        <div className="space-y-5 max-h-[70vh] overflow-y-auto custom-scrollbar pr-2">
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
                          {/* +++ النسف المعماري (متوسط 1): السماح بالنزول لـ -1 لتفعيل الاستدانة من الكراتين +++ */}
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

      </div>
    </Modal>
  );
}
