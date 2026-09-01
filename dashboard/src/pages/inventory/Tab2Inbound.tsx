import { useState, useMemo, useEffect } from "react";
import { FilePlus, Search, Eraser } from "lucide-react";
import { toast } from "sonner";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { WarehouseProduct } from "./inventoryUtils";
import { toTotalPacks } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal"; // +++ الكي الجراحي: استدعاء النافذة العصرية +++

interface Props {
  products: WarehouseProduct[];
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onSuccess: () => void;
}

export function Tab2Inbound({ products, authenticatedFetch, onSuccess }: Props) {
  const [quantities, setQuantities] = useState<Record<string, { cartons: number; loose_packs: number }>>(() => {
    const saved = localStorage.getItem("inbound_draft_quantities");
    return saved ? JSON.parse(saved) : {};
  });
  const [search, setSearch] = useState("");
  const [referenceId, setReferenceId] = useState(() => localStorage.getItem("inbound_draft_ref") || "");
  const [notes, setNotes] = useState(() => localStorage.getItem("inbound_draft_notes") || "");
  const [submitting, setSubmitting] = useState(false);
  const [isConfirmClearOpen, setIsConfirmClearOpen] = useState(false); // +++ حالة النافذة العصرية +++

  // +++ حفظ أي تغيير يكتبه المستخدم في الذاكرة فوراً (Auto-Save) +++
  useEffect(() => { localStorage.setItem("inbound_draft_quantities", JSON.stringify(quantities)); }, [quantities]);
  useEffect(() => { localStorage.setItem("inbound_draft_ref", referenceId); }, [referenceId]);
  useEffect(() => { localStorage.setItem("inbound_draft_notes", notes); }, [notes]);

  const updateQty = (id: string, field: "cartons" | "loose_packs", val: number) => {
    setQuantities(prev => ({
      ...prev,
      [id]: {
        ...({ cartons: 0, loose_packs: 0 }),
        ...(prev[id] || {}),
        [field]: val
      }
    }));
  };

  const clearAll = () => {
    if (Object.keys(quantities).length > 0) {
      setIsConfirmClearOpen(true); // +++ فتح النافذة العصرية بدل تنبيه المتصفح +++
    }
  };

  const confirmClear = () => {
    setQuantities({});
    setReferenceId("");
    setNotes("");
    localStorage.removeItem("inbound_draft_quantities");
    localStorage.removeItem("inbound_draft_ref");
    localStorage.removeItem("inbound_draft_notes");
    setIsConfirmClearOpen(false);
    toast.success("تم تصفير الكميات والبيانات بالكامل بنجاح");
  };

  const handleSubmit = async () => {
    const itemsToSubmit: { product_variant_id: number; quantity_packs: number }[] = [];

    // تجميع الأصناف التي تم إدخال كميات لها فقط
    for (const [id, qty] of Object.entries(quantities)) {
      if (qty.cartons === 0 && qty.loose_packs === 0) continue;

      const p = products.find(prod => String(prod.id) === id);
      if (!p) continue;
      const ppc = p.packs_per_carton || 1;

      // درع الحماية من إدخال حبات أكبر من الكرتونة
      if (qty.loose_packs >= ppc) {
        toast.error(`⚠️ خطأ في صنف (${p.name}): عدد الحبات (${qty.loose_packs}) يجب أن يكون أقل من سعة الكرتونة (${ppc}).`);
        return;
      }

      itemsToSubmit.push({
        product_variant_id: parseInt(id),
        quantity_packs: toTotalPacks(qty.cartons, qty.loose_packs, ppc),
      });
    }

    if (itemsToSubmit.length === 0) return toast.error("أضف كمية لصنف واحد على الأقل لتوريده!");
    if (!referenceId.trim()) return toast.error("رقم الفاتورة أو المرجع إجباري لتوثيق التوريد!");

    setSubmitting(true);
    try {
      const data = await authenticatedFetch("/warehouse/inbound", {
        method: "POST",
        body: JSON.stringify({ items: itemsToSubmit, reference_id: referenceId.trim(), notes }),
      });

      toast.success(data?.message || "تم استلام البضاعة وتوثيقها بنجاح ✅");
      setQuantities({});
      setReferenceId("");
      setNotes("");
      // +++ تنظيف الذاكرة لتبدأ توريدة جديدة نظيفة +++
      localStorage.removeItem("inbound_draft_quantities");
      localStorage.removeItem("inbound_draft_ref");
      localStorage.removeItem("inbound_draft_notes");
      onSuccess();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // +++ خوارزمية البحث المرن (Tokenized Search) +++
  const displayedProducts = useMemo(() => {
    if (!search.trim()) return products;
    const tokens = search.toLowerCase().trim().split(/\s+/);
    return products.filter(p => tokens.every(t => p.name.toLowerCase().includes(t) || (p.sku && p.sku.toLowerCase().includes(t))));
  }, [products, search]);

  return (
    <div className="flex flex-col h-full flex-1 min-h-0 pt-1 animate-in fade-in duration-300">
      {/* +++ الكي الجراحي: نسف الفراغات المتراكمة (gap-4 و mt-4) لتوحيد المسافة مع باقي التبويبات +++ */}
      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm pb-2 flex-1 min-h-0">
          
          <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-emerald-500 to-teal-600 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
            <FilePlus className="w-4 h-4" /> توريد بضاعة (الاستلام المخزني)
          </div>

          {/* Grid Data Entry - Locked Height */}
          <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar bg-white mt-5 border-b border-slate-100">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-slate-50 shadow-sm border-b border-slate-200">
                <tr className="text-slate-500 text-xs uppercase text-right">
                  <th className="py-3 px-6 font-extrabold w-1/2">
                    {/* +++ حقن مربع البحث بجانب كلمة المنتج +++ */}
                    <div className="flex flex-col md:flex-row md:items-center gap-4">
                      <span>المنتج</span>
                      <div className="relative font-normal flex-1 max-w-sm">
                        <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                        <input
                          type="search"
                          placeholder="ابحث عن صنف (مثال: شيبس حار)..."
                          value={search}
                          onChange={e => setSearch(e.target.value)}
                          className="w-full pl-4 pr-9 py-1.5 text-xs border border-slate-200 rounded-lg outline-none focus:border-emerald-400 bg-white shadow-sm transition-all"
                        />
                      </div>
                    </div>
                  </th>
                  <th className="py-3 px-6 font-extrabold text-center relative">
                    {/* +++ الكي الجراحي: سنترة النص تماماً باستخدام absolute للزر لمنعه من دفش النص لليمين +++ */}
                    <span className="block w-full text-center">الكمية الواردة (كرتونة / حبة)</span>
                    <button onClick={clearAll} className="absolute left-4 top-1/2 -translate-y-1/2 text-[10px] font-bold text-red-500 hover:text-red-700 flex items-center gap-1 bg-red-50 hover:bg-red-100 px-2.5 py-1.5 rounded-md transition-colors border border-red-100 shadow-sm shrink-0">
                      <Eraser className="w-3.5 h-3.5" /> تصفير
                    </button>
                  </th>
                </tr>
              </thead>
            <tbody className="divide-y divide-slate-100">
              {displayedProducts.length === 0 ? (
                <tr><td colSpan={2} className="text-center py-12 text-slate-400">لا توجد منتجات مطابقة للبحث</td></tr>
              ) : (
                displayedProducts.map(prod => {
                  const id = String(prod.id);
                  const qty = quantities[id] || { cartons: 0, loose_packs: 0 };
                  const ppc = prod.packs_per_carton || 1;
                  const hasError = qty.loose_packs >= ppc;
                  const isFilled = qty.cartons > 0 || qty.loose_packs > 0;

                  return (
                    <tr key={id} className={`hover:bg-slate-50 transition-colors ${isFilled ? 'bg-emerald-50/40' : ''}`}>
                      {/* +++ الكي الجراحي: تقليل الحشوات (Padding) وتصغير الخط للحصول على Compact UI +++ */}
                      <td className="py-1.5 px-4">
                        <div className="font-bold text-slate-800 text-sm">{prod.name}</div>
                        <div className="text-[10px] text-slate-400 font-bold mt-0.5 flex items-center gap-2">
                          <span>SKU: {prod.sku || "—"}</span>
                          <span className="text-slate-300">•</span>
                          <span className="text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-md border border-emerald-100">التعبئة: {ppc} حبات</span>
                        </div>
                      </td>
                      <td className="py-1.5 px-4">
                        <div className="flex items-center justify-center gap-4 md:gap-8">
                          <div className="flex flex-col items-center gap-1">
                            <span className="text-[10px] font-bold text-slate-500">كراتين</span>
                            <QuantityInput value={qty.cartons} onChange={n => updateQty(id, "cartons", n)} />
                          </div>
                          <div className="flex flex-col items-center gap-1">
                            <span className={`text-[10px] font-bold ${hasError ? 'text-red-600 animate-pulse' : 'text-slate-500'}`}>
                              حبات {hasError && "⚠️"}
                            </span>
                            <QuantityInput value={qty.loose_packs} onChange={n => updateQty(id, "loose_packs", n)} isError={hasError} />
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* +++ الكي الجراحي: فوتر مدمج بتصميم Floating Labels، ومسافات مضغوطة لتوفير المساحة للجدول +++ */}
        {/* Footer Form & Submit */}
        <div className="p-3 bg-slate-50 rounded-b-2xl">
          <div className="flex flex-col md:flex-row items-center gap-3">
            
            <div className="flex-1 w-full grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
              <div className="relative">
                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">
                  رقم الفاتورة / المرجع <span className="text-red-500">*</span>
                </span>
                <input value={referenceId} onChange={(e) => setReferenceId(e.target.value)} placeholder="مثال: INV-2024-001" className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 transition shadow-sm outline-none" />
              </div>
              
              <div className="relative">
                <span className="absolute -top-2 right-3 px-1.5 text-[10px] font-black text-slate-500 bg-slate-50 z-10 leading-none">
                  ملاحظات (اختياري)
                </span>
                <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="أي ملاحظات إضافية..." className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-emerald-300 transition shadow-sm outline-none" />
              </div>
            </div>
            
            <div className="w-full md:w-auto mt-2 md:mt-0">
              <button onClick={handleSubmit} disabled={submitting} className="bg-gradient-to-r from-emerald-500 to-teal-600 hover:opacity-90 text-white px-6 py-2.5 rounded-xl text-sm font-black shadow-md transition-all active:scale-[0.98] w-full disabled:opacity-50 flex items-center justify-center gap-2">
                {submitting ? "جارٍ التوثيق..." : "✓ توثيق الاستلام"}
              </button>
            </div>
            
          </div>
        </div>

        {/* +++ الكي الجراحي: حقن النافذة العصرية لتأكيد التصفير +++ */}
        {isConfirmClearOpen && (
          <Modal
            isOpen={isConfirmClearOpen}
            onClose={() => setIsConfirmClearOpen(false)}
            title="⚠️ تأكيد التصفير"
            footer={
              <div className="flex gap-2 w-full">
                <button onClick={() => setIsConfirmClearOpen(false)} className="px-6 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl transition-colors">إلغاء</button>
                {/* +++ الكي الجراحي: إضافة autoFocus ليتم تحديد الزر تلقائياً فور فتح النافذة، مما يسمح بتأكيد التصفير بضغطة Enter +++ */}
                <button autoFocus onClick={confirmClear} className="flex-1 bg-red-500 text-white py-2 rounded-xl font-bold hover:bg-red-600 focus:ring-4 focus:ring-red-300 outline-none transition-all shadow-lg">نعم، صفر الكميات</button>
              </div>
            }
          >
            <div className="space-y-4">
              <p className="text-sm text-slate-600 font-bold">هل أنت متأكد من تصفير جميع الكميات المدخلة؟</p>
              <p className="text-xs text-red-500">لا يمكن التراجع عن هذه الخطوة وسيتم تفريغ الأرقام الحالية.</p>
            </div>
          </Modal>
        )}

      </div>
    </div>
  );
}