import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, PackagePlus, Plus, RefreshCcw, Search } from "lucide-react";
import { toast } from "sonner";
import { Modal } from "@/components/ui/modal";
import { useAuthFetch } from "@/hooks/useAuthFetch";
import { useInventoryAccess } from "@/hooks/useInventoryAccess";
import { apiErrorMessage } from "@/lib/apiErrors";
import {
  buildProductVariantCreatePayload,
  parseCatalogPage,
  parseProductVariantMutationResponse,
  type ProductVariantCreateDraft,
  type SimpleProductVariant,
} from "./catalog/contracts";

interface Props {
  onCatalogChanged: () => void | Promise<void>;
}

const EMPTY_DRAFT: ProductVariantCreateDraft = {
  variant_name: "",
  sku: "",
  price_per_carton: "",
  packs_per_carton: "",
  price_per_pack: "",
  max_samples: "0",
};

export function TabProductCatalog({ onCatalogChanged }: Props) {
  const authenticatedFetch = useAuthFetch();
  const access = useInventoryAccess();
  const canManage = access.can("catalog.manage");
  const [items, setItems] = useState<SimpleProductVariant[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | null>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestSequence = useRef(0);
  const requestAbortRef = useRef<AbortController | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState<ProductVariantCreateDraft>(EMPTY_DRAFT);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const clean = searchInput.trim();
      setSearch(clean.length >= 2 ? clean : "");
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
      setTotal(null);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const loadCatalog = useCallback(async () => {
    const sequence = ++requestSequence.current;
    requestAbortRef.current?.abort();
    const requestController = new AbortController();
    requestAbortRef.current = requestController;
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "50" });
      if (cursor) params.set("cursor", cursor);
      if (search) params.set("search", search);
      const page = parseCatalogPage(await authenticatedFetch(
        `/product_variants/simple/cursor?${params.toString()}`,
        { signal: requestController.signal },
      ));
      if (sequence !== requestSequence.current) return;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      if (page.total !== null) setTotal(page.total);
    } catch (error: unknown) {
      if (sequence !== requestSequence.current) return;
      if (error instanceof Error && error.name === "AbortError") return;
      setItems([]);
      setNextCursor(null);
      setTotal(null);
      toast.error(apiErrorMessage(error, "تعذر جلب كتالوج المنتجات."));
    } finally {
      if (requestAbortRef.current === requestController) requestAbortRef.current = null;
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [authenticatedFetch, cursor, search]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog, refreshKey]);

  useEffect(() => () => {
    requestSequence.current += 1;
    requestAbortRef.current?.abort();
  }, []);

  const createProduct = async () => {
    setCreating(true);
    try {
      const payload = buildProductVariantCreatePayload(draft);
      const response = parseProductVariantMutationResponse(await authenticatedFetch(
        "/warehouse/product_variants",
        { method: "POST", body: JSON.stringify(payload) },
      ));
      toast.success(response.message);
      setDraft(EMPTY_DRAFT);
      setCreateOpen(false);
      setCursor(null);
      setCursorHistory([]);
      setNextCursor(null);
      setTotal(null);
      setRefreshKey((value) => value + 1);
      await onCatalogChanged();
    } catch (error: unknown) {
      toast.error(apiErrorMessage(error, "تعذر إنشاء المنتج."));
    } finally {
      setCreating(false);
    }
  };

  const field = (key: keyof ProductVariantCreateDraft, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  return (
    <div className="inventory-view inventory-data-panel inventory-surface flex flex-col h-full min-h-0 rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="inventory-panel-header p-4 border-b border-slate-100 flex flex-col sm:flex-row gap-3 items-center justify-between bg-slate-50">
        <div>
          <h2 className="font-black text-slate-800">كتالوج منتجات الشركة</h2>
          <p className="text-xs text-slate-500 mt-1">يعرض الأصناف الفعالة من عقد الكتالوج المركزي.</p>
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-72">
            <Search className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="search"
              value={searchInput}
              maxLength={100}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="ابحث بالاسم أو SKU..."
              className="w-full rounded-xl border border-slate-200 bg-white pr-9 pl-3 py-2 text-xs font-bold outline-none focus:ring-2 focus:ring-blue-300"
            />
          </div>
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading} className="p-2 rounded-xl border border-slate-200 bg-white text-slate-600 disabled:opacity-40" title="تحديث الكتالوج">
            <RefreshCcw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
          {canManage && (
            <button type="button" onClick={() => setCreateOpen(true)} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 text-white px-4 py-2 text-xs font-black">
              <Plus className="w-4 h-4" /> إضافة منتج
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 border-b border-slate-200 text-right">
            <tr>
              <th className="px-5 py-3 text-xs text-slate-500">المنتج</th>
              <th className="px-5 py-3 text-xs text-slate-500">SKU</th>
              <th className="px-5 py-3 text-xs text-slate-500">معامل الكرتونة</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loading && <tr><td colSpan={3} className="py-12 text-center text-slate-400 font-bold">جارٍ تحميل الكتالوج...</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={3} className="py-12 text-center text-slate-400">لا توجد منتجات مطابقة</td></tr>}
            {!loading && items.map((item) => (
              <tr key={item.id} className="hover:bg-slate-50">
                <td className="px-5 py-3 font-bold text-slate-800 flex items-center gap-2"><PackagePlus className="w-4 h-4 text-blue-500" />{item.name}</td>
                <td className="px-5 py-3 text-slate-500 font-mono text-xs">{item.sku || "—"}</td>
                <td className="px-5 py-3 text-slate-700 font-bold">{item.packs_per_carton} حبة / كرتونة</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(cursorHistory.length > 0 || nextCursor) && (
        <div className="flex items-center justify-between px-5 py-3 border-t border-slate-200 bg-slate-50">
          <span className="text-xs font-bold text-slate-500">صفحة {cursorHistory.length + 1}{total !== null ? ` • ${total} صنف` : ""}</span>
          <div className="flex gap-2">
            <button type="button" disabled={!cursorHistory.length || loading} onClick={() => {
              const previous = cursorHistory[cursorHistory.length - 1] ?? null;
              setCursorHistory((current) => current.slice(0, -1));
              setCursor(previous);
            }} className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-30"><ChevronRight className="w-4 h-4" /></button>
            <button type="button" disabled={!nextCursor || loading} onClick={() => {
              if (!nextCursor) return;
              setCursorHistory((current) => [...current, cursor]);
              setCursor(nextCursor);
            }} className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-30"><ChevronLeft className="w-4 h-4" /></button>
          </div>
        </div>
      )}

      <Modal isOpen={createOpen} onClose={() => { if (!creating) setCreateOpen(false); }} title="إضافة منتج إلى كتالوج الشركة" maxWidth="max-w-xl" footer={
        <div className="flex gap-2 w-full">
          <button type="button" disabled={creating} onClick={() => setCreateOpen(false)} className="px-4 py-2 rounded-xl text-slate-600 font-bold">إلغاء</button>
          <button type="button" disabled={creating} onClick={() => void createProduct()} className="flex-1 rounded-xl bg-blue-600 text-white py-2 font-black disabled:opacity-50">
            {creating ? "جارٍ الحفظ..." : "حفظ المنتج"}
          </button>
        </div>
      }>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="text-xs font-bold text-slate-600 sm:col-span-2">اسم المنتج
            <input value={draft.variant_name} maxLength={200} onChange={(event) => field("variant_name", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
          <label className="text-xs font-bold text-slate-600">SKU اختياري
            <input value={draft.sku} maxLength={100} onChange={(event) => field("sku", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
          <label className="text-xs font-bold text-slate-600">عدد الحبات في الكرتونة
            <input type="number" min={1} max={2147483647} step={1} value={draft.packs_per_carton} onChange={(event) => field("packs_per_carton", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
          <label className="text-xs font-bold text-slate-600">سعر الكرتونة
            <input inputMode="decimal" value={draft.price_per_carton} onChange={(event) => field("price_per_carton", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
          <label className="text-xs font-bold text-slate-600">سعر الحبة اختياري
            <input inputMode="decimal" value={draft.price_per_pack} onChange={(event) => field("price_per_pack", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
          <label className="text-xs font-bold text-slate-600">حد العينات اليومي
            <input type="number" min={0} max={2147483647} step={1} value={draft.max_samples} onChange={(event) => field("max_samples", event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 p-2.5 outline-none" />
          </label>
        </div>
        <p className="mt-4 text-xs font-bold text-blue-700 bg-blue-50 border border-blue-200 rounded-xl p-3">إنشاء المنتج مستقل عن المستودعات. تُضبط سياسة الحد الأدنى لاحقاً لكل موقع مخزني.</p>
      </Modal>
    </div>
  );
}
