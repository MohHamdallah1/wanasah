import { useState, useEffect } from "react";
import { Modal } from "@/components/ui/modal";
import { CheckCircle2, AlertTriangle, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { DriverData } from "@/data/operations-data";

interface InventoryJard {
  product_id: number;
  product_name: string;
  expected: number;
  actual: number;
}

interface SettlementModalProps {
  isOpen: boolean;
  onClose: () => void;
  driver: DriverData | null;
  onConfirmSettlement: (actualCash: number, inventoryJard: InventoryJard[]) => void;
}

export function SettlementModal({ isOpen, onClose, driver, onConfirmSettlement }: SettlementModalProps) {
  const [actualCash, setActualCash] = useState<string>("");
  const [jardData, setJardData] = useState<InventoryJard[]>([]);

  // إعادة تهيئة البيانات عند فتح النافذة أو تغيير المندوب
  useEffect(() => {
    if (driver && isOpen) {
      setActualCash(String(driver.settlement.financials.expected_cash_in_hand));
      setJardData(
        driver.settlement.inventory.map((item) => ({
          product_id: item.product_id,
          product_name: item.product_name,
          expected: item.remaining_quantity,
          actual: item.remaining_quantity,
        }))
      );
    }
  }, [driver, isOpen]);

  if (!driver) return null;

  const expected = driver.settlement.financials.expected_cash_in_hand;
  const actual = parseFloat(actualCash) || 0;
  const diff = actual - expected;

  const handleJardChange = (productId: number, value: string) => {
    setJardData((prev) =>
      prev.map((item) =>
        item.product_id === productId ? { ...item, actual: parseInt(value) || 0 } : item
      )
    );
  };

  const handleConfirm = () => {
    onConfirmSettlement(actual, jardData);
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
              className={`w-full text-3xl font-extrabold tabular-nums text-center rounded-2xl border-2 py-4 px-4 outline-none transition-all focus:ring-4 ${
                diff < 0
                  ? "border-red-300 bg-red-50 focus:ring-red-100 text-red-700"
                  : diff > 0
                  ? "border-blue-300 bg-blue-50 focus:ring-blue-100 text-blue-700"
                  : "border-emerald-300 bg-emerald-50 focus:ring-emerald-100 text-emerald-700"
              }`}
            />
          </div>

          {/* نتيجة المقارنة */}
          <div className={`rounded-2xl p-4 flex items-center gap-3 border ${
            diff < 0
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

          <div className="space-y-3">
            {jardData.map((item) => {
              const invDiff = item.actual - item.expected;
              return (
                <div
                  key={item.product_id}
                  className={`rounded-2xl p-4 border transition-all ${
                    invDiff < 0
                      ? "bg-red-50 border-red-200"
                      : invDiff > 0
                      ? "bg-amber-50 border-amber-200"
                      : "bg-slate-50 border-slate-200"
                  }`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <p className="font-bold text-slate-700 text-sm">{item.product_name}</p>
                    {invDiff !== 0 && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                        invDiff < 0 ? "bg-red-100 text-red-600" : "bg-amber-100 text-amber-700"
                      }`}>
                        {invDiff > 0 ? `+${invDiff}` : invDiff} كرتون
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 text-center">
                      <p className="text-[10px] text-slate-400 mb-1">المتبقي المتوقع</p>
                      <p className="text-2xl font-extrabold tabular-nums text-slate-600">{item.expected}</p>
                    </div>
                    <div className="text-slate-300 font-bold">←</div>
                    <div className="flex-1">
                      <p className="text-[10px] text-slate-400 mb-1 text-center">الجرد الفعلي</p>
                      <input
                        type="number"
                        min="0"
                        value={item.actual}
                        onChange={(e) => handleJardChange(item.product_id, e.target.value)}
                        className={`w-full text-2xl font-extrabold tabular-nums text-center rounded-xl border-2 py-1.5 outline-none transition-all focus:ring-2 ${
                          invDiff < 0
                            ? "border-red-300 bg-white focus:ring-red-100 text-red-600"
                            : invDiff > 0
                            ? "border-amber-300 bg-white focus:ring-amber-100 text-amber-600"
                            : "border-emerald-300 bg-white focus:ring-emerald-100 text-emerald-600"
                        }`}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* ملخص الجرد */}
          {jardData.some((i) => i.actual !== i.expected) && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
              <p className="text-xs font-bold text-amber-700 flex items-center gap-1">
                <AlertTriangle className="w-3.5 h-3.5" />
                يوجد فروقات في الجرد — سيتم تسجيلها في تقرير التسوية
              </p>
            </div>
          )}
        </div>

      </div>
    </Modal>
  );
}
