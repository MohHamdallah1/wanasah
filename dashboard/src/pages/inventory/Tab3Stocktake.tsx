import { useState, useMemo, useEffect, useCallback } from "react";
import { Lock, Unlock, AlertTriangle, Check, Info, Scan, Package } from "lucide-react";
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
  const [showUnlockModal, setShowUnlockModal] = useState(false); 
  const [showSubmitModal, setShowSubmitModal] = useState(false); // +++ حالة نافذة اعتماد التسوية +++
  const [showVarianceModal, setShowVarianceModal] = useState(false); // +++ حالة نافذة عرض الفروقات +++
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
        // 2. +++  (متوسط 1): الاستدانة من الكراتين (فك كرتونة) إذا نقصت الحبات عن صفر +++
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
      setShowSubmitModal(false); // +++ إغلاق نافذة الاعتماد +++
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
    <div className="flex flex-col gap-4 h-full flex-1 min-h-0 pt-1">
      
      {/* +++ حالة المستودع مفتوح (فارغ): عرض الأبواب الأسطورية في المنتصف +++ */}
      {!isAuditLocked && (
        <div className="flex-1 flex flex-col items-center justify-center bg-slate-50/50 rounded-3xl border border-slate-200/50 overflow-hidden relative">
          
          {/* خلفية جمالية (إضاءة المستودع) */}
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-64 bg-amber-400/10 blur-[80px] rounded-full pointer-events-none" />

          <div className="text-center mb-10 z-10">
            <h2 className="text-3xl font-black text-slate-800 tracking-tight">نظام تسوية المخزون</h2>
            <p className="text-slate-500 font-bold mt-2">المستودع مفتوح للعمليات.. اقترب من الأبواب لبدء الجرد</p>
          </div>

          {/* +++ الكي الجراحي: إطار نيون متحرك آمن 100% (Inline Styles) ليدل على حالة الإغلاق بدون أخطاء JIT +++ */}
          <div 
            className="relative w-80 h-48 rounded-xl overflow-hidden shadow-[0_0_30px_rgba(245,158,11,0.2)] group cursor-pointer p-[3px] bg-slate-800"
            dir="ltr"
            onClick={() => setShowLockModal(true)}
          >
            {/* شعاع النيون الدوار الآمن (CSS نقي) */}
            <div
              className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
              style={{
                backgroundImage: 'conic-gradient(from 0deg, transparent 75%, rgba(245,158,11,0.8) 100%)',
                animationDuration: '3s'
              }}
            />
            <div
              className="absolute inset-[-150%] opacity-80 animate-spin pointer-events-none"
              style={{
                backgroundImage: 'conic-gradient(from 180deg, transparent 75%, rgba(245,158,11,0.8) 100%)',
                animationDuration: '3s'
              }}
            />

            {/* حاوية الأبواب الفعلية */}
            <div className="relative w-full h-full bg-slate-900 rounded-[9px] overflow-hidden">
              {/* المحتوى الداخلي (الزر المتوهج) */}
              <div className="absolute inset-0 flex items-center justify-center bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-amber-900/40 via-slate-900 to-slate-900">
                <div className="flex flex-col items-center gap-3 scale-90 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-500 delay-100">
                  <div className="w-16 h-16 rounded-full bg-amber-500/20 flex items-center justify-center border border-amber-500/30 animate-pulse">
                    <Lock className="w-8 h-8 text-amber-500" />
                  </div>
                  <span className="text-white font-black text-lg tracking-wide drop-shadow-md">إغلاق المستودع وبدء الجرد</span>
                </div>
              </div>

              {/* الباب الأيسر (Left Door) */}
              <div className="absolute top-0 left-0 w-1/2 h-full bg-slate-200 border-r-2 border-slate-300 origin-left transition-transform duration-700 ease-out group-hover:-translate-x-full z-10">
                <div className="absolute top-4 left-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute bottom-4 left-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-1/3" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-2/3" />
                <div className="absolute top-1/2 -translate-y-1/2 right-3 w-2 h-14 bg-slate-400 rounded-full shadow-inner border border-slate-300" /> 
              </div>

              {/* الباب الأيمن (Right Door) */}
              <div className="absolute top-0 right-0 w-1/2 h-full bg-slate-200 border-l-2 border-slate-300 origin-right transition-transform duration-700 ease-out group-hover:translate-x-full z-10">
                <div className="absolute top-4 right-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute bottom-4 right-3 w-1.5 h-1.5 rounded-full bg-slate-400 shadow-sm" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-1/3" />
                <div className="absolute left-0 w-full h-px bg-slate-300 top-2/3" />
                <div className="absolute top-1/2 -translate-y-1/2 left-3 w-2 h-14 bg-slate-400 rounded-full shadow-inner border border-slate-300" />
              </div>
              
              <div className="absolute top-0 left-0 w-full h-2 bg-gradient-to-b from-slate-900/40 to-transparent z-20 pointer-events-none" />
              <div className="absolute bottom-0 left-0 w-full h-2 bg-gradient-to-t from-slate-900/60 to-transparent z-20 pointer-events-none" />
            </div>
          </div>

          <p className="mt-8 text-xs text-slate-400 font-bold flex items-center gap-1.5">
            <Info className="w-3.5 h-3.5" /> عند بدء الجرد سيتم إيقاف جميع العمليات اللوجستية
          </p>
        </div>
      )}

      {isAuditLocked && (
        <div className="glass-card flex flex-col border border-slate-200 shadow-sm flex-1 min-h-0 pt-0 overflow-hidden">
          {/* تم إعدام البار الأصفر المزعج بالكامل */}
          
          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-100 text-right sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500">المنتج</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">الإجمالي المتوقع</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-[#1e87bb] text-center">الجرد الفعلي (كرتونة / حبة)</th>
                  <th className="px-4 py-3.5 text-xs font-bold text-slate-500 text-center">فرق الجرد</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50 bg-white">
                {enrichedRows.map((r) => {
                  // +++ المحرك الرياضي الصارم لضمان دقة الكراتين والحبات 100% +++
                  const ppc = r.packs_per_carton || 1;
                  const expectedCartons = Math.floor(r.expected_packs / ppc);
                  const expectedLoose = r.expected_packs % ppc;

                  return (
                    <tr key={r.product_variant_id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 font-bold text-slate-800">{r.product_name}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-center gap-3">
                          <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-100 px-3 py-1 rounded-lg">
                            <span className="text-sm font-black text-slate-700">{expectedCartons}</span>
                            <span className="text-[10px] font-bold text-slate-400">ك</span>
                          </div>
                          {expectedLoose > 0 && (
                            <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-100 px-3 py-1 rounded-lg">
                              <span className="text-sm font-black text-slate-700">{expectedLoose}</span>
                              <span className="text-[10px] font-bold text-slate-400">ح</span>
                            </div>
                          )}
                        </div>
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
                          {/* +++  (متوسط 1): السماح للزر بالنزول لـ -1 لتشغيل منطق فك الكرتونة +++ */}
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
                )})}
              </tbody>
            </table>
          </div>

          {/* +++ الكي الجراحي: كونسول سفلي موحد ونظيف (One-Line Footer) +++ */}
          <div className="bg-slate-900 text-white rounded-b-2xl overflow-hidden border-t border-slate-700">
            <div className="px-5 py-4 flex flex-wrap items-center justify-between gap-6">
              
              {/* الإحصائيات وحالة الجرد في خط واحد */}
              <div className="flex flex-wrap items-center gap-6 flex-1 min-w-[300px]">
                
                {/* الإحصائيات (الإجمالي، مطابق، عجز) */}
                <div className="flex gap-6 border-l border-slate-700 pl-6">
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">الإجمالي</span>
                    <span className="text-sm font-extrabold">{totals.totalItems} صنف</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">مطابق</span>
                    <span className="text-sm font-extrabold text-emerald-400">{totals.matchedItems} صنف</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-[10px] text-slate-400 font-bold uppercase">عجز/زيادة</span>
                    <span className={`text-sm font-extrabold ${totals.varianceItems > 0 ? "text-red-400" : "text-slate-300"}`}>
                      {totals.varianceItems} صنف
                    </span>
                  </div>
                </div>

                {/* زر الفروقات أو رسالة المطابقة */}
                <div>
                  {totals.varianceItems > 0 ? (
                    <button
                      onClick={() => setShowVarianceModal(true)}
                      className="text-xs font-bold bg-red-500/20 text-red-400 hover:bg-red-500/30 px-4 py-2 rounded-xl transition-all border border-red-500/30 flex items-center gap-2 hover:shadow-[0_0_15px_rgba(239,68,68,0.2)]"
                    >
                      <AlertTriangle className="w-4 h-4" /> عرض الأصناف غير المطابقة ({totals.varianceItems})
                    </button>
                  ) : (
                    <p className="text-xs text-emerald-400 font-bold flex items-center gap-1.5 bg-emerald-500/10 px-4 py-2 rounded-xl border border-emerald-500/20">
                      <Check className="w-4 h-4" /> جميع الأصناف مطابقة تماماً للمتوقع ✅
                    </p>
                  )}
                </div>
              </div>

              {/* أزرار القرار فقط */}
              <div className="flex items-end gap-2 w-full lg:w-auto min-w-[280px]">
                <button
                  onClick={() => setShowUnlockModal(true)}
                  /* +++ مفتاح المعايرة: زر الإلغاء بارتفاع h-9 (صغير ومدمج) +++ */
                  className="flex-1 px-4 h-9 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 border border-transparent hover:border-red-500/30 text-xs font-bold rounded-xl transition-all flex items-center justify-center"
                >
                  إلغاء الجرد
                </button>
                <button
                  onClick={() => setShowSubmitModal(true)}
                  /* +++ مفتاح المعايرة: زر الاعتماد بارتفاع h-9 (صغير ومدمج) +++ */
                  className="flex-[2.5] px-4 h-9 bg-amber-500 hover:bg-amber-600 text-slate-900 text-sm font-black rounded-xl shadow-lg transition-all flex items-center justify-center gap-2"
                >
                  <Check className="w-5 h-5" /> اعتماد التسوية
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

      {/* +++ مودال فتح المستودع وإلغاء الجرد +++ */}
      <Modal
        isOpen={showUnlockModal}
        onClose={() => setShowUnlockModal(false)}
        title="⚠️ تأكيد فتح المستودع"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowUnlockModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50 transition-colors">تراجع</button>
            <button onClick={() => { setShowUnlockModal(false); handleToggleLock(); }} className="flex-1 px-5 py-2 bg-emerald-500 hover:bg-emerald-600 text-white font-bold rounded-xl shadow-md transition-colors">نعم، افتح النظام للعمليات</button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <p className="text-sm text-slate-600 font-bold">هل أنت متأكد من رغبتك في فتح المستودع واستئناف العمليات اللوجستية؟</p>
        </div>
      </Modal>
      {/* +++ مودال اعتماد التسوية (تم نقل حقل الملاحظات هنا) +++ */}
      <Modal
        isOpen={showSubmitModal}
        onClose={() => setShowSubmitModal(false)}
        title="✅ اعتماد تسوية الجرد نهائياً"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-3 w-full">
            <button onClick={() => setShowSubmitModal(false)} className="flex-1 px-4 py-2 rounded-xl border border-slate-200 text-slate-600 font-bold hover:bg-slate-50 transition-colors">تراجع</button>
            <button onClick={handleSubmit} disabled={submitting} className="flex-[1.5] px-5 py-2 bg-amber-500 hover:bg-amber-600 text-slate-900 font-black rounded-xl shadow-md transition-colors flex justify-center items-center gap-2">
              {submitting ? "جاري الاعتماد..." : "تأكيد الاعتماد"}
            </button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="bg-amber-50 border-r-4 border-amber-500 p-4 rounded-l-lg">
            <p className="text-sm text-amber-800 font-bold">
              أنت على وشك اعتماد جرد المخزون نهائياً. سيتم ترحيل الفروقات (إن وجدت) وفتح النظام للعمليات اللوجستية بشكل كامل.
            </p>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-bold text-slate-700">ملاحظات ختامية للجرد (اختياري)</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="اكتب أي ملاحظات حول الفروقات أو حالة المستودع..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 focus:ring-2 focus:ring-amber-500 outline-none resize-none h-24 transition-all"
            />
          </div>
        </div>
      </Modal>

      {/* +++ مودال قائمة الفروقات (تظهر فقط عند الضغط على الزر) +++ */}
      <Modal
        isOpen={showVarianceModal}
        onClose={() => setShowVarianceModal(false)}
        title="⚠️ تفاصيل الفروقات (عجز / زيادة)"
        maxWidth="max-w-lg"
        footer={
          <button onClick={() => setShowVarianceModal(false)} className="w-full px-4 py-2 bg-slate-100 text-slate-700 font-bold rounded-xl hover:bg-slate-200 transition-colors">إغلاق</button>
        }
      >
        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar pr-2 space-y-2">
          {enrichedRows.filter(r => r.variance !== 0).map(r => (
            <div key={r.product_variant_id} className="flex items-center justify-between p-3 bg-slate-50 border border-slate-100 rounded-xl hover:border-slate-200 transition-colors">
              <span className="font-bold text-slate-800 text-sm">{r.product_name}</span>
              <span className={`font-black text-sm dir-ltr px-3 py-1 rounded-lg ${r.variance > 0 ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"}`}>
                {r.variance > 0 ? "+ " : "- "} {formatQty(Math.abs(r.variance), r.packs_per_carton)}
              </span>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}