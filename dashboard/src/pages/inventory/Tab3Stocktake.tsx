import { useState, useMemo, useEffect, useCallback } from "react";
import { Lock, Unlock, AlertTriangle, Check, Info } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { QuantityInput } from "@/components/ui/quantity-input";
import type { WarehouseProduct, StocktakeRow } from "./inventoryUtils";
import { toTotalPacks, formatQty } from "./inventoryUtils";

interface Props {
  products: WarehouseProduct[];
  isAuditLocked: boolean;
  authenticatedFetch: (url: string, opts?: RequestInit) => Promise<any>;
  onLockChange: (locked: boolean) => void;
}

const DRAFT_KEY = "wanasah_audit_draft";

export function Tab3Stocktake({ products, isAuditLocked, authenticatedFetch, onLockChange }: Props) {
  const [showLockModal, setShowLockModal] = useState(false);
  const [showUnsavedWarning, setShowUnsavedWarning] = useState(false);
  const [rows, setRows] = useState<StocktakeRow[]>([]);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [locking, setLocking] = useState(false);

  // حفظ المسودة بذكاء (Debounce)
  useEffect(() => {
    if (isAuditLocked && rows.length > 0) {
      const timeoutId = setTimeout(() => {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(rows));
      }, 1000);
      return () => clearTimeout(timeoutId);
    }
  }, [rows, isAuditLocked]);

  // استرجاع المسودة أو تهيئة الجدول
  useEffect(() => {
    if (isAuditLocked) {
      const saved = localStorage.getItem(DRAFT_KEY);
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed) && parsed.length > 0) {
            setRows(parsed);
            return;
          }
        } catch (e) {
          localStorage.removeItem(DRAFT_KEY);
        }
      }
      const initial = products.map((p) => ({
        product_variant_id: p.id,
        product_name: p.name,
        packs_per_carton: p.packs_per_carton,
        expected_packs: p.total_packs,
        actual_cartons: Math.floor(p.total_packs / p.packs_per_carton),
        actual_loose_packs: p.total_packs % p.packs_per_carton,
      }));
      setRows(initial);
    } else {
      setRows([]);
    }
  }, [isAuditLocked, products]);

  const executeToggleLock = async () => {
    setShowUnsavedWarning(false);
    const newStatus = isAuditLocked ? "ACTIVE" : "AUDIT_LOCK";
    setLocking(true);
    try {
      const data = await authenticatedFetch("/warehouse/lock", {
        method: "PUT",
        body: JSON.stringify({ status: newStatus }),
      });
      toast.success(data?.message || "تم تغيير حالة المستودع");
      onLockChange(newStatus === "AUDIT_LOCK");
      if (newStatus === "ACTIVE") localStorage.removeItem(DRAFT_KEY);
    } catch (e: any) {
      toast.error(e.message || "فشل تغيير الحالة");
    } finally {
      setLocking(false);
      setShowLockModal(false);
    }
  };

  const handleToggleLock = async () => {
    if (isAuditLocked) {
      const hasUnsavedChanges = enrichedRows.some(r => r.actual_total !== r.expected_packs);
      if (hasUnsavedChanges) {
        setShowUnsavedWarning(true);
        return;
      }
    }
    await executeToggleLock();
  };

  const updateRow = useCallback((id: number, field: "actual_cartons" | "actual_loose_packs", val: number) => {
    setRows((prev) => prev.map((r) => {
      if (r.product_variant_id === id) {
        const updated = { ...r, [field]: val };
        const ppc = updated.packs_per_carton || 1;

        // 1. الترحيل للأعلى (إذا زادت الحبات عن سعة الكرتونة)
        if (updated.actual_loose_packs >= ppc) {
          updated.actual_cartons += Math.floor(updated.actual_loose_packs / ppc);
          updated.actual_loose_packs = updated.actual_loose_packs % ppc;
        }
        // 2. +++ النسف المعماري (متوسط 1): الاستدانة من الكراتين (فك كرتونة) إذا نقصت الحبات عن صفر +++
        else if (updated.actual_loose_packs < 0) {
          if (updated.actual_cartons > 0) {
            updated.actual_cartons -= 1;
            updated.actual_loose_packs = ppc - 1;
          } else {
            updated.actual_loose_packs = 0; // لا يمكن الاستدانة، الكراتين صفر
          }
        }
        return updated;
      }
      return r;
    }));
  }, []);

  const handleSubmit = async () => {
    const items = rows.map((r) => ({
      product_variant_id: r.product_variant_id,
      actual_packs: toTotalPacks(r.actual_cartons, r.actual_loose_packs, r.packs_per_carton),
    }));
    setSubmitting(true);
    try {
      const data = await authenticatedFetch("/warehouse/stocktake", {
        method: "POST",
        body: JSON.stringify({ items, notes }),
      });
      toast.success(data?.message || "تمت تسوية المستودع وفتحه للعمليات بنجاح");
      setNotes("");
      localStorage.removeItem(DRAFT_KEY);
      onLockChange(false);
    } catch (e: any) {
      toast.error(e.message || "فشل تسوية المستودع");
    } finally {
      setSubmitting(false);
    }
  };

  const enrichedRows = useMemo(() => {
    return rows.map((r) => {
      const actual_total = toTotalPacks(r.actual_cartons, r.actual_loose_packs, r.packs_per_carton);
      return { ...r, actual_total, variance: actual_total - r.expected_packs };
    });
  }, [rows]);

  const totals = useMemo(() => {
    return enrichedRows.reduce((acc, r) => ({
      totalItems: acc.totalItems + 1,
      matchedItems: acc.matchedItems + (r.variance === 0 ? 1 : 0),
      varianceItems: acc.varianceItems + (r.variance !== 0 ? 1 : 0)
    }), { totalItems: 0, matchedItems: 0, varianceItems: 0 });
  }, [enrichedRows]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between bg-white p-4 rounded-2xl shadow-sm border border-slate-200">
        <div className="flex items-center gap-3">
          <div className={`p-3 rounded-xl ${isAuditLocked ? "bg-amber-100 text-amber-600" : "bg-emerald-100 text-emerald-600"}`}>
            {isAuditLocked ? <Lock className="w-6 h-6" /> : <Unlock className="w-6 h-6" />}
          </div>
          <div>
            <h2 className="text-lg font-bold text-slate-800">حالة المستودع: {isAuditLocked ? "مغلق للجرد" : "مفتوح للعمليات"}</h2>
            <p className="text-sm text-slate-500 font-semibold mt-0.5">
              {isAuditLocked ? "جميع عمليات التحميل والتنزيل معلقة حتى إنهاء التسوية." : "النظام جاهز لاستقبال حركات التوريد والتحميل."}
            </p>
          </div>
        </div>
        <button
          onClick={() => isAuditLocked ? handleToggleLock() : setShowLockModal(true)}
          className={`px-5 py-2.5 rounded-xl text-sm font-bold transition-all shadow-sm flex items-center gap-2 ${isAuditLocked ? "bg-slate-100 hover:bg-slate-200 text-slate-700" : "bg-amber-500 hover:bg-amber-600 text-white"
            }`}
        >
          {isAuditLocked ? "إلغاء وفتح النظام" : "بدء الجرد"}
        </button>
      </div>

      {isAuditLocked && (
        <div className="glass-card overflow-hidden flex flex-col border border-amber-200 shadow-lg shadow-amber-500/5">
          <div className="bg-amber-50 px-5 py-3 border-b border-amber-100 flex items-center justify-between">
            <h3 className="font-bold text-amber-800 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              ورقة عمل الجرد (لا يُنصح بتحديث الصفحة)
            </h3>
            <span className="text-xs font-black bg-amber-200 text-amber-800 px-3 py-1 rounded-full animate-pulse">
              يتم الحفظ التلقائي كمسودة
            </span>
          </div>

          <div className="overflow-x-auto max-h-[50vh] custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-white border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-4 py-3 text-xs font-bold text-slate-500">المنتج</th>
                  <th className="px-4 py-3 text-xs font-bold text-slate-500 text-center">الإجمالي المتوقع</th>
                  <th className="px-4 py-3 text-xs font-bold text-blue-600 text-center">الجرد الفعلي (كرتونة / حبة)</th>
                  <th className="px-4 py-3 text-xs font-bold text-slate-500 text-center">فرق الجرد</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 bg-slate-50/30">
                {enrichedRows.map((r) => (
                  <tr key={r.product_variant_id} className="hover:bg-white transition-colors">
                    <td className="px-4 py-3 font-bold text-slate-800">{r.product_name}</td>
                    <td className="px-4 py-3 text-center">
                      <span className="inline-flex bg-slate-100 text-slate-600 px-3 py-1 rounded-lg text-xs font-bold" dir="ltr">
                        {formatQty(r.expected_packs, r.packs_per_carton)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-center gap-4">
                        <div className="flex items-center gap-1.5">
                          <QuantityInput
                            value={r.actual_cartons}
                            onChange={(v) => updateRow(r.product_variant_id, "actual_cartons", v)}
                            min={0}
                          />
                          <span className="text-xs font-bold text-slate-500">ك</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          {/* +++ النسف المعماري (متوسط 1): السماح للزر بالنزول لـ -1 لتشغيل منطق فك الكرتونة +++ */}
                          <QuantityInput
                            value={r.actual_loose_packs}
                            onChange={(v) => updateRow(r.product_variant_id, "actual_loose_packs", v)}
                            min={-1}
                          />
                          <span className="text-xs font-bold text-slate-500">ح</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {r.variance === 0 ? (
                        <span className="text-slate-400 font-bold">-</span>
                      ) : (
                        <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-black ${r.variance > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`} dir="ltr">
                          {r.variance > 0 ? "+ " : "- "} {formatQty(Math.abs(r.variance), r.packs_per_carton)}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* الخلاصة السفلية التفصيلية */}
          <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
            <div className="px-5 py-4 flex flex-wrap items-end justify-between gap-6">
              <div className="flex-1 min-w-[300px]">
                <div className="flex gap-6 mb-3 border-b border-slate-700 pb-3">
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">الإجمالي</span>
                    <span className="text-sm font-extrabold">{totals.totalItems} صنف</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">مطابق</span>
                    <span className="text-sm font-extrabold text-emerald-400">{totals.matchedItems} صنف</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">عجز / زيادة</span>
                    <span className={`text-sm font-extrabold ${totals.varianceItems > 0 ? "text-red-400" : "text-slate-300"}`}>
                      {totals.varianceItems} صنف
                    </span>
                  </div>
                </div>

                {totals.varianceItems > 0 ? (
                  <div className="max-h-[80px] overflow-y-auto custom-scrollbar pr-2 space-y-1">
                    {enrichedRows.filter(r => r.variance !== 0).map(r => (
                      <div key={r.product_variant_id} className="flex items-center justify-between text-xs bg-slate-800/50 px-2 py-1 rounded">
                        <span className="font-bold text-slate-300">{r.product_name}</span>
                        <span className={`font-black dir-ltr ${r.variance > 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {r.variance > 0 ? "+" : "-"} {formatQty(Math.abs(r.variance), r.packs_per_carton)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-emerald-500 font-bold">جميع الأصناف مطابقة تماماً للمتوقع ✅</p>
                )}
              </div>

              <div className="flex flex-col gap-3 w-full sm:w-auto">
                <input
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="ملاحظات ختامية للجرد..."
                  className="w-full sm:w-64 rounded-xl border-none bg-white/10 px-3 py-2 text-sm text-white placeholder:text-slate-400 focus:ring-2 focus:ring-amber-500 transition-all"
                />
                <button
                  onClick={handleSubmit}
                  disabled={submitting}
                  className="w-full px-6 py-2.5 bg-amber-500 hover:bg-amber-600 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting ? "..." : <><Check className="w-5 h-5" /> اعتماد التسوية</>}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* مودال قفل المستودع */}
      <Modal
        isOpen={showLockModal}
        onClose={() => setShowLockModal(false)}
        title="⚠️ إجراء أمني: قفل المستودع"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowLockModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50">إلغاء</button>
            <button onClick={executeToggleLock} disabled={locking} className="flex-1 px-5 py-2 bg-amber-500 hover:bg-amber-600 text-white font-bold rounded-xl shadow-md">{locking ? "جارٍ القفل..." : "نعم، ابدأ الجرد"}</button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="bg-amber-50 border-r-4 border-amber-500 p-4">
            <p className="text-sm text-amber-800 font-bold">هذا الإجراء سيوقف جميع عمليات التحميل والبيع فوراً لضمان سلامة الجرد المالي.</p>
          </div>
          <p className="text-sm text-slate-600">هل أنت متأكد من رغبتك في تجميد المستودع وبدء جرد فعلي؟</p>
        </div>
      </Modal>

      {/* مودال التحذير من فقدان المسودة */}
      <Modal
        isOpen={showUnsavedWarning}
        onClose={() => setShowUnsavedWarning(false)}
        title="⚠️ تحذير: بيانات غير محفوظة"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowUnsavedWarning(false)} className="flex-1 px-4 py-2 rounded-xl bg-slate-100 text-slate-700 font-bold hover:bg-slate-200">إلغاء</button>
            <button onClick={executeToggleLock} disabled={locking} className="flex-1 px-5 py-2 bg-red-500 hover:bg-red-600 text-white font-bold rounded-xl shadow-md">نعم، احذف المسودة وافتح النظام</button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-600 leading-relaxed font-bold">
            لقد قمت بإدخال فروقات جرد ولكنك <span className="text-red-500">لم تقم بـ "اعتماد التسوية"</span>.
          </p>
          <p className="text-xs text-slate-500 p-3 bg-red-50 rounded-lg border border-red-100">
            إذا قمت بفتح النظام الآن، سيتم إلغاء هذه الإدخالات ولن تُحفظ التسوية. هل أنت متأكد من رغبتك بالخروج؟
          </p>
        </div>
      </Modal>
    </div>
  );
}