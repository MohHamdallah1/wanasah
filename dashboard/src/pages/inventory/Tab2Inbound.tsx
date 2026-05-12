import { useState, useMemo, useCallback, memo } from "react";
import { FilePlus, Trash2, Plus } from "lucide-react";
import { toast } from "sonner";
import { CustomSelect } from "@/components/ui/custom-select";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { WarehouseProduct, InboundRow } from "./inventoryUtils";
import { toTotalPacks } from "./inventoryUtils";

interface Props {
  products: WarehouseProduct[];
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onSuccess: () => void;
}

// +++ النسف المعماري: إضافة tempId فريد لكل سطر لضمان سلامة الـ React State +++
const EMPTY_ROW = (): InboundRow & { tempId: string } => ({
  tempId: crypto.randomUUID(),
  product_variant_id: "",
  cartons: 0,
  loose_packs: 0
});

// +++ المكون الفرعي المصفح (InboundItemRow): لمنع الـ Re-renders الزائدة وتحسين الأداء +++
const InboundItemRow = memo(({
  row,
  index,
  products,
  updateRow,
  removeRow,
  isRemovable,
  selectedProductIds
}: {
  row: InboundRow & { tempId: string };
  index: number;
  products: WarehouseProduct[];
  updateRow: (i: number, patch: Partial<InboundRow>) => void;
  removeRow: (i: number) => void;
  isRemovable: boolean;
  selectedProductIds: Set<string>;
}) => {
  const ppc = products.find((p) => String(p.id) === row.product_variant_id)?.packs_per_carton ?? 1;

  // فلترة الخيارات لمنع تكرار نفس الصنف في الفاتورة
  const productOptions = products
    .filter(p => !selectedProductIds.has(String(p.id)) || String(p.id) === row.product_variant_id)
    .map((p) => ({ id: String(p.id), label: p.name }));

  return (
    <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 items-end bg-slate-50/70 rounded-2xl p-3 border border-slate-100">
      <CustomSelect
        label="الصنف"
        options={productOptions}
        value={row.product_variant_id}
        onChange={(id) => updateRow(index, { product_variant_id: id })}
        placeholder="اختر صنف..."
      />
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-slate-600">كراتين</span>
        <QuantityInput value={row.cartons} onChange={(n) => updateRow(index, { cartons: n })} />
      </div>
      <div className="flex flex-col gap-1">
        <span className={`text-xs font-bold transition-colors ${row.loose_packs >= ppc ? "text-red-600 animate-pulse" : "text-slate-600"}`}>
          حبات (max {ppc - 1}) {row.loose_packs >= ppc && "⚠️"}
        </span>
        <QuantityInput
          value={row.loose_packs}
          onChange={(n) => updateRow(index, { loose_packs: n })}
          isError={row.loose_packs >= ppc}
        />
      </div>
      <button
        onClick={() => removeRow(index)}
        disabled={!isRemovable}
        className="p-2 rounded-xl text-slate-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-30"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
});

export function Tab2Inbound({ products, authenticatedFetch, onSuccess }: Props) {
  const [rows, setRows] = useState<(InboundRow & { tempId: string })[]>([EMPTY_ROW()]);
  const [referenceId, setReferenceId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // +++ تحسين الأداء: تتبع الأصناف المختارة مسبقاً لمنع الازدواجية +++
  const selectedProductIds = useMemo(() =>
    new Set(rows.map(r => r.product_variant_id).filter(id => id !== "")),
    [rows]);

  const updateRow = useCallback((i: number, patch: Partial<InboundRow>) => {
    setRows((prev) => prev.map((r, idx) => {
      if (idx !== i) return r;
      const updated = { ...r, ...patch };

      const p = products.find(prod => String(prod.id) === updated.product_variant_id);
      const ppc = p?.packs_per_carton ?? 1;

      // --- تم إزالة القص التلقائي هنا للسماح للمسؤول برؤية خطئه ومعالجته يدوياً ---

      return updated;
    }));
  }, [products]);

  const removeRow = useCallback((i: number) =>
    setRows((prev) => prev.filter((_, idx) => idx !== i)), []);

  const addRow = () => setRows((prev) => [...prev, EMPTY_ROW()]);

  const handleSubmit = async () => {
    // 1. فلترة الأسطر المعبأة فقط
    const valid = rows.filter((r) => r.product_variant_id);
    if (!valid.length) { toast.error("أضف صنفاً واحداً على الأقل"); return; }

    // +++ الدرع المعماري (Senior Validation): منع الحفظ إذا كان هناك خطأ في إدخال الحبات +++
    for (const row of valid) {
      const p = products.find((prod) => String(prod.id) === row.product_variant_id);
      const ppc = p?.packs_per_carton ?? 1;

      if (row.loose_packs >= ppc) {
        toast.error(`⚠️ خطأ في صنف (${p?.name}): عدد الحبات (${row.loose_packs}) لا يمكن أن يكون مساوياً أو أكبر من سعة الكرتونة (${ppc}).`);
        return; // توقف فوراً وامنع إرسال الطلب
      }
    }

    // 2. التحقق من أن كل سطر تم اختياره يحتوي على كمية (منع الفشل الصامت)
    const items = valid.map((r) => {
      const p = products.find((prod) => String(prod.id) === r.product_variant_id);
      const ppc = p?.packs_per_carton ?? 1;
      return {
        product_variant_id: parseInt(r.product_variant_id),
        quantity_packs: toTotalPacks(r.cartons, r.loose_packs, ppc),
      };
    });

    const hasZeroQty = items.some((x) => x.quantity_packs <= 0);
    if (hasZeroQty) {
      toast.error("مرفوض: يوجد أصناف مختارة كميتها (صفر). يرجى تعبئتها أو حذف السطر.");
      return;
    }

    if (!referenceId.trim()) {
      toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد!");
      return;
    }

    setSubmitting(true);
    try {
      // +++ استلام الداتا مباشرة والاعتماد على الهوك في معالجة الأخطاء +++
      const data = await authenticatedFetch("/warehouse/inbound", {
        method: "POST",
        body: JSON.stringify({ items, reference_id: referenceId.trim(), notes }),
      });

      toast.success(data?.message || "تم استلام البضاعة بنجاح");
      setRows([EMPTY_ROW()]);
      setReferenceId("");
      setNotes("");
      onSuccess();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="glass-card p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-700 flex items-center gap-2">
            <FilePlus className="w-4 h-4 text-emerald-600" />
            إدخال بضاعة واردة (Supplier Inbound)
          </h3>
          <button
            onClick={addRow}
            className="flex items-center gap-1.5 text-xs font-bold text-emerald-600 hover:text-emerald-700 border border-emerald-200 hover:border-emerald-400 rounded-xl px-3 py-1.5 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> إضافة صنف
          </button>
        </div>

        {/* Rows - تثبيت الارتفاع ليكون واجهة عمل ثابتة (Fixed Workspace) */}
        <div className="flex flex-col gap-3 h-[45vh] overflow-y-auto pr-2 custom-scrollbar bg-slate-50 border border-slate-200 shadow-inner rounded-2xl p-3">
          {rows.map((row, i) => (
            <InboundItemRow
              key={row.tempId}
              row={row}
              index={i}
              products={products}
              updateRow={updateRow}
              removeRow={removeRow}
              isRemovable={rows.length > 1}
              selectedProductIds={selectedProductIds}
            />
          ))}
        </div>

        {/* Reference & Notes */}
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-600">رقم الفاتورة / المرجع</label>
            <input
              value={referenceId}
              onChange={(e) => setReferenceId(e.target.value)}
              placeholder="مثال: INV-2024-001"
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 transition"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-600">ملاحظات</label>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="اختياري..."
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 transition"
            />
          </div>
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="self-end px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-bold rounded-xl shadow-lg transition-all disabled:opacity-50"
        >
          {submitting ? "جارٍ الحفظ..." : "✓ تأكيد الاستلام"}
        </button>
      </div>
    </div>
  );
}