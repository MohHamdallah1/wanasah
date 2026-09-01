import { useState, useMemo, useEffect } from "react";
import { History, Search, ChevronRight, ChevronLeft, Eye, FileText, Package } from "lucide-react";
import type { LedgerEntry } from "./inventoryUtils";
import { getLedgerBadge, formatQty } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal";
import { toast } from "sonner"; // +++ استيراد التوست المفقود +++
import { useAuthFetch } from "@/hooks/useAuthFetch"; // +++ استيراد الدرع الأمني +++

interface Props {
  entries: LedgerEntry[];
  loading: boolean;
  onRefresh: () => void; // +++ استلام دالة التحديث +++
}

export function Tab4Ledger({ entries, loading, onRefresh }: Props) {
  const authenticatedFetch = useAuthFetch(); // +++ تهيئة الهوك في المكان الصحيح هندسياً +++
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterType, setFilterType] = useState<string>("ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedNote, setSelectedNote] = useState<string | null>(null);
  const [adjustingEntry, setAdjustingEntry] = useState<LedgerEntry | null>(null);
  const [adjPassword, setAdjPassword] = useState("");
  const [newQty, setNewQty] = useState({ cartons: 0, loose: 0 });
  const [adjSubmitting, setAdjSubmitting] = useState(false);

  // +++ حالة وصل التسليم (Delivery Note) +++
  const [selectedReference, setSelectedReference] = useState<string | null>(null);

  const ITEMS_PER_PAGE = 20;

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(search);
      setCurrentPage(1);
    }, 300);
    return () => clearTimeout(handler);
  }, [search]);

  const uniqueTypes = useMemo(() => Array.from(new Set(entries.map(e => e.type))), [entries]);

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      const q = debouncedSearch.trim().toLowerCase();
      const matchSearch = !q || (
        e.product_name.toLowerCase().includes(q) ||
        (e.reference || "").toLowerCase().includes(q) ||
        (e.admin_name || "").toLowerCase().includes(q) ||
        (e.notes || "").toLowerCase().includes(q)
      );
      const matchType = filterType === "ALL" || e.type === filterType;
      return matchSearch && matchType;
    });
  }, [entries, debouncedSearch, filterType]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return filtered.slice(start, start + ITEMS_PER_PAGE);
  }, [filtered, currentPage]);

  // +++ جلب جميع حركات الفاتورة المختارة لعرضها في وصل التسليم +++
  const deliveryNoteItems = useMemo(() => {
    if (!selectedReference) return [];
    return entries.filter(e => e.reference === selectedReference);
  }, [selectedReference, entries]);

  return (
    <div className="flex flex-col h-full flex-1 min-h-0 pt-1">
      {/* +++ الكي الجراحي: توحيد المسافة عبر إلغاء mt-2 و gap-4 +++ */}
      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm flex-1 min-h-0">
        
        {/* الشريطة العائمة */}
        <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-blue-600 to-indigo-700 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
          <History className="w-4 h-4" /> سجل الحركات ({filtered.length})
        </div>

        {/* شريط الفلترة والبحث (مدمج وأنيق داخل رأس البطاقة) */}
        <div className="p-3 pt-5 border-b border-slate-100 flex flex-col sm:flex-row items-center justify-end gap-3 bg-slate-50 rounded-t-2xl">
          <div className="flex items-center gap-3 w-full sm:w-auto">
            {/* قائمة الفلترة */}
            <select
              value={filterType}
              onChange={(e) => { setFilterType(e.target.value); setCurrentPage(1); }}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm cursor-pointer"
            >
              <option value="ALL">جميع الحركات</option>
              {uniqueTypes.map(t => <option key={t} value={t}>{getLedgerBadge(t).label}</option>)}
            </select>
            
            {/* مربع البحث */}
            <div className="relative flex-1 sm:w-64">
              <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" strokeWidth={1.5} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="ابحث في السجل..."
                className="w-full rounded-xl border border-slate-200 bg-white pr-9 pl-3 py-2 text-xs font-bold text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm"
              />
            </div>
          </div>
        </div>

        {/* +++ الكي الجراحي: نسف الـ vh واستخدام flex-1 min-h-0 ليتمدد الجدول بمرونة تامة +++ */}
        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar bg-white rounded-b-2xl">
          <table className="w-full text-sm">
            {/* +++ تثبيت الترويسة لتبقى ظاهرة أثناء النزول +++ */}
            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur shadow-sm border-b border-slate-200 text-right">
              <tr>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">نوع العملية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المنتج</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد قبل</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الكمية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد بعد</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الفاتورة / المرجع</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الملاحظات</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">التاريخ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading && (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-slate-400 font-bold">جارٍ التحميل...</td>
                </tr>
              )}
              {!loading && paginated.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center py-12 text-slate-400">لا توجد حركات مطابقة</td>
                </tr>
              )}
              {paginated.map((e) => {
                const badge = getLedgerBadge(e.type);
                const isNeg = e.quantity_packs < 0;
                const ppc = e.packs_per_carton || 1;
                return (
                  <tr key={e.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-1 rounded-lg text-[11px] font-black ${badge.bg} ${badge.text}`}>
                        {badge.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-bold text-slate-800 text-sm">{e.product_name}</td>

                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">
                      {formatQty(e.balance_before, ppc)}
                    </td>

                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>
                      <div dir="rtl" className="flex items-center gap-1 justify-end">
                        <span>{isNeg ? "-" : "+"}</span>
                        <span>{formatQty(Math.abs(e.quantity_packs), ppc)}</span>
                      </div>
                    </td>

                    <td className="px-4 py-3 text-slate-800 font-bold text-xs bg-slate-50/50 border-r border-l border-slate-100">
                      {formatQty(e.balance_after, ppc)}
                    </td>

                    <td className="px-4 py-3 text-slate-600 text-xs font-bold">
                      {e.admin_name || "—"}
                    </td>

                    <td className="px-4 py-3">
                      {e.reference && e.reference !== "بدون فاتورة" ? (
                        e.reference.startsWith("MANUAL_ADJUST") ? (
                          <span className="text-[11px] font-bold text-slate-500 bg-slate-100 px-2 py-1 rounded-md">تعديل يدوي للحمولة</span>
                        ) : e.reference.startsWith("VEH_") ? (
                          <span className="text-[11px] font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded-md">حمولة سيارة (صباحي)</span>
                        ) : e.reference.startsWith("SESS_") ? (
                          <span className="text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2 py-1 rounded-md">تسوية جرد مندوب</span>
                        ) : e.reference.startsWith("BATCH_") ? (
                          <span className="text-[11px] font-bold text-violet-600 bg-violet-50 px-2 py-1 rounded-md">حوالة منتصف اليوم</span>
                        ) : e.reference.startsWith("TRANS_") ? (
                          <span className="text-[11px] font-bold text-emerald-600 bg-emerald-50 px-2 py-1 rounded-md">رد المندوب (مصافحة)</span>
                        ) : e.type === 'INBOUND_SUPPLIER' || e.type === 'INBOUND_CORRECTION' ? (
                          <span className="text-[11px] font-bold text-slate-700 bg-slate-100 border border-slate-200 px-2 py-1 rounded-md flex items-center gap-1 w-max">
                            <FileText className="w-3 h-3 text-slate-500" />
                            فاتورة مورد: <span className="text-blue-700">{e.reference}</span>
                          </span>
                        ) : (
                          <button
                            onClick={() => setSelectedReference(e.reference)}
                            className="flex items-center gap-1.5 text-xs text-[#1e87bb] hover:text-blue-800 font-bold hover:bg-blue-50 px-2 py-1 rounded-md transition-all border border-transparent hover:border-blue-200"
                            title="عرض تفاصيل الفاتورة"
                          >
                            <FileText className="w-3.5 h-3.5" />
                            {e.reference}
                          </button>
                        )
                      ) : <span className="text-slate-400 text-xs font-mono">—</span>}
                    </td>

                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {e.notes ? (
                          <button
                            onClick={() => setSelectedNote(e.notes)}
                            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 font-semibold bg-slate-100 px-2 py-1 rounded-lg transition-colors"
                            title="قراءة الملاحظات"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        ) : <span className="text-slate-300">—</span>}

                        {e.type === 'INBOUND_SUPPLIER' && (
                          <button
                            onClick={() => {
                              setAdjustingEntry(e);
                              const netPacks = entries
                                .filter(x => x.reference === e.reference && x.product_name === e.product_name && (x.type === 'INBOUND_SUPPLIER' || x.type === 'INBOUND_CORRECTION'))
                                .reduce((sum, x) => sum + x.quantity_packs, 0);

                              const currentNetTotal = Math.max(0, netPacks);
                              setNewQty({ cartons: Math.floor(currentNetTotal / ppc), loose: currentNetTotal % ppc });
                            }}
                            className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 bg-purple-50 px-2 py-1 rounded-lg transition-all border border-purple-100 hover:border-purple-300"
                            title="تعديل أو إرجاع هذه الفاتورة"
                          >
                            تعديل
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-[11px] font-semibold whitespace-nowrap" dir="ltr">
                      {e.date ? new Date(e.date.endsWith("Z") || e.date.includes("+") ? e.date : e.date + "Z").toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" }) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* الفوتر - الترقيم */}
        {!loading && totalPages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50 rounded-b-2xl">
            <span className="text-xs font-bold text-slate-500">
              صفحة {currentPage} من {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30 transition-all shadow-sm"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* مودال الملاحظات */}
      <Modal isOpen={!!selectedNote} onClose={() => setSelectedNote(null)} title="تفاصيل الحركة المحاسبية" maxWidth="max-w-md">
        <div className="p-4 bg-slate-50 rounded-xl border border-slate-100">
          <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{selectedNote}</p>
        </div>
      </Modal>

      {/* +++ مودال وصل التسليم المجمع (Delivery Note) +++ */}
      <Modal isOpen={!!selectedReference} onClose={() => setSelectedReference(null)} title={`وصل تسليم مجمع: ${selectedReference}`} maxWidth="max-w-2xl">
        <div className="flex flex-col gap-4">
          <div className="bg-blue-50 border border-blue-100 p-4 rounded-xl flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="w-5 h-5 text-blue-600" />
              <span className="font-bold text-blue-800">رقم المرجع: {selectedReference}</span>
            </div>
            {/* +++ الكي الجراحي: استخدام نفس الدرع الزمني الموجود في الجدول لمنع كراش Invalid Date +++ */}
            <span className="text-xs font-bold text-slate-500">
              {deliveryNoteItems[0]?.date ? new Date(deliveryNoteItems[0].date.endsWith("Z") || deliveryNoteItems[0].date.includes("+") ? deliveryNoteItems[0].date : deliveryNoteItems[0].date + "Z").toLocaleString("ar-EG") : ""}
            </span>
          </div>

          <div className="border border-slate-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 border-b border-slate-200 text-right">
                <tr>
                  <th className="px-4 py-2 text-xs font-bold text-slate-600">الصنف</th>
                  <th className="px-4 py-2 text-xs font-bold text-slate-600 text-center">الكمية المصروفة/المستلمة</th>
                  <th className="px-4 py-2 text-xs font-bold text-slate-600">نوع الحركة</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {deliveryNoteItems.map(item => {
                  const badge = getLedgerBadge(item.type);
                  const isNeg = item.quantity_packs < 0;
                  return (
                    <tr key={item.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-bold text-slate-800 flex items-center gap-2">
                        <Package className="w-4 h-4 text-slate-400" />
                        {item.product_name}
                      </td>
                      <td className={`px-4 py-3 text-center font-bold dir-ltr ${isNeg ? "text-red-600" : "text-emerald-600"}`}>
                        {isNeg ? "-" : "+"}{formatQty(Math.abs(item.quantity_packs), item.packs_per_carton || 1)}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex px-2 py-1 rounded-md text-[10px] font-bold ${badge.bg} ${badge.text}`}>
                          {badge.label}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </Modal>

      {/* +++ مودال التعديل العكسي المصفح +++ */}
      <Modal
        isOpen={!!adjustingEntry}
        onClose={() => { setAdjustingEntry(null); setAdjPassword(""); }}
        title="🛠️ تعديل فاتورة توريد"
        maxWidth="max-w-md"
        footer={
          <div className="flex gap-2 w-full">
            <button onClick={() => setAdjustingEntry(null)} className="px-4 py-2 text-slate-500 font-bold hover:bg-slate-100 rounded-xl">إلغاء</button>
            <button
              disabled={adjSubmitting || !adjPassword}
              onClick={async () => {
                // +++ الدرع المعماري لمنع المسؤول من التخبيص في الحبات +++
                const ppc = adjustingEntry?.packs_per_carton || 1;
                if (newQty.loose >= ppc) {
                  toast.error(`⚠️ خطأ: عدد الحبات (${newQty.loose}) لا يمكن أن يكون مساوياً أو أكبر من سعة الكرتونة (${ppc}).`);
                  return;
                }

                setAdjSubmitting(true);
                try {
                  const totalPacks = (newQty.cartons * ppc) + newQty.loose;

                  // +++ استخدام الهوك الموحد لضمان أمان التوكن والروابط +++
                  await authenticatedFetch(`/warehouse/ledger/${adjustingEntry?.id}/adjust`, {
                    method: 'POST',
                    body: JSON.stringify({ password: adjPassword, new_total_packs: totalPacks })
                  });

                  toast.success("تم تسجيل حركة التعديل وتحديث المخزون بنجاح ✅");
                  setAdjustingEntry(null);
                  setAdjPassword("");

                  // +++  الاعتماد على onRefresh الممرر من الأب لتحديث الداتا برمجياً بدون ريفرش للصفحة +++
                  onRefresh();
                } catch (e: any) {
                  toast.error(e.message || "حدث خطأ أثناء معالجة التعديل");
                } finally {
                  setAdjSubmitting(false);
                }
              }}
              className="flex-1 bg-purple-600 text-white py-2 rounded-xl font-bold hover:bg-purple-700 shadow-lg disabled:opacity-50 transition-all"
            >
              {adjSubmitting ? "جاري المعالجة..." : "تأكيد التعديل"}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div className="bg-purple-50 p-3 rounded-xl border border-purple-100">
            <p className="text-[11px] font-bold text-purple-800">صنف: {adjustingEntry?.product_name}</p>
            <p className="text-[10px] text-purple-600 mt-1">المرجع: {adjustingEntry?.reference}</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-black text-slate-600">الإجمالي الصحيح (كراتين)</label>
              <input
                type="number"
                value={newQty.cartons}
                onChange={(e) => setNewQty(p => ({ ...p, cartons: parseInt(e.target.value) || 0 }))}
                className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black focus:border-purple-500 outline-none transition-all"
              />
            </div>
            <div className="space-y-1.5">
              {/* +++ استخراج ppc للتحقق +++ */}
              {(() => {
                const ppc = adjustingEntry?.packs_per_carton || 1;
                const isError = newQty.loose >= ppc;
                return (
                  <>
                    <label className={`text-xs font-black transition-colors ${isError ? "text-red-600 animate-pulse" : "text-slate-600"}`}>
                      الإجمالي الصحيح (حبات) (max {ppc - 1}) {isError && "⚠️"}
                    </label>
                    <div className={`transition-all rounded-lg overflow-hidden border-2 ${isError ? "border-red-500 ring-2 ring-red-200 shadow-[0_0_10px_rgba(239,68,68,0.3)]" : "border-slate-100"}`}>
                      <input
                        type="number"
                        value={newQty.loose}
                        onChange={(e) => setNewQty(p => ({ ...p, loose: parseInt(e.target.value) || 0 }))}
                        className="w-full p-2 text-center font-black outline-none bg-transparent"
                      />
                    </div>
                  </>
                );
              })()}
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-black text-red-600">كلمة مرور المسؤول للتأكيد 🔑</label>
            <input
              type="password"
              value={adjPassword}
              onChange={(e) => setAdjPassword(e.target.value)}
              className="w-full rounded-xl border-2 border-red-100 p-3 text-center font-black focus:border-red-500 outline-none transition-all"
              placeholder="••••••••"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}