import { useState, useEffect, useCallback, useRef } from "react";
import { History, Search, ChevronRight, ChevronLeft, Eye, FileText, Package, RefreshCcw } from "lucide-react";
import type { LedgerEntry } from "./inventoryUtils";
import { getLedgerBadge, formatQty } from "./inventoryUtils";
import { Modal } from "@/components/ui/modal";
import { toast } from "sonner";
import { useAuthFetch } from "@/hooks/useAuthFetch";

interface Props {
  locationId: number;
  refreshKey: number;
}

interface LedgerCursorPage {
  items: LedgerEntry[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
  available_types: string[];
}

export function Tab4Ledger({ locationId, refreshKey }: Props) {
  const authenticatedFetch = useAuthFetch();

  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [filterType, setFilterType] = useState("ALL");
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState<number | null>(null);
  const [availableTypes, setAvailableTypes] = useState<string[]>([]);

  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const [selectedNote, setSelectedNote] = useState<string | null>(null);
  const [selectedReference, setSelectedReference] = useState<string | null>(null);
  const [deliveryNoteItems, setDeliveryNoteItems] = useState<LedgerEntry[]>([]);
  const [referenceLoading, setReferenceLoading] = useState(false);

  const [adjustingEntry, setAdjustingEntry] = useState<LedgerEntry | null>(null);
  const [adjPassword, setAdjPassword] = useState("");
  const [newQty, setNewQty] = useState({ cartons: 0, loose: 0 });
  const [adjSubmitting, setAdjSubmitting] = useState(false);

  const requestSequence = useRef(0);
  const PAGE_SIZE = 20;

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const buildUrl = useCallback((
    cursor: string | null,
    options?: { exactReference?: string; pageSize?: number },
  ) => {
    const params = new URLSearchParams({
      location_id: String(locationId),
      limit: String(options?.pageSize ?? PAGE_SIZE),
    });

    if (cursor) params.set("cursor", cursor);

    if (options?.exactReference) {
      params.set("reference_id", options.exactReference);
    } else {
      if (debouncedSearch.length >= 2) params.set("search", debouncedSearch);
      if (filterType !== "ALL") params.set("reference_type", filterType);
    }

    return `/warehouse/ledger/cursor?${params.toString()}`;
  }, [locationId, debouncedSearch, filterType]);

  const loadPage = useCallback(async (cursor: string | null, targetPage: number) => {
    const sequence = ++requestSequence.current;
    setLoading(true);

    try {
      const data = await authenticatedFetch(buildUrl(cursor)) as LedgerCursorPage;
      if (sequence !== requestSequence.current) return;
      if (!data || !Array.isArray(data.items)) throw new Error("استجابة سجل الحركات غير صالحة.");

      setEntries(data.items);
      setNextCursor(data.next_cursor || null);
      setHasMore(data.has_more === true);
      setPageIndex(targetPage);

      if (typeof data.total === "number") setTotal(data.total);
      if (Array.isArray(data.available_types) && data.available_types.length > 0) {
        setAvailableTypes(data.available_types);
      }
    } catch (e: any) {
      if (sequence !== requestSequence.current) return;
      setEntries([]);
      setNextCursor(null);
      setHasMore(false);
      toast.error(e?.message || "تعذر جلب سجل الحركات.");
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [authenticatedFetch, buildUrl]);

  const resetAndLoad = useCallback(() => {
    requestSequence.current += 1;
    setCursorHistory([null]);
    setPageIndex(0);
    setNextCursor(null);
    setHasMore(false);
    setTotal(null);
    void loadPage(null, 0);
  }, [loadPage]);

  useEffect(() => {
    resetAndLoad();
  }, [resetAndLoad, refreshKey]);

  const goNext = () => {
    if (!hasMore || !nextCursor || loading) return;
    const target = pageIndex + 1;
    setCursorHistory((prev) => {
      const next = prev.slice(0, target);
      next[target] = nextCursor;
      return next;
    });
    void loadPage(nextCursor, target);
  };

  const goPrevious = () => {
    if (pageIndex <= 0 || loading) return;
    const target = pageIndex - 1;
    void loadPage(cursorHistory[target] ?? null, target);
  };

  const fetchAllByReference = useCallback(async (reference: string) => {
    const all: LedgerEntry[] = [];
    let cursor: string | null = null;

    for (let page = 0; page < 50; page += 1) {
      const data = await authenticatedFetch(
        buildUrl(cursor, { exactReference: reference, pageSize: 200 })
      ) as LedgerCursorPage;

      if (!data || !Array.isArray(data.items)) throw new Error("استجابة تفاصيل المرجع غير صالحة.");
      all.push(...data.items);

      if (!data.has_more) return all;
      if (!data.next_cursor) throw new Error("Cursor تفاصيل المرجع غير متسق.");
      cursor = data.next_cursor;
    }

    throw new Error("عدد حركات المرجع تجاوز 10,000 حركة؛ استخدم تقريراً مخصصاً.");
  }, [authenticatedFetch, buildUrl]);

  const openReference = async (reference: string) => {
    setSelectedReference(reference);
    setDeliveryNoteItems([]);
    setReferenceLoading(true);
    try {
      setDeliveryNoteItems(await fetchAllByReference(reference));
    } catch (e: any) {
      toast.error(e?.message || "تعذر جلب تفاصيل المرجع.");
      setSelectedReference(null);
    } finally {
      setReferenceLoading(false);
    }
  };

  const openAdjustment = async (entry: LedgerEntry) => {
    if (!entry.reference) return;
    setReferenceLoading(true);
    try {
      const all = await fetchAllByReference(entry.reference);
      const relevant = all.filter((movement) => (
        movement.product_variant_id === entry.product_variant_id
        && (movement.type === "INBOUND_SUPPLIER" || movement.type === "INBOUND_CORRECTION")
      ));
      const net = relevant.reduce((sum, movement) => sum + movement.quantity_packs, 0);
      const ppc = entry.packs_per_carton || 1;
      const safeNet = Math.max(0, net);
      setAdjustingEntry(entry);
      setNewQty({ cartons: Math.floor(safeNet / ppc), loose: safeNet % ppc });
    } catch (e: any) {
      toast.error(e?.message || "تعذر حساب صافي فاتورة التوريد.");
    } finally {
      setReferenceLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full flex-1 min-h-0 pt-1">
      <div className="relative bg-white rounded-2xl border border-slate-200 flex flex-col shadow-sm flex-1 min-h-0">
        <div className="absolute -top-3.5 right-6 bg-gradient-to-r from-blue-600 to-indigo-700 text-white px-4 py-1.5 rounded-lg text-sm font-black flex items-center gap-2 shadow-md z-20">
          <History className="w-4 h-4" /> سجل الحركات {total !== null ? `(${total})` : ""}
        </div>

        <div className="p-3 pt-5 border-b border-slate-100 flex flex-col sm:flex-row items-center justify-end gap-3 bg-slate-50 rounded-t-2xl">
          <button
            onClick={resetAndLoad}
            disabled={loading}
            className="p-2 rounded-xl border border-slate-200 bg-white text-slate-600 hover:text-blue-600 disabled:opacity-40"
            title="تحديث السجل"
          >
            <RefreshCcw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>

          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm"
          >
            <option value="ALL">جميع الحركات</option>
            {availableTypes.map((type) => (
              <option key={type} value={type}>{getLedgerBadge(type).label}</option>
            ))}
          </select>

          <div className="relative w-full sm:w-72">
            <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="ابحث (حرفان فأكثر)..."
              className="w-full rounded-xl border border-slate-200 bg-white pr-9 pl-3 py-2 text-xs font-bold text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-300 shadow-sm"
            />
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar bg-white rounded-b-2xl">
          <table className="w-full text-sm min-w-[1150px]">
            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur shadow-sm border-b border-slate-200 text-right">
              <tr>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">نوع العملية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المنتج</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد قبل</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الكمية</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الرصيد بعد</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المشرف</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">المرجع</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">الملاحظات</th>
                <th className="px-4 py-3 text-xs font-bold text-slate-500">التاريخ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {loading && (
                <tr><td colSpan={9} className="text-center py-12 text-slate-400 font-bold">جارٍ التحميل...</td></tr>
              )}
              {!loading && entries.length === 0 && (
                <tr><td colSpan={9} className="text-center py-12 text-slate-400">لا توجد حركات مطابقة</td></tr>
              )}
              {!loading && entries.map((entry) => {
                const badge = getLedgerBadge(entry.type);
                const ppc = entry.packs_per_carton || 1;
                const isNeg = entry.quantity_packs < 0;
                const reference = entry.reference || "";

                return (
                  <tr key={entry.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-lg text-[11px] font-black ${badge.bg} ${badge.text}`}>{badge.label}</span></td>
                    <td className="px-4 py-3 font-bold text-slate-800">{entry.product_name}</td>
                    <td className="px-4 py-3 text-slate-500 font-semibold text-xs">{formatQty(entry.balance_before ?? 0, ppc)}</td>
                    <td className={`px-4 py-3 font-bold text-xs ${isNeg ? "text-red-600" : "text-emerald-600"}`}>{isNeg ? "-" : "+"}{formatQty(Math.abs(entry.quantity_packs), ppc)}</td>
                    <td className="px-4 py-3 text-slate-800 font-bold text-xs bg-slate-50/50">{formatQty(entry.balance_after ?? 0, ppc)}</td>
                    <td className="px-4 py-3 text-slate-600 text-xs font-bold">{entry.admin_name || "—"}</td>
                    <td className="px-4 py-3">
                      {reference ? (
                        entry.type === "INBOUND_SUPPLIER" || entry.type === "INBOUND_CORRECTION" ? (
                          <span className="text-[11px] font-bold text-slate-700 bg-slate-100 border border-slate-200 px-2 py-1 rounded-md">فاتورة مورد: {reference}</span>
                        ) : (
                          <button onClick={() => { void openReference(reference); }} className="flex items-center gap-1 text-xs text-blue-700 hover:bg-blue-50 px-2 py-1 rounded-md">
                            <FileText className="w-3.5 h-3.5" /> {reference}
                          </button>
                        )
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {entry.notes ? (
                          <button onClick={() => setSelectedNote(entry.notes)} className="p-1.5 rounded-lg bg-slate-100 text-slate-500 hover:text-slate-800"><Eye className="w-3.5 h-3.5" /></button>
                        ) : <span className="text-slate-300">—</span>}
                        {entry.type === "INBOUND_SUPPLIER" && reference && (
                          <button
                            disabled={referenceLoading}
                            onClick={() => { void openAdjustment(entry); }}
                            className="text-xs text-purple-600 bg-purple-50 px-2 py-1 rounded-lg border border-purple-100 disabled:opacity-40"
                          >
                            تعديل
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-[11px] font-semibold whitespace-nowrap" dir="ltr">
                      {entry.date ? new Date(entry.date.endsWith("Z") || entry.date.includes("+") ? entry.date : `${entry.date}Z`).toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" }) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!loading && (pageIndex > 0 || hasMore) && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50 rounded-b-2xl">
            <span className="text-xs font-bold text-slate-500">صفحة {pageIndex + 1} — {entries.length} حركة</span>
            <div className="flex gap-2">
              <button onClick={goPrevious} disabled={pageIndex === 0} className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30"><ChevronRight className="w-4 h-4" /></button>
              <button onClick={goNext} disabled={!hasMore || !nextCursor} className="p-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-white disabled:opacity-30"><ChevronLeft className="w-4 h-4" /></button>
            </div>
          </div>
        )}
      </div>

      <Modal isOpen={!!selectedNote} onClose={() => setSelectedNote(null)} title="تفاصيل الحركة المحاسبية" maxWidth="max-w-md">
        <div className="p-4 bg-slate-50 rounded-xl border border-slate-100"><p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{selectedNote}</p></div>
      </Modal>

      <Modal
        isOpen={!!selectedReference}
        onClose={() => { setSelectedReference(null); setDeliveryNoteItems([]); }}
        title={`وصل تسليم مجمع: ${selectedReference || ""}`}
        maxWidth="max-w-2xl"
      >
        {referenceLoading ? (
          <div className="py-12 text-center text-sm font-bold text-slate-400">جارٍ تحميل جميع حركات المرجع...</div>
        ) : (
          <div className="border border-slate-200 rounded-xl overflow-hidden max-h-[60vh] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-100 sticky top-0"><tr><th className="px-4 py-2 text-right">الصنف</th><th className="px-4 py-2">الكمية</th><th className="px-4 py-2 text-right">النوع</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {deliveryNoteItems.map((item) => {
                  const badge = getLedgerBadge(item.type);
                  return (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-bold text-slate-800 flex items-center gap-2"><Package className="w-4 h-4 text-slate-400" />{item.product_name}</td>
                      <td className="px-4 py-3 text-center font-bold">{item.quantity_packs < 0 ? "-" : "+"}{formatQty(Math.abs(item.quantity_packs), item.packs_per_carton || 1)}</td>
                      <td className="px-4 py-3"><span className={`inline-flex px-2 py-1 rounded-md text-[10px] font-bold ${badge.bg} ${badge.text}`}>{badge.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

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
                if (!adjustingEntry) return;
                const ppc = adjustingEntry.packs_per_carton || 1;
                if (newQty.loose >= ppc) {
                  toast.error(`عدد الحبات يجب أن يكون أقل من ${ppc}.`);
                  return;
                }
                setAdjSubmitting(true);
                try {
                  const totalPacks = (newQty.cartons * ppc) + newQty.loose;
                  await authenticatedFetch(`/warehouse/ledger/${adjustingEntry.id}/adjust`, {
                    method: "POST",
                    body: JSON.stringify({ password: adjPassword, new_total_packs: totalPacks }),
                  });
                  toast.success("تم تسجيل حركة التصحيح وتحديث المخزون بنجاح ✅");
                  setAdjustingEntry(null);
                  setAdjPassword("");
                  resetAndLoad();
                } catch (e: any) {
                  toast.error(e?.message || "حدث خطأ أثناء التصحيح.");
                } finally {
                  setAdjSubmitting(false);
                }
              }}
              className="flex-1 bg-purple-600 text-white py-2 rounded-xl font-bold hover:bg-purple-700 disabled:opacity-50"
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
            <div>
              <label className="text-xs font-black text-slate-600">الإجمالي الصحيح (كراتين)</label>
              <input type="number" min={0} value={newQty.cartons} onChange={(e) => setNewQty((prev) => ({ ...prev, cartons: Math.max(0, parseInt(e.target.value) || 0) }))} className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black outline-none" />
            </div>
            <div>
              <label className="text-xs font-black text-slate-600">الإجمالي الصحيح (حبات)</label>
              <input type="number" min={0} value={newQty.loose} onChange={(e) => setNewQty((prev) => ({ ...prev, loose: Math.max(0, parseInt(e.target.value) || 0) }))} className="w-full rounded-xl border-2 border-slate-100 p-2 text-center font-black outline-none" />
            </div>
          </div>
          <div>
            <label className="text-xs font-black text-red-600">كلمة مرور المسؤول للتأكيد 🔑</label>
            <input type="password" value={adjPassword} onChange={(e) => setAdjPassword(e.target.value)} className="w-full rounded-xl border-2 border-red-100 p-3 text-center font-black focus:border-red-500 outline-none" placeholder="••••••••" />
          </div>
        </div>
      </Modal>
    </div>
  );
}
